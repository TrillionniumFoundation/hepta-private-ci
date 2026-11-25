"""Bind complete sources, actual Cargo units and the executed owner libraries."""
import hashlib
import json
from pathlib import Path
import re

from file_update_oracle import cargo, identity

MODULES = ("seek_sequence", "source_file", "file_update", "parser", "patch_effects",
           "patch_summary", "patch_application")
BOUND_MODULES = (*MODULES, "patch_standalone")
STANDALONE_ROUTING_BLOCKS = {
    "native-module-path": "// BEGIN HIA PATCH STANDALONE ROUTING v1: native-module-path\n#[cfg_attr(feature = \"hia-native\", path = \"hia_native_patch_standalone.rs\")]\n// END HIA PATCH STANDALONE ROUTING v1: native-module-path\n",
    "native-environment-export": "// BEGIN HIA PATCH STANDALONE ROUTING v1: native-environment-export\n#[cfg(feature = \"hia-native\")]\n#[doc(hidden)]\npub use standalone_executable::apply_patch_file_update_mode_from_env;\n// END HIA PATCH STANDALONE ROUTING v1: native-environment-export\n",
    "legacy-environment-function": "// BEGIN HIA PATCH STANDALONE ROUTING v1: legacy-environment-function\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA PATCH STANDALONE ROUTING v1: legacy-environment-function\n"
}
APPLICATION_ROUTING_BLOCKS = {
    "native-module": "// BEGIN HIA PATCH APPLICATION ROUTING v1: native-module\n#[cfg(feature = \"hia-native\")]\nmod hia_native_patch_application;\n#[cfg(feature = \"hia-native\")]\nuse hia_native_patch_application::apply_hunks_with_options;\n#[cfg(feature = \"hia-native\")]\npub use hia_native_patch_application::apply_patch_with_options;\n// END HIA PATCH APPLICATION ROUTING v1: native-module\n",
    "legacy-parse-error-import": "// BEGIN HIA PATCH APPLICATION ROUTING v1: legacy-parse-error-import\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA PATCH APPLICATION ROUTING v1: legacy-parse-error-import\n",
    "legacy-patch-function": "// BEGIN HIA PATCH APPLICATION ROUTING v1: legacy-patch-function\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA PATCH APPLICATION ROUTING v1: legacy-patch-function\n",
    "legacy-hunks-function": "// BEGIN HIA PATCH APPLICATION ROUTING v1: legacy-hunks-function\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA PATCH APPLICATION ROUTING v1: legacy-hunks-function\n"
}
ORIGINAL_LIB_SHA256 = "7daa1b1f7df70220bcc2bd45e5e169246261c689b388fbb030c6b60b9d5db07a"
ORIGINAL_LIB_BLOB = "1450223f39c2ce2e3ec6709df58a612d681e4b0d"
ORIGINAL_TESTS = frozenset((
    "test_add_file_hunk_creates_file_with_contents",
    "test_apply_patch_hunks_accept_relative_and_absolute_paths",
    "test_delete_file_hunk_removes_file",
    "test_update_file_hunk_modifies_content",
    "test_update_file_hunk_can_move_file",
    "test_failed_move_returns_committed_destination_delta",
    "test_multiple_update_chunks_apply_to_single_file",
    "test_update_file_hunk_interleaved_changes",
    "test_pure_addition_chunk_followed_by_removal",
    "test_update_line_with_unicode_dash",
    "test_apply_patch_fails_on_write_error",
    "test_unreadable_destinations_return_inexact_delta",
    "test_delete_symlink_returns_inexact_delta",
))
OBSERVER_HASHES = {
    "driver.rs": "248138e83e798b14f5e8d48bf28da7042e2486ab00d19c339b7f091fb941c680",
    "observed_fs.rs": "bec939e2e1804f1c0cfc2b7ff222c167c9c55c824a732d20840afddfae040d8b",
}
PROFILE = {"opt_level": "0", "debuginfo": 0, "debug_assertions": True,
           "overflow_checks": True, "test": False}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def original_lib(snapshot, manifest):
    path = identity.CRATE + "/src/lib.rs"
    record = manifest["files"][path]
    require((record["bytes"], record["blob"], record["sha256"]) ==
            (47657, ORIGINAL_LIB_BLOB, ORIGINAL_LIB_SHA256),
            "complete immutable original lib.rs identity differs")
    require(identity.sha(snapshot / path) == ORIGINAL_LIB_SHA256,
            "complete original library bytes differ")
    return record


