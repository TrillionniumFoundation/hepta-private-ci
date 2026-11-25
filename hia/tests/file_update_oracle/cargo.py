"""Admit and stage real complete Cargo artifact graphs, then compile whole owners."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import types

from .identity import CRATE, REQUIRED, RUSTC_COMMIT, RUSTC_SHA256, sha

ORIGINAL_TESTS = frozenset((
    "file_update::tests::test_unified_diff",
    "file_update::tests::test_unified_diff_first_line_replacement",
    "file_update::tests::test_unified_diff_last_line_replacement",
    "file_update::tests::test_unified_diff_insert_at_eof",
    "file_update::tests::test_unified_diff_interleaved_changes",
))


class Commands:
    def __init__(self, output):
        self.output = output
        self.records = []

    def run(self, label, argv, *, cwd, env, jsonl=False):
        stdout = self.output / (label + (".jsonl" if jsonl else ".stdout"))
        stderr = self.output / (label + ".stderr")
        with stdout.open("xb") as out, stderr.open("xb") as err:
            result = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, stdout=out, stderr=err)
        self.records.append({"label": label, "argv": [str(a) for a in argv], "cwd": str(cwd),
            "returncode": result.returncode, "stdout": str(stdout), "stderr": str(stderr),
            "stdout_bytes": stdout.stat().st_size, "stdout_sha256": sha(stdout),
            "stderr_bytes": stderr.stat().st_size, "stderr_sha256": sha(stderr)})
        (self.output / "commands.json").write_text(json.dumps(self.records, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError(f"actual command failed: {label}; see {stderr}")
        return stdout


def policy_environment(producer, rustc, env):
    if not env.get("RUSTC_WRAPPER") and not env.get("RUSTC_WORKSPACE_WRAPPER"):
        return None
    path = producer / "hia/unified_policy_ci.py"
    module = types.ModuleType("unified_policy_ci_admission")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module.admit_environment(producer, rustc, env)


def compiler(rustc, commands, producer):
    rustc = rustc.resolve(strict=True)
    if sha(rustc) != RUSTC_SHA256:
        raise RuntimeError("the fixed Linux Rust 1.96.1 compiler SHA differs")
    env = os.environ.copy()
    wrapper = policy_environment(producer, rustc, env)
    env.update(RUSTC=str(rustc), RUSTUP_TOOLCHAIN="1.96.1",
               CARGO_INCREMENTAL="0", CARGO_PROFILE_DEV_DEBUG="0", CARGO_PROFILE_TEST_DEBUG="0")
    env.setdefault("CARGO_BUILD_JOBS", "1")
    version = commands.run("rustc-version", [rustc, "-vV"], cwd=producer, env=env).read_text()
    if f"commit-hash: {RUSTC_COMMIT}" not in version or "host: x86_64-unknown-linux-gnu" not in version:
        raise RuntimeError("the fixed compiler commit/host differs")
    cargo = rustc.parent / "cargo"
    cargo_version = commands.run("cargo-version", [cargo, "--version"], cwd=producer, env=env).read_text()
    if not cargo_version.startswith("cargo 1.96.1 "):
        raise RuntimeError("Cargo is not from the fixed toolchain")
    return rustc, cargo, env, {"rustc_sha256": sha(rustc), "rustc_version": version,
                              "cargo_sha256": sha(cargo), "cargo_version": cargo_version,
                              "policy_wrapper": wrapper}


def metadata(cargo, producer, env, commands):
    path = commands.run("cargo-metadata", [cargo, "metadata", "--locked", "--format-version=1",
        "--filter-platform", "x86_64-unknown-linux-gnu", "--no-default-features"],
        cwd=producer / "codex-rs", env=env, jsonl=True)
    graph = json.loads(path.read_text())
    packages = {p["id"]: p for p in graph["packages"]}
    if len(packages) != len(graph["packages"]):
        raise RuntimeError("duplicate real metadata package IDs")
    owners = [p for p in packages.values() if
              Path(p["manifest_path"]).resolve() == producer / CRATE / "Cargo.toml"]
    if len(owners) != 1 or owners[0]["name"] != "codex-apply-patch":
        raise RuntimeError("metadata is not bound to the actual owner manifest path")
    owner = owners[0]
    nodes = [n for n in graph["resolve"]["nodes"] if n["id"] == owner["id"]]
    if len(nodes) != 1:
        raise RuntimeError("missing owner resolution")
    dependencies = {d["name"].replace("-", "_"): d["pkg"] for d in nodes[0]["deps"]}
    if set(dependencies) != REQUIRED:
        raise RuntimeError("the resolved complete 14-dependency set changed")
    source_sets = {}
    for package in packages.values():
        manifest = Path(package["manifest_path"]).resolve(strict=True)
        if package["source"] is None and not manifest.is_relative_to(producer):
            raise RuntimeError("a path dependency escaped the actual producing checkout")
        source_sets[package["id"]] = {"manifest_path": str(manifest),
            "manifest_sha256": sha(manifest), "source": package["source"],
            "name": package["name"], "version": package["version"]}
    return graph, packages, owner, dependencies, {"metadata_sha256": sha(path), "packages": source_sets}


def capture(cargo, producer, env, native, commands):
    child = env.copy()
    if native:
        admitted_policy = policy_environment(producer, Path(child["RUSTC"]), child)
        if admitted_policy is None:
            raise RuntimeError("native owner qualification requires an admitted policy wrapper and configuration")
    if not native:
        child.pop("CODEX_HIA_NATIVE_LIB_DIR", None)
    args = [cargo, "build", "--locked", "--no-default-features", "-p", "codex-apply-patch",
            "--tests", "--message-format=json-render-diagnostics"]
    if native:
        args += ["--features", "hia-native"]
    result = commands.run("cargo-native" if native else "cargo-default", args,
                          cwd=producer / "codex-rs", env=child, jsonl=True)
    if native:
        if policy_environment(producer, Path(child["RUSTC"]), child) != admitted_policy:
            raise RuntimeError("policy environment changed during actual Cargo compilation")
        verified = commands.run("cargo-native-policy-admission", [sys.executable,
            producer / "hia/similar_policy.py", "--verify-cargo-log", result],
            cwd=producer / "codex-rs", env=child)
        record = json.loads(verified.read_text())
        binding = {"path": str(result.resolve()), "bytes": result.stat().st_size, "sha256": sha(result)}
        if (record.get("passed") is not True or record.get("cargo_log") != binding
                or not record.get("consumer_artifacts")
                or any(item["policy_mode"] != 0 for item in record["consumer_artifacts"])):
            raise RuntimeError("actual Cargo native artifacts lack policy receipt admission")
    return result


def verify_library_copy(source, staged, digest, size):
    """Require a byte-exact snapshot with no shared inode with its producer."""
    if (not stat.S_ISREG(source.lstat().st_mode)
            or not stat.S_ISREG(staged.lstat().st_mode)
            or source.samefile(staged) or staged.stat().st_nlink != 1
            or source.stat().st_size != size or staged.stat().st_size != size
            or sha(source) != digest or sha(staged) != digest):
        raise RuntimeError("staged library is not an independent exact copy")


def stage_library(source, staged, digest):
    size = source.stat().st_size
    # Exclusive creation: never alias a mutable Cargo target inode, or
    # overwrite an existing snapshot after a partial or concurrent attempt.
    with source.open("rb") as inp, staged.open("xb") as out:
        shutil.copyfileobj(inp, out)
    verify_library_copy(source, staged, digest, size)
    return size


def native_search_source(raw, target_dir):
    """Classify target-owned -L arguments without inspecting external directories."""
    kind, separator, path = raw.partition("=")
    if separator and kind in {"native", "dependency", "crate", "framework", "all"}:
        prefix = kind + "="
    else:
        prefix, path = "", raw
    requested = Path(path)
    if not requested.is_absolute():
        return prefix, None
    absolute = Path(os.path.normpath(requested))
    if not absolute.is_relative_to(target_dir):
        return prefix, None
    if (absolute == target_dir or absolute.resolve(strict=True) != absolute
            or requested.resolve(strict=True) != absolute):
        raise RuntimeError("target-owned native search root is not an isolated canonical directory")
    return prefix, absolute


def native_search_inventory(root):
    """Include empty directories; reject nonregular entries instead of following links."""
    if not stat.S_ISDIR(root.lstat().st_mode) or root.resolve(strict=True) != root:
        raise RuntimeError("native search root is not a canonical directory")
    records = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            records[relative] = {"kind": "directory"}
        elif stat.S_ISREG(mode):
            records[relative] = {"kind": "file", "bytes": path.stat().st_size,
                                 "sha256": sha(path)}
        else:
            raise RuntimeError("native search directory contains a nonregular entry")
    return records


def stage_native_search(paths, target_dir, stage):
    """Snapshot target-owned build-script search roots; preserve other -L arguments."""
    target_dir = target_dir.resolve(strict=True)
    stage = stage.resolve()
    if stage.is_relative_to(target_dir) or target_dir.is_relative_to(stage):
        raise RuntimeError("native search staging must be outside the actual target directory")
    stage.mkdir()
    records = []
    for index, raw in enumerate(sorted(set(paths))):
        prefix, source = native_search_source(raw, target_dir)
        if source is None:
            records.append({"original": raw, "effective": raw,
                            "scope": "external_or_relative_unisolated"})
            continue
        destination = stage / str(index)
        entries = native_search_inventory(source)
        destination.mkdir()
        for relative, record in entries.items():
            output = destination / relative
            if record["kind"] == "directory":
                output.mkdir()
            else:
                size = stage_library(source / relative, output, record["sha256"])
                if size != record["bytes"]:
                    raise RuntimeError("native search input size changed during staging")
        records.append({"original": raw, "effective": prefix + str(destination),
                        "scope": "target_owned_snapshot", "source": str(source),
                        "staged": str(destination), "entries": entries})
    result = {"native_paths": [r["effective"] for r in records],
              "native_search": records, "native_search_stage": str(stage),
              "native_search_target_dir": str(target_dir),
              "native_search_fully_isolated": all(
                  r["scope"] == "target_owned_snapshot" for r in records)}
    verify_native_search(result)
    return result


def verify_native_search(graph):
    stage = Path(graph["native_search_stage"])
    target = Path(graph["native_search_target_dir"])
    records = graph["native_search"]
    originals = [r["original"] for r in records]
    if (originals != sorted(set(originals))
            or graph["native_paths"] != [r["effective"] for r in records]
            or target.resolve(strict=True) != target
            or stage.resolve(strict=True) != stage
            or not stat.S_ISDIR(stage.lstat().st_mode)
            or stage.is_relative_to(target) or target.is_relative_to(stage)):
        raise RuntimeError("native search argument or staging identity changed")
    expected_directories = set()
    for index, record in enumerate(records):
        raw = record["original"]
        prefix, source = native_search_source(raw, target)
        if source is None:
            if record != {"original": raw, "effective": raw,
                          "scope": "external_or_relative_unisolated"}:
                raise RuntimeError("unisolated native search argument changed")
            continue
        destination = stage / str(index)
        expected_directories.add(destination.name)
        if (record["scope"] != "target_owned_snapshot"
                or record["source"] != str(source)
                or record["staged"] != str(destination)
                or record["effective"] != prefix + str(destination)
                or native_search_inventory(source) != record["entries"]
                or native_search_inventory(destination) != record["entries"]):
            raise RuntimeError("native search snapshot or source inventory changed")
        for relative, entry in record["entries"].items():
            if entry["kind"] == "file":
                verify_library_copy(source / relative, destination / relative,
                                    entry["sha256"], entry["bytes"])
    if {p.name for p in stage.iterdir()} != expected_directories:
        raise RuntimeError("native search staging contains missing or extra directories")
    if graph["native_search_fully_isolated"] is not all(
            r["scope"] == "target_owned_snapshot" for r in records):
        raise RuntimeError("native search isolation scope changed")


def admit(path, packages, owner, dependencies, target_dir, stage, *, native):
    messages = [json.loads(line) for line in path.read_text().splitlines()]
    endings = [m for m in messages if m.get("reason") == "build-finished"]
    if len(endings) != 1 or endings[0].get("success") is not True or messages[-1] != endings[0]:
        raise RuntimeError("Cargo must emit exactly one final successful build-finished record")
    stage.mkdir()
    direct = {name: [] for name in REQUIRED | {"codex_apply_patch"}}
    wanted = {**dependencies, "codex_apply_patch": owner["id"]}
    files, units, native_paths = {}, [], set()
    for message in messages:
        if message.get("reason") == "build-script-executed":
            native_paths.update(message.get("linked_paths", []))
        if message.get("reason") != "compiler-artifact":
            continue
        package = packages.get(message["package_id"])
        if package is None:
            raise RuntimeError("artifact package is absent from actual Cargo metadata")
        target = message["target"]
        if target not in package["targets"]:
            raise RuntimeError("artifact target/src_path differs from actual package metadata")
        features = message["features"]
        if features != sorted(set(features)) or not set(features) <= set(package["features"]):
            raise RuntimeError("artifact features are not canonical declared features")
        profile = message["profile"]
        library_files = [Path(f).resolve(strict=True) for f in message["filenames"]
                         if Path(f).suffix in {".rlib", ".rmeta", ".so"}]
        if not library_files:
            continue
        if profile["test"] is not False:
            raise RuntimeError("a test executable cannot substitute a library dependency")
        identities = []
        for real in library_files:
            if not real.is_relative_to(target_dir):
                raise RuntimeError("a Cargo library escaped the actual target directory")
            name = real.name
            digest = sha(real)
            if name in files:
                raise RuntimeError("duplicate library filename in the actual artifact graph")
            with real.open("rb") as handle:
                magic = handle.read(8)
            if real.suffix == ".rlib" and magic != b"!<arch>\n":
                raise RuntimeError("a required Rust library is not an actual archive")
            if real.suffix == ".so" and magic[:4] != b"\x7fELF":
                raise RuntimeError("a proc-macro library is not an actual ELF")
            link = stage / name
            size = stage_library(real, link, digest)
            files[name] = {"source": str(real), "path": str(link), "bytes": size,
                           "sha256": digest, "package_id": package["id"]}
            identities.append(name)
        primary = next((f for f in library_files if f.suffix in {".rlib", ".so"}), None)
        if primary is None:
            raise RuntimeError("a standalone metadata file cannot replace a real library")
        suffix = primary.stem.rsplit("-", 1)[-1]
        if re.fullmatch("[0-9a-f]{16}", suffix) is None:
            raise RuntimeError("unexpected Cargo library identity")
        fingerprint = primary.parent.parent / ".fingerprint" / (package["name"] + "-" + suffix) / ("lib-" + target["name"] + ".json")
        recorded = json.loads(fingerprint.read_text())
        if json.loads(recorded["features"]) != features:
            raise RuntimeError("real Cargo fingerprint features disagree with compiler-artifact")
        unit = {"package_id": package["id"], "target": target, "features": features,
                "profile": profile, "files": identities, "fingerprint_sha256": sha(fingerprint)}
        units.append(unit)
        name = target["name"]
        if name in direct and package["id"] == wanted[name]:
            rlibs = [f for f in library_files if f.suffix == ".rlib"]
            expected = {"opt_level": "0", "debuginfo": 0, "debug_assertions": True,
                        "overflow_checks": True, "test": False}
            if len(rlibs) != 1 or any(profile.get(k) != v for k, v in expected.items()):
                raise RuntimeError(f"wrong actual direct-library profile: {name}")
            direct[name].append({"path": str(stage / rlibs[0].name), "unit": unit})
    if {p.name for p in stage.iterdir()} != set(files):
        raise RuntimeError("missing or extra files in the isolated complete dependency directory")
    chosen = {}
    for name, choices in direct.items():
        if len(choices) != 1:
            raise RuntimeError(f"missing or ambiguous actual direct artifact: {name}")
        chosen[name] = choices[0]
    if chosen["codex_apply_patch"]["unit"]["features"] != (["hia-native"] if native else []):
        raise RuntimeError("actual production owner feature dispatch is wrong")
    search = stage_native_search(native_paths, target_dir,
                                 stage.with_name(stage.name + "-native-search"))
    return {"direct": chosen, "files": files, "units": units, **search,
            "artifact_jsonl_sha256": sha(path), "stage": str(stage),
            "actual_cargo_build_succeeded": True}


def verify_graph(graph):
    if {p.name for p in Path(graph["stage"]).iterdir()} != set(graph["files"]):
        raise RuntimeError("the isolated complete dependency set changed")
    for record in graph["files"].values():
        verify_library_copy(Path(record["source"]), Path(record["path"]),
                            record["sha256"], record["bytes"])
    if graph.get("actual_cargo_build_succeeded") is True:
        verify_native_search(graph)


def flags(rustc, graph, *, original):
    args = [rustc, "--edition=2024", "-C", "opt-level=0", "-C", "debuginfo=0",
            "-C", "debug-assertions=yes", "-C", "overflow-checks=yes",
            "-L", "dependency=" + graph["stage"]]
    args += [item for path in graph["native_paths"] for item in ("-L", path)]
    for name, record in sorted(graph["direct"].items()):
        if original and name == "codex_apply_patch":
            continue
        args += ["--extern", name + "=" + record["path"]]
    return args


def build_drivers(rustc, original_root, producer, driver, default, native, env, commands, output):
    for name in REQUIRED:
        left, right = default["direct"][name]["unit"], native["direct"][name]["unit"]
        for field in ("package_id", "features", "profile", "target"):
            if left[field] != right[field]:
                raise RuntimeError(f"default/native dependency graph differs unexpectedly: {name}/{field}")
    child = env.copy()
    child.pop("CODEX_HIA_NATIVE_LIB_DIR", None)
    child["CARGO_MANIFEST_DIR"] = str(original_root / CRATE)
    source = original_root / CRATE / "src/lib.rs"
    common = flags(rustc, default, original=True)
    reference = output / "libcodex_apply_patch_original.rlib"
    commands.run("compile-whole-original-lib", common + ["--crate-name", "codex_apply_patch_original",
        "--crate-type", "rlib", source, "-o", reference], cwd=producer, env=child)
    tests = output / "original-crate-tests"
    commands.run("compile-whole-original-tests", common + ["--crate-name", "codex_apply_patch_original_tests",
        "--test", source, "-o", tests], cwd=producer, env=child)
    listing = commands.run("list-whole-original-tests", [tests, "--list"], cwd=producer, env=child).read_text()
    names = {line.removesuffix(": test") for line in listing.splitlines()
             if line.startswith("file_update::tests::") and line.endswith(": test")}
    if names != ORIGINAL_TESTS:
        raise RuntimeError("the exact original five-test inventory changed")
    passed = commands.run("run-five-original-owner-tests",
        [tests, "file_update::tests::", "--nocapture", "--test-threads=1"], cwd=producer, env=child).read_text()
    if re.search(r"test result: ok\. 5 passed; 0 failed; 0 ignored;", passed) is None:
        raise RuntimeError("the original five tests did not execute and pass")
    for name in ORIGINAL_TESTS:
        if f"test {name} ... ok" not in passed:
            raise RuntimeError(f"the original test lacks its real pass result: {name}")
    binaries = {"original": output / "file-update-original-oracle",
                "native": output / "file-update-native-oracle"}
    commands.run("compile-original-public-driver", common + ["--crate-name", "file_update_original_oracle",
        "--extern", "codex_apply_patch=" + str(reference), driver, "-o", binaries["original"]],
        cwd=producer, env=child)
    commands.run("compile-native-public-driver", flags(rustc, native, original=False) +
        ["--crate-name", "file_update_native_oracle", driver, "-o", binaries["native"]],
        cwd=producer, env=env)
    for name, binary in binaries.items():
        symbols = commands.run(name + "-defined-symbols", ["nm", "--defined-only", binary],
                               cwd=producer, env=env).read_text()
        for module in ("file_update", "seek_sequence", "source_file"):
            found = re.search(r"\b[Tt] codex_hia_" + module + r"$", symbols, re.MULTILINE) is not None
            if found != (name == "native"):
                raise RuntimeError(f"{name} executable has wrong real HIA linkage for {module}")
    return binaries
