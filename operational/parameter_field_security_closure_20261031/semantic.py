"""Execute byte-bound vendor regressions with real Rust and independent oracles."""

import argparse
import bz2
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import time
import tomllib
import xml.etree.ElementTree as ET

from . import prepare
from . import resolve


GROUPS = {
    "matrix": {"members": ["matrix-sdk-crypto"], "features": []},
    "aws": {"members": ["aws-config"],
            "features": ["aws-config/credentials-login", "aws-config/test-util"]},
    "compat": {"members": ["anymap2", "i18n-config", "secret-service"],
               "features": ["secret-service/rt-async-io-crypto-rust"]},
    "zip": {"members": ["zip", "oxiarc-bzip2"],
            "features": ["oxiarc-bzip2/bzip2-oracle"]},
}


def test_feature_args(group, package):
    selected = [feature for feature in GROUPS[group]["features"]
                if feature.split("/", 1)[0] == package]
    return ["--features", ",".join(selected)] if selected else []


def restore_candidate(root, resolved, plan):
    """Read exactly the same-run resolver artifact; never trust archive paths."""
    receipt = json.loads((resolved / "RESOLUTION.json").read_text())
    head = prepare.git(root, "rev-parse", "HEAD").decode().strip()
    if (receipt.get("status") != "complete" or receipt.get("source_head") != head
            or receipt.get("run_id") != os.environ.get("GITHUB_RUN_ID")
            or receipt.get("run_attempt") != os.environ.get("GITHUB_RUN_ATTEMPT")):
        raise ValueError("resolver artifact is not a complete same-source, same-attempt result")
    if prepare.git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("semantic source checkout is not clean")
    for path, expected in plan["base_files"].items():
        prepare.check((root / path).read_bytes(), expected, path)
    raw = (resolved / "CANDIDATE_SOURCE.tar.gz").read_bytes()
    prepare.check(raw, receipt["candidate_source_archive"], "resolved candidate archive")
    expected = {**plan["candidate_files"], "codex-rs/Cargo.lock": receipt["cargo_lock"]}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            path = str(prepare.relative_path(member.name))
            if path not in expected or path in seen or not member.isfile():
                raise ValueError("unexpected resolved candidate archive member")
            with archive.extractfile(member) as stream:
                content = stream.read(expected[path]["bytes"] + 1)
            prepare.check(content, expected[path], path)
            destination = root / path
            if destination.is_symlink():
                raise ValueError("candidate destination is a symlink")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            seen.add(path)
    if seen != set(expected):
        raise ValueError("incomplete resolved candidate archive")
    resolve.graph_contract(tomllib.loads((root / "codex-rs/Cargo.lock").read_text()))
    for path in plan["policy_files_unchanged"] + [
        "codex-rs/keyring-store/Cargo.toml", "codex-rs/keyring-store/src/lib.rs",
    ]:
        prepare.check((root / path).read_bytes(), plan["base_files"][path], path)
    return receipt


def check_tests(path, required=(), minimum=1, negative=False):
    document = ET.parse(path).getroot()
    tests = list(document.iter("testcase"))
    if len(tests) < minimum or any(test.find("skipped") is not None for test in tests):
        raise ValueError("required Rust tests did not execute")
    names = [test.get("name", "") for test in tests]
    for suffix in required:
        if not any(name.endswith(suffix) for name in names):
            raise ValueError("required Rust regression was absent: " + suffix)
    failures = [test for test in tests
                if test.find("failure") is not None or test.find("error") is not None]
    if negative:
        if len(tests) != 1 or len(failures) != 1:
            raise ValueError("original Matrix implementation did not fail the new regression")
        if "Should have verification violation if device_owner_identity is None" not in ET.tostring(failures[0], encoding="unicode"):
            raise ValueError("Matrix negative control failed for a different reason")
    elif failures:
        raise ValueError("a required Rust test failed")
    return {"executed": len(tests), "failed": len(failures), "names": names,
            "junit": prepare.identity(path.read_bytes()), "negative_control": negative}