def recover_lib(producer):
    """Remove only exact routing additions, never extract algorithm fragments."""
    source = producer / identity.CRATE / "src/lib.rs"
    data = source.read_bytes()
    restored = data
    for name, block in STANDALONE_ROUTING_BLOCKS.items():
        encoded = block.encode()
        require(restored.count(encoded) == 1,
                "standalone routing is absent or duplicated: " + name)
        restored = restored.replace(encoded, b"", 1)
    require(b"HIA PATCH STANDALONE ROUTING" not in restored,
            "unreviewed standalone routing remains")
    for name, block in APPLICATION_ROUTING_BLOCKS.items():
        encoded = block.encode()
        require(restored.count(encoded) == 1,
                "application routing is absent or duplicated: " + name)
        restored = restored.replace(encoded, b"", 1)
    require(b"HIA PATCH APPLICATION ROUTING" not in restored,
            "unreviewed application routing remains")
    native = '#[cfg(feature = "hia-native")]\n'
    legacy = '#[cfg(not(feature = "hia-native"))]\n'
    blocks = [
        native + "mod hia_native_patch_effects;\n",
        native + "use hia_native_patch_effects::apply_hunks_to_files;\n",
        native + "mod hia_native_patch_summary;\n",
        native + "pub use hia_native_patch_summary::print_summary;\n",
        native + "mod hia_native_unified_diff;\n",
        native + "mod hia_native_unified_diff_policy;\n",
    ]
    for statement in (
        "use std::io;", "use anyhow::Context;",
        "use codex_exec_server::CreateDirectoryOptions;",
        "use codex_exec_server::GetMetadataOptions;",
        "use codex_exec_server::ReadFileOptions;",
        "use codex_exec_server::RemoveOptions;",
        "use codex_exec_server::WriteFileOptions;",
        "use file_update::AppliedPatch;",
        "use file_update::derive_new_contents_from_chunks;",
    ):
        before = (legacy + statement + "\n").encode()
        require(restored.count(before) == 1, "legacy import routing is absent or duplicated")
        restored = restored.replace(before, (statement + "\n").encode(), 1)
    for function in (
        "apply_hunks_to_files", "ensure_not_directory",
        "remove_failure_was_side_effect_free", "read_optional_file_text_for_delta",
        "note_existing_path_delta_support", "write_file_with_missing_parent_retry",
    ):
        after = "async fn " + function + "("
        before = (legacy + after).encode()
        require(restored.count(before) == 1, "legacy owner routing is absent or duplicated")
        restored = restored.replace(before, after.encode(), 1)
    summary = "pub fn print_summary("
    guarded_summary = (legacy + summary).encode()
    require(restored.count(guarded_summary) == 1, "legacy summary routing differs")
    restored = restored.replace(guarded_summary, summary.encode(), 1)
    # These four inherited module declarations are the complete a201 -> 2ff
    # lib.rs difference, independently observed before effects routing.
    blocks.extend(native + "mod " + name + ";\n" for name in (
        "hia_native_file_update", "hia_native_parser",
        "hia_native_streaming_parser", "hia_native_text_file",
    ))
    for block in blocks:
        encoded = block.encode()
        require(restored.count(encoded) == 1, "native module/import routing differs")
        restored = restored.replace(encoded, b"", 1)
    digest = hashlib.sha256(restored).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(restored)).encode() + b"\0" + restored).hexdigest()
    require((len(restored), digest, blob) ==
            (47657, ORIGINAL_LIB_SHA256, ORIGINAL_LIB_BLOB),
            "inverse routing must recover the entire unchanged original lib.rs")
    return {"current_lib_sha256": hashlib.sha256(data).hexdigest(),
            "exact_routing_rewrites": 33, "restored_bytes": len(restored),
            "restored_sha256": digest, "restored_git_blob": blob}


def native_inputs(producer, library):
    report_path = library / "build.json"
    build = json.loads(report_path.read_text())
    require(build.get("status") == "built" and build.get("compiler_fixed_point") is True,
            "a real native compiler fixed point and successful build are required")
    modules = {}
    for name in BOUND_MODULES:
        record = build["modules"][name]
        source = producer / "hia" / (name + ".hepta")
        archive = library / ("libcodex_hia_" + name + ".a")
        abi = record["codex_link_abi"]
        require(record["source_sha256"] == identity.sha(source),
                "stale native source binding: " + name)
        require(abi["archive_sha256"] == identity.sha(archive) and
                abi["symbol"] == "codex_hia_" + name,
                "stale native archive/symbol binding: " + name)
        modules[name] = {"source_sha256": identity.sha(source),
                         "archive_sha256": identity.sha(archive), "symbol": abi["symbol"]}
    sources = {}
    for relative in (
        "codex-rs/apply-patch/src/lib.rs",
        "codex-rs/apply-patch/src/hia_native_patch_effects.rs",
        "hia/patch_effects_buffer_contract.json",
        "codex-rs/apply-patch/src/hia_native_patch_summary.rs",
        "hia/patch_summary_buffer_contract.json",
        "codex-rs/apply-patch/src/hia_native_patch_application.rs",
        "hia/patch_application_buffer_contract.json",
        "codex-rs/apply-patch/src/hia_native_patch_standalone.rs",
        "codex-rs/apply-patch/src/standalone_executable.rs",
        "codex-rs/apply-patch/src/main.rs",
        "hia/patch_standalone_buffer_contract.json",
    ):
        sources[relative] = identity.sha(producer / relative)
    return {"build_report_sha256": identity.sha(report_path),
            "compiler_sha256": build["compiler_sha256"], "modules": modules,
            "current_production_sources": sources}