def materialize_test_inputs(output, group):
    raw_plan = (prepare.HERE / "TEST_INPUTS.json").read_bytes()
    plan = json.loads(raw_plan)
    if plan.get("schema") != "hepta.dependency-security-dev-fixtures.1":
        raise ValueError("unrecognized dev fixture source plan")
    archives = output / "dev-fixture-downloads"
    archives.mkdir()
    actual = {}
    for entry in plan["files"]:
        if entry["group"] != group:
            continue
        relative = str(prepare.relative_path(entry["destination"]))
        if not ((group == "zip" and relative.startswith("workspace/zip/tests/data/"))
                or (group == "matrix" and relative in {
                    "benchmarks/benches/crypto_bench/keys_claim.json",
                    "benchmarks/benches/crypto_bench/keys_query.json",
                })):
            raise ValueError("dev fixture destination is outside its declared test scope")
        destination = output / relative
        if destination.exists() or destination.is_symlink() or relative in actual:
            raise ValueError("dev fixture would replace candidate source or another fixture")
        raw = prepare.download(entry, archives)
        git_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if git_blob != entry["git_blob"]:
            raise ValueError("dev fixture Git blob identity changed")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        actual[relative] = {**prepare.identity(raw), "git_blob": git_blob,
                            "repository": entry["repository"], "commit": entry["commit"]}
    return actual, prepare.identity(raw_plan)


def make_workspace(root, work, plan, group):
    sources = {}
    for package_root in sorted({"/".join(Path(path).parts[:3])
                                for path in plan["candidate_files"]
                                if path.startswith("codex-rs/third_party/")}):
        manifest = tomllib.loads((root / package_root / "Cargo.toml").read_text())
        sources[manifest["package"]["name"]] = root / package_root
    selected = GROUPS[group]["members"]
    copied = {}
    for name in selected:
        destination = work / name
        shutil.copytree(sources[name], destination)
        copied[name] = destination
    text = "[workspace]\nresolver = \"3\"\nmembers = " + json.dumps(selected) + "\n"
    # Preserve previously repaired imbl/SQLite and inherited Git patches too;
    # an isolated test must not accidentally revert the product's older fixes.
    patches = tomllib.loads((root / "codex-rs/Cargo.toml").read_text())["patch"]
    for registry, entries in patches.items():
        text += "\n[patch." + json.dumps(registry) + "]\n"
        for name, declaration in entries.items():
            declaration = dict(declaration)
            if "path" in declaration:
                declaration["path"] = str(copied.get(name, (root / "codex-rs" / declaration["path"]).resolve()))
            text += json.dumps(name) + " = { " + ", ".join(
                json.dumps(key) + " = " + json.dumps(value) for key, value in declaration.items()) + " }\n"
    (work / "Cargo.toml").write_text(text)
    (work / "Cargo.lock").write_bytes((root / "codex-rs/Cargo.lock").read_bytes())
    (work / "justfile").write_text(
        'set positional-arguments\n\ntest *args:\n    RUST_MIN_STACK=8388608 cargo nextest run --no-fail-fast "$@"\n')
    (work / ".config").mkdir()
    (work / ".config/nextest.toml").write_text(
        "[profile.ci]\nretries = 0\ntest-threads = 2\n"
        "[profile.ci.junit]\npath = \"junit.xml\"\n"
        "store-success-output = true\nstore-failure-output = true\n")
    return sources, copied