def shared_serde(graph, packages):
    """Select by actual dependency identities, not just package/features names."""
    records = {}
    cache = {}

    def fingerprint(unit):
        key = (unit["package_id"], tuple(unit["files"]))
        if key in cache:
            return cache[key]
        names = [name for name in unit["files"] if name.endswith(".rlib")]
        require(len(names) == 1, "fingerprint unit must identify one real rlib")
        file = graph["files"][names[0]]
        require(file["package_id"] == unit["package_id"], "unit/file package differs")
        source = Path(file["source"]).resolve(strict=True)
        package = packages[unit["package_id"]]
        suffix = source.stem.rsplit("-", 1)[-1]
        require(re.fullmatch(r"[0-9a-f]{16}", suffix) is not None,
                "actual Cargo artifact suffix differs")
        base = source.parent.parent / ".fingerprint" / (
            package["name"] + "-" + suffix) / ("lib-" + unit["target"]["name"])
        json_path = base.with_suffix(".json")
        require(identity.sha(json_path) == unit["fingerprint_sha256"],
                "fingerprint JSON differs from actual admitted artifact")
        raw = base.read_bytes()
        require(re.fullmatch(rb"[0-9a-f]{16}", raw) is not None,
                "Cargo fingerprint identity is not exactly 16 hex bytes")
        value = int.from_bytes(bytes.fromhex(raw.decode()), "little")
        body = json.loads(json_path.read_text())
        require(json.loads(body["features"]) == unit["features"],
                "actual fingerprint features differ")
        deps = {}
        for dep in body["deps"]:
            require(len(dep) == 4 and isinstance(dep[1], str) and
                    type(dep[3]) is int and 0 <= dep[3] < 2**64 and dep[1] not in deps,
                    "ambiguous or invalid Cargo fingerprint dependency")
            deps[dep[1]] = dep[3]
        for path in (base, json_path):
            records[str(path)] = identity.sha(path)
        result = {"identity": value, "deps": deps, "unit": unit}
        cache[key] = result
        return result

    def dependency(target, expected):
        matches = []
        for unit in graph["units"]:
            if unit["target"]["name"] == target:
                record = fingerprint(unit)
                if record["identity"] == expected:
                    matches.append(record)
        require(len(matches) == 1, "missing/ambiguous real dependency identity: " + target)
        return matches[0]

    execute = fingerprint(graph["direct"]["codex_exec_server"]["unit"])
    filesystem = dependency("codex_file_system", execute["deps"]["codex_file_system"])
    json_unit = dependency("serde_json", execute["deps"]["serde_json"])
    serde = dependency("serde", filesystem["deps"]["serde"])
    require(serde["identity"] == execute["deps"]["serde"],
            "exec-server and file-system select different serde identities")
    require(serde["deps"]["serde_core"] == json_unit["deps"]["serde_core"],
            "FileSystemSandboxContext and serde_json have different serde_core identities")
    core = dependency("serde_core", json_unit["deps"]["serde_core"])
    unit = json_unit["unit"]
    require(unit["package_id"] ==
            "registry+https://github.com/rust-lang/crates.io-index#serde_json@1.0.154",
            "locked serde_json package differs")
    require(unit["profile"] == PROFILE, "actual serde_json profile differs")
    names = [name for name in unit["files"] if name.endswith(".rlib")]
    require(len(names) == 1, "actual serde_json library is ambiguous")
    library = graph["files"][names[0]]
    require(identity.sha(library["path"]) == library["sha256"],
            "selected real serde_json library changed")
    return {"library": library, "unit": unit,
            "shared_serde_core_identity": core["identity"],
            "filesystem_identity": filesystem["identity"],
            "serde_identity": serde["identity"], "serde_json_identity": json_unit["identity"],
            "fingerprint_inputs": records,
            "chain": [execute, filesystem, serde, json_unit, core]}


def verify_fingerprints(receipt):
    for path, digest in receipt["fingerprint_inputs"].items():
        require(identity.sha(path) == digest, "a selected Cargo dependency identity changed")


def build_owners(rustc, producer, snapshot, support, original, default, native, serde,
                 env, commands, output):
    for name in identity.REQUIRED:
        for field in ("package_id", "target", "features", "profile"):
            require(default["direct"][name]["unit"][field] ==
                    native["direct"][name]["unit"][field],
                    "default/native direct dependency changed: " + name + "/" + field)
    for field in ("package_id", "target", "features", "profile"):
        require(serde["default"]["unit"][field] == serde["native"]["unit"][field],
                "default/native selected serde_json differs: " + field)
    child = cargo.reference_environment(producer, env)
    child["CARGO_TARGET_DIR"] = original["lane"]["target"]
    child["CARGO_MANIFEST_DIR"] = str(snapshot / identity.CRATE)
    original_source = snapshot / identity.CRATE / "src/lib.rs"
    flags = cargo.flags(rustc, original, original=True)
    reference = output / "libcodex_apply_patch_original.rlib"
    commands.run("effects-compile-complete-original-lib", flags + [
        "--crate-name", "codex_apply_patch_original", "--crate-type", "rlib",
        original_source, "-o", reference], cwd=producer, env=child)
    tests = output / "original-crate-tests"
    commands.run("effects-compile-complete-original-tests", flags + [
        "--crate-name", "codex_apply_patch_original_tests", "--test",
        original_source, "-o", tests], cwd=producer, env=child)
    reference_hash, tests_hash = identity.sha(reference), identity.sha(tests)
    listing = commands.run("effects-list-original-tests",
                           [tests, "--list"], cwd=producer, env=child).read_text()
    names = {line.removesuffix(": test") for line in listing.splitlines()
             if line.startswith("tests::") and line.endswith(": test")}
    expected = {"tests::" + name for name in ORIGINAL_TESTS}
    require(names == expected, "the exact original 13 root-test inventory changed")
    for index, name in enumerate(sorted(expected)):
        text = commands.run("effects-original-root-test-" + str(index), [
            tests, "--exact", name, "--nocapture", "--test-threads=1"],
            cwd=producer, env=child).read_text()
        require("test result: ok. 1 passed; 0 failed; 0 ignored;" in text and
                "test " + name + " ... ok" in text,
                "an unchanged original root test did not execute: " + name)
    binaries = {"original": output / "effects-original-observer",
                "native": output / "effects-native-observer"}
    for side, binary in binaries.items():
        graph = original if side == "original" else native
        extra = ["--extern", "serde_json=" + serde[side]["library"]["path"]]
        if side == "original":
            extra += ["--extern", "codex_apply_patch=" + str(reference)]
        commands.run("effects-compile-public-" + side,
                     cargo.flags(rustc, graph, original=side == "original") + extra + [
                         "--crate-name", "patch_effects_public_" + side,
                         support / "driver.rs", "-o", binary],
                     cwd=producer / "codex-rs", env=child if side == "original" else env)
        symbols = commands.run("effects-public-symbols-" + side,
                               ["nm", "--defined-only", binary], cwd=producer, env=env).read_text()
        for module in MODULES:
            matches = re.findall(r"\b[Tt] codex_hia_" + module + r"$", symbols, re.MULTILINE)
            require(len(matches) == (1 if side == "native" else 0),
                    "real public executable has incorrect native dispatch: " + side + "/" + module)
    receipts = {
        "original_library": {"path": str(reference), "sha256": reference_hash},
        "original_tests_binary": {"path": str(tests), "sha256": tests_hash},
        "original_tests": {"names": sorted(expected), "passed": 13, "skipped": 0,
                           "scope": "13 unchanged root tests; other complete crate tests are not claimed."},
        "binaries": {side: {"path": str(path), "sha256": identity.sha(path)}
                     for side, path in binaries.items()},
    }
    require(identity.sha(reference) == reference_hash and identity.sha(tests) == tests_hash,
            "the original library/test executable changed during compilation or execution")
    return binaries, receipts