def run(root, resolved, output, group):
    root, resolved, output = root.resolve(), resolved.resolve(), output.resolve()
    if output.exists() or output == root or root in output.parents:
        raise ValueError("semantic work directory must be new and outside source")
    evidence = output / "evidence"
    evidence.mkdir(parents=True)
    work = output / "workspace"
    work.mkdir()
    plan = json.loads((prepare.HERE / "INPUTS.json").read_text())
    capture = resolve.load_module(root, "scripts/capture_cargo_deny_diagnostic.py",
                                  "semantic_capture", plan["capture_git_blob"])
    started = time.monotonic()
    receipt = {
        "schema": "hepta.dependency-security-semantics.1", "status": "in_progress",
        "group": group, "source_head": prepare.git(root, "rev-parse", "HEAD").decode().strip(),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "qualification": False, "commands": [], "rust_tests": {},
        "scope": "Isolated dev-dependency tests of byte-identical candidate packages; not a replacement for native product or Bazel qualification.",
        "path_advisory_coverage": "Path backports require source identity and real regressions; absence from cargo-deny registry matching is not security evidence.",
    }

    def save():
        receipt["wall_seconds"] = time.monotonic() - started
        (evidence / "SEMANTICS.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    def invoke(label, command, timeout=2400, check=True):
        save()
        result = capture.capture(command, work, evidence, label, timeout=timeout, limit=32 * 1024 * 1024)
        result["label"] = label
        receipt["commands"].append(result)
        save()
        if result["timed_out"] or (check and result["exit_code"]):
            raise ValueError("actual semantic command failed: " + label)
        return result

    junit = work / "target/nextest/ci/junit.xml"

    def tests(label, arguments, required=(), minimum=1, negative=False):
        if junit.exists():
            raise ValueError("unexpected stale JUnit receipt")
        package = arguments[arguments.index("-p") + 1]
        result = invoke(label, ["just", "test", "--profile", "ci", "--locked", *arguments,
                                *test_feature_args(group, package)], check=not negative)
        retained = evidence / (label + ".junit.xml")
        if not junit.is_file():
            raise ValueError("nextest did not produce actual JUnit evidence")
        shutil.copyfile(junit, retained)
        parsed = check_tests(retained, required, minimum, negative)
        if negative and result["exit_code"] != 100:
            raise ValueError("negative control was not a nextest test failure")
        receipt["rust_tests"][label] = parsed
        junit.unlink()
        save()

    save()
    try:
        resolver = restore_candidate(root, resolved, plan)
        receipt["product_cargo_lock"] = resolver["cargo_lock"]
        receipt["resolver_receipt"] = prepare.identity((resolved / "RESOLUTION.json").read_bytes())
        sources, copied = make_workspace(root, work, plan, group)
        dev_inputs, dev_plan_identity = materialize_test_inputs(output, group)
        receipt["dev_inputs"] = dev_inputs
        receipt["dev_input_plan"] = dev_plan_identity
        for tool in ("rustc", "cargo", "just"):
            invoke(tool + "_version", [tool, "--version"], 60)
        invoke("nextest_version", ["cargo", "nextest", "--version"], 60)
        for tool in ("cargo", "rustc"):
            if not (evidence / (tool + "_version.stdout.log")).read_text().startswith(tool + " 1.95.0 "):
                raise ValueError("semantic Rust toolchain differs from product resolver")
        invoke("rustc_verbose", ["rustc", "-vV"], 60)
        hosts = [line.removeprefix("host: ") for line in (evidence / "rustc_verbose.stdout.log").read_text().splitlines()
                 if line.startswith("host: ")]
        if len(hosts) != 1 or not hosts[0].endswith("-unknown-linux-gnu"):
            raise ValueError("actual Rust host identity was not established")
        # nextest 0.9.103 resolves all workspace features with this actual host
        # filter before compiling the requested test package. Prepare that exact
        # dev graph, retaining every resolver step; product Cargo.lock is separate.
        metadata_args = ["cargo", "metadata", "--all-features", "--filter-platform", hosts[0], "--format-version", "1"]
        receipt["nextest_metadata_contract"] = metadata_args
        invoke("isolated_metadata_resolve", metadata_args, 1200)
        isolated = tomllib.loads((work / "Cargo.lock").read_text())
        for name, version in plan["lock_pins"].items():
            selected = [item for item in isolated["package"] if item["name"] == name
                        and (name != "toml" or item["version"].startswith("1."))]
            if len(selected) > 1:
                raise ValueError("ambiguous isolated security dependency: " + name)
            if selected and selected[0]["version"] != version:
                invoke("isolated_pin_" + name, ["cargo", "update", "-p", name + "@" + selected[0]["version"],
                                                "--precise", version], 1200)
        for attempt in range(1, 4):
            before = (work / "Cargo.lock").read_bytes()
            invoke("isolated_metadata_stabilize_" + str(attempt), metadata_args, 1200)
            if (work / "Cargo.lock").read_bytes() == before:
                break
        else:
            raise ValueError("actual isolated dev resolver failed to reach a stable lock")
        invoke("isolated_metadata_locked", [*metadata_args, "--locked"], 1200)
        lock_raw = (work / "Cargo.lock").read_bytes()
        locked_packages = tomllib.loads(lock_raw.decode())["package"]
        for name, version in plan["lock_pins"].items():
            selected = [item for item in locked_packages if item["name"] == name
                        and (name != "toml" or item["version"].startswith("1."))]
            if selected and (len(selected) != 1 or selected[0]["version"] != version):
                raise ValueError("isolated real resolver changed a declared security pin: " + name)
        (evidence / "Cargo.lock").write_bytes(lock_raw)
        receipt["isolated_cargo_lock"] = prepare.identity(lock_raw)
        old = resolve.package_map(tomllib.loads((root / "codex-rs/Cargo.lock").read_text()))
        new = resolve.package_map(tomllib.loads(lock_raw.decode()))
        delta = {"added": [new[k] for k in sorted(new.keys() - old.keys())],
                 "removed": [old[k] for k in sorted(old.keys() - new.keys())],
                 "changed": [{"before": old[k], "after": new[k]} for k in sorted(old.keys() & new.keys()) if old[k] != new[k]],
                 "scope": "Actual isolated dev-dependency graph, not the product lock."}
        (evidence / "ISOLATED_LOCK_DELTA.json").write_text(json.dumps(delta, indent=2) + "\n")
        if group == "matrix":
            entry = next(item for item in plan["archives"] if item["name"] == "matrix-sdk-crypto")
            upstream_raw = (resolved / "upstream" / entry["sha256"]).read_bytes()
            prepare.check(upstream_raw, entry, "Matrix original registry source")
            relative = "src/session_manager/group_sessions/share_strategy.rs"
            with tarfile.open(fileobj=io.BytesIO(upstream_raw), mode="r:gz") as archive:
                with archive.extractfile(entry["source_prefix"] + "/" + relative) as stream:
                    original = stream.read()
            source_file = copied["matrix-sdk-crypto"] / relative
            fixed = source_file.read_bytes()
            original_test = ["-p", "matrix-sdk-crypto", "--lib", "-E", "test(test_share_strategy_prevents_encryption)"]
            source_file.write_bytes(original)
            try:
                tests("matrix_original_panic_negative_control", original_test,
                      ["test_share_strategy_prevents_encryption"], negative=True)
            finally:
                source_file.write_bytes(fixed)
            receipt["matrix_control_source"] = {"original": prepare.identity(original), "fixed": prepare.identity(fixed)}
            tests("matrix_official_security_regression", original_test, ["test_share_strategy_prevents_encryption"])
        elif group == "aws":
            tests("aws_dpop", ["-p", "aws-config", "--lib", "-E", "test(login::dpop::tests::)"],
                  ["test_header_extracts_public_coordinates", "test_build_message", "test_calculate_valid_key",
                   "test_calculate_invalid_key", "test_dpop_signature_verifies_and_rejects_modified_payload"], minimum=5)
        elif group == "compat":
            tests("anymap_type_boundaries", ["-p", "anymap2", "--lib"], minimum=2)
            tests("i18n_parser_compatibility", ["-p", "i18n-config", "--lib"], [
                "reads_age_fluent_profile", "reads_cargo_manifest_and_its_localization_profile",
                "preserves_gettext_defaults_and_overridden_paths", "preserves_parent_config_selection",
                "rejects_invalid_profiles_with_the_original_file_path", "rejects_invalid_cargo_manifests_with_the_manifest_path",
            ], minimum=6)
            tests("secret_service_prompt_boundaries", ["-p", "secret-service", "--lib", "-E", "test(prompt_tests::)"], minimum=4)
        elif group == "zip":
            bzip2 = shutil.which("bzip2")
            if not bzip2:
                raise ValueError("actual independent libbz2 executable is required; self-skip is forbidden")
            receipt["independent_bzip2_binary"] = {"path": bzip2, **prepare.identity(Path(bzip2).read_bytes())}
            invoke("bzip2_version", [bzip2, "--version"], 60)
            golden = copied["zip"] / "tests/data/randomised_rep_l1.bz2"
            if bz2.decompress(golden.read_bytes()) != b"repetitive repetitive repetitive!\n" * 64:
                raise ValueError("Python libbz2 rejected the legacy randomised fixture")
            receipt["python_libbz2_legacy_fixture_verified"] = True
            tests("zip_lib_regressions", ["-p", "zip", "--lib"], [
                "retains_levels_flush_continuation_and_next_container_bytes", "preserves_legacy_randomised_blocks",
                "rejects_bad_crc_and_truncation", "header_error_returns_source_and_zero_read_does_not_advance",
            ], minimum=4)
            tests("oxiarc_lib_regressions", ["-p", "oxiarc-bzip2", "--lib"])
            tests("oxiarc_fixed_interoperability", ["-p", "oxiarc-bzip2", "--test", "interop_bzip2"], minimum=10)
            tests("oxiarc_actual_libbz2_oracle", ["-p", "oxiarc-bzip2", "--test", "bzip2_oracle"], [
                "oracle_reference_compress_oxiarc_decode", "oracle_oxiarc_compress_reference_decode",
                "oracle_multistream_reference_streams_oxiarc_decodes_all", "oracle_multistream_oxiarc_streams_reference_decodes_all",
                "oracle_randomised_fixture_cross_check", "oracle_ratio_report_structured_data",
            ], minimum=6)
            logs = b"".join(path.read_bytes() for path in evidence.glob("oxiarc_actual_libbz2_oracle.*.log"))
            if b"self-skip" in logs or b"not on PATH; skipping" in logs:
                raise ValueError("independent libbz2 oracle self-skipped")
        for name, destination in copied.items():
            source = sources[name]
            expected_paths = {path.relative_to(source).as_posix(): prepare.identity(path.read_bytes())
                              for path in source.rglob("*") if path.is_file()}
            for relative, expected in dev_inputs.items():
                fixture = output / relative
                if fixture.is_relative_to(destination):
                    expected_paths[fixture.relative_to(destination).as_posix()] = {
                        key: expected[key] for key in ("bytes", "sha256")}
            actual_paths = {path.relative_to(destination).as_posix(): prepare.identity(path.read_bytes())
                            for path in destination.rglob("*") if path.is_file()}
            if actual_paths != expected_paths:
                raise ValueError("isolated candidate package source changed during testing: " + name)
        for relative, expected in dev_inputs.items():
            prepare.check((output / relative).read_bytes(), expected, relative)
        for path, expected in plan["candidate_files"].items():
            prepare.check((root / path).read_bytes(), expected, path)
        if (work / "Cargo.lock").read_bytes() != lock_raw:
            raise ValueError("locked regression tests changed the isolated lock")
        receipt["status"] = "complete"
        receipt["candidate_sources_preserved"] = True
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error)
        raise
    finally:
        save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group", choices=GROUPS, required=True)
    args = parser.parse_args()
    receipt = run(args.repo, args.resolved, args.output, args.group)
    print(json.dumps({"status": receipt["status"], "group": args.group,
                      "qualification": False, "rust_tests": len(receipt["rust_tests"])}))


if __name__ == "__main__":
    main()