def verify_parent_lanes(parent, parent_work, producer, graphs, bind):
    """Require exact three-lane receipts; a two-lane report cannot qualify a child."""
    sides = {"original", "default", "native"}
    for name in ("actual_cargo_graph_manifests", "actual_cargo_builds",
                 "three_way_cargo_metadata", "three_way_cargo_graphs",
                 "actual_serde_identity"):
        require(set(parent.get(name, {})) == sides, "incomplete prerequisite lane inventory: " + name)
    require(set(graphs) == sides, "missing original/default/native prerequisite graph")
    metadata = parent["three_way_cargo_metadata"]
    require(metadata["default"] == parent["cargo_metadata_inputs"],
            "legacy metadata view differs from the actual default lane")
    original = Path(graphs["original"]["lane"]["source"]).resolve(strict=True)
    require(original != producer and not original.is_relative_to(producer)
            and not producer.is_relative_to(original),
            "original and candidate source checkouts must be disjoint")
    identity.outside(parent_work, (original, producer))
    for side, graph in graphs.items():
        require(graph["lane"] == parent["three_way_cargo_graphs"][side],
                "prerequisite Cargo lane binding differs: " + side)
        path = bind(parent_work / (side + "-metadata-source-inputs.json"))
        require(json.loads(path.read_text()) == metadata[side],
                "prerequisite Cargo metadata receipt differs: " + side)
        selected = parent["actual_serde_identity"][side]
        verify_fingerprints(selected)
        require(graph["files"].get(Path(selected["library"]["path"]).name) == selected["library"]
                and selected["unit"] in graph["units"],
                "prerequisite serde unit escaped its Cargo lane")
        bind(selected["library"]["path"], selected["library"]["sha256"])
        for filename, digest in selected["fingerprint_inputs"].items():
            bind(filename, digest)
        unit = graph["direct"]["codex_apply_patch"]["unit"]
        require(unit["features"] == (["hia-native"] if side == "native" else [])
                and unit["profile"] == PROFILE,
                "prerequisite Cargo lane owner profile differs: " + side)
    cargo.verify_three_graphs(graphs, metadata, original, producer)
    command_path = bind(parent["commands_file"])
    require(command_path == parent_work / "commands/commands.json",
            "prerequisite command log escaped its work directory")
    commands_log = json.loads(command_path.read_text())
    for side, graph in graphs.items():
        label = "cargo-" + side
        captured = [record for record in commands_log if record["label"] == label]
        require(len(captured) == 1 and captured[0]["returncode"] == 0,
                "missing actual prerequisite Cargo build: " + side)
        record = captured[0]
        log = bind(record["stdout"], graph["artifact_jsonl_sha256"])
        require(log.is_relative_to(parent_work)
                and log.stat().st_size == record["stdout_bytes"]
                and record["stdout_sha256"] == graph["artifact_jsonl_sha256"],
                "prerequisite Cargo artifact log binding differs: " + side)
        require(record["cwd"] == str(Path(graph["lane"]["source"]) / "codex-rs"),
                "prerequisite Cargo build ran in the wrong source lane")
        metadata_label = "cargo-metadata" if side == "default" else label + "-metadata"
        observed = [record for record in commands_log if record["label"] == metadata_label]
        require(len(observed) == 1 and observed[0]["returncode"] == 0,
                "missing actual prerequisite metadata command: " + side)
        observed = observed[0]
        metadata_log = bind(observed["stdout"], metadata[side]["metadata_sha256"])
        require(metadata_log.is_relative_to(parent_work)
                and observed["stdout_sha256"] == metadata[side]["metadata_sha256"]
                and metadata_log.stat().st_size == observed["stdout_bytes"]
                and observed["cwd"] == record["cwd"],
                "prerequisite metadata log binding differs: " + side)
        resolved = json.loads(metadata_log.read_text())
        require(Path(resolved["workspace_root"]).resolve(strict=True) ==
                Path(graph["lane"]["source"]) / "codex-rs"
                and Path(resolved["target_directory"]).resolve(strict=True) ==
                Path(graph["lane"]["target"]),
                "prerequisite metadata source or target lane differs: " + side)
    compiled = [record for record in commands_log
                if record["label"] == "effects-compile-complete-original-lib"]
    require(len(compiled) == 1 and compiled[0]["returncode"] == 0,
            "missing prerequisite original library compile")
    argv = compiled[0]["argv"]
    flags = [str(value) for value in cargo.flags(argv[0], graphs["original"], original=True)]
    reference = bind(parent["original_library"]["path"], parent["original_library"]["sha256"])
    require(reference.parent == parent_work,
            "original library escaped its qualified work directory")
    expected = flags + ["--crate-name", "codex_apply_patch_original", "--crate-type", "rlib",
                        str(parent_work / "original" / identity.CRATE / "src/lib.rs"),
                        "-o", str(reference)]
    require(argv == expected and compiled[0]["cwd"] == str(producer),
            "original library was not compiled exclusively with the original Cargo graph")
    return original, metadata


def original_compile_environment(producer, env, graph):
    child = cargo.reference_environment(producer, env)
    child["CARGO_TARGET_DIR"] = graph["lane"]["target"]
    return child


def parent_original_checkout(parent_path, producer):
    """Read the original source boundary before creating any child work files."""
    parent = json.loads(parent_path.read_text())
    lanes = parent.get("three_way_cargo_graphs", {})
    require(set(lanes) == {"original", "default", "native"},
            "prerequisite lacks the three source lanes")
    original = Path(lanes["original"]["source"]).resolve(strict=True)
    require(original != producer and not original.is_relative_to(producer)
            and not producer.is_relative_to(original),
            "original and candidate source checkouts must be disjoint")
    require(identity.clean_identity(original)["commit"] == identity.BASE,
            "prerequisite original checkout is not the pinned commit")
    return original
