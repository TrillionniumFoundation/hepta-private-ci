#!/usr/bin/env python3
"""Require both current native shards and every original Windows terminal result."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

from windows_current_ci import (
    ANSI,
    SANDBOX_HELPERS,
    SHARD_PACKAGES,
    assess,
    git,
    original_command,
    scope_digest,
    selected_groups,
    valid_source,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON receipt key")
        result[key] = value
    return result


def read_bytes(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"missing or redirected evidence: {path.name}")
    return path.read_bytes()


def read_json(path: Path):
    return json.loads(read_bytes(path), object_pairs_hook=unique_object)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_name(head: str, run_id: str, attempt: str, shard: str) -> str:
    return f"windows-current-ci-{head}-{run_id}-{attempt}-{shard}"


def single_nextest_run(group: dict, raw: str) -> dict:
    # Keep the original outcome assessor unchanged. A second complete run must
    # not disappear when that assessor deduplicates its terminal test names.
    text = ANSI.sub("", raw).replace("\r\n", "\n")
    headers = list(re.finditer(r"^[ \t]*Nextest run ID[^\n]*$", text, re.MULTILINE))
    starts = list(re.finditer(r"^[ \t]*Starting [^\n]*$", text, re.MULTILINE))
    summaries = list(re.finditer(r"^[ \t]*Summary \[[^\n]*$", text, re.MULTILINE))
    require(len(headers) == len(starts) == len(summaries) == 1, "original group must contain exactly one Nextest run ID, Starting and Summary")
    header = re.fullmatch(r"\s*Nextest run ID ([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}) with nextest profile: local", headers[0].group())
    start = re.fullmatch(r"\s*Starting (\d+) tests? across 1 binary(?: \((\d+) tests? skipped\))?", starts[0].group())
    summary = re.fullmatch(r"\s*Summary \[[^\]\n]+\] (\d+) tests? run: (\d+) passed(?:, (\d+) skipped)?", summaries[0].group())
    require(header is not None and start is not None and summary is not None, "original single-run profile or terminal summary is invalid")
    require(headers[0].start() < starts[0].start() < summaries[0].start(), "original Nextest run envelope is out of order")
    selected = group["expectedTestCount"]
    skipped = int(start[2] or 0)
    require(int(start[1]) == int(summary[1]) == int(summary[2]) == selected and int(summary[3] or 0) == skipped, "original single-run selected, passed or skipped totals disagree")
    return {"runId": header[1], "profile": "local", "selected": selected, "skipped": skipped}


def native_path(value, label: str) -> PureWindowsPath:
    require(isinstance(value, str) and bool(value), f"missing native {label} path")
    path = PureWindowsPath(value)
    require(path.is_absolute() and ".." not in path.parts, f"invalid native {label} path")
    return path


def validate_helper_bytes(directory: Path, helpers: dict, native_paths: dict) -> None:
    require(isinstance(native_paths, dict) and set(native_paths) == {"checkout", "target"}, "missing native checkout/target paths")
    root = native_path(native_paths["checkout"], "checkout")
    target = native_path(native_paths["target"], "target")
    require(not target.is_relative_to(root), "native helper target must remain outside the source checkout")
    manifest = root / "codex-rs/windows-sandbox-rs/Cargo.toml"
    profile = target / "dev-small"
    sources = {
        "codex-windows-sandbox-setup": "src/bin/setup_main/main.rs",
        "codex-command-runner": "src/bin/command_runner/main.rs",
    }
    build = read_bytes(directory / "sandbox-helper-build.log")
    require(sha256(build) == helpers.get("logSha256"), "helper build log changed")
    records = {name: [] for name in SANDBOX_HELPERS}
    completed = []
    for line in build.decode("utf-8").splitlines():
        try:
            record = json.loads(line, object_pairs_hook=unique_object)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("reason") == "build-finished":
            completed.append(record.get("success"))
        item = record.get("target", {})
        if record.get("reason") == "compiler-artifact" and item.get("name") in records:
            records[item["name"]].append(record)
    require(len(completed) == 1 and completed[0] is True, "helper Cargo build has no unique successful terminal")
    artifacts = helpers["artifacts"]
    require(isinstance(artifacts, list) and [item["name"] for item in artifacts] == list(SANDBOX_HELPERS), "missing original native helper")
    binaries = directory / "sandbox-helper-binaries"
    require(binaries.is_dir() and not binaries.is_symlink(), "missing or redirected compiled helper evidence directory")
    require({path.name for path in binaries.iterdir()} == {name + ".exe" for name in SANDBOX_HELPERS}, "missing or extra compiled helper evidence")
    for item in artifacts:
        name = item["name"]
        binary = profile / (name + ".exe")
        sibling = profile / "deps" / binary.name
        require(len(records[name]) == 1, "helper must have exactly one original Cargo compiler artifact")
        record = records[name][0]
        require(record["target"].get("kind") == ["bin"] and record["target"].get("crate_types") == ["bin"], "helper is not the original native binary target")
        require(native_path(record.get("manifest_path"), "Cargo manifest") == manifest and native_path(record["target"].get("src_path"), "Cargo source") == manifest.parent / sources[name], "helper Cargo source belongs to another checkout or target")
        require(native_path(record.get("executable"), "Cargo executable") == binary and record.get("profile", {}).get("test") is False, "helper Cargo artifact escaped the original native profile")
        require(isinstance(record.get("filenames"), list) and binary in [native_path(path, "Cargo output") for path in record["filenames"]], "helper is absent from original Cargo output files")
        require(native_path(item.get("source"), "helper source") == binary and native_path(item.get("testSibling"), "helper test sibling") == sibling, "helper metadata is not bound to the original compiler artifact and test sibling")
        require(item.get("evidenceFile") == "sandbox-helper-binaries/" + binary.name, "helper evidence path changed")
        data = read_bytes(binaries / binary.name)
        require(data.startswith(b"MZ") and type(item.get("bytes")) is int and item["bytes"] == len(data) and item.get("sha256") == sha256(data), "compiled helper bytes, PE header, length or SHA256 disagree")


def validate_shards(
    manifest: dict, head: str, tree: str, lock: bytes, run_id: str, attempt: str,
    matrix_result: str, evidence: Path,
) -> dict:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", head)), "expected head is not immutable")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", tree)), "expected tree is not immutable")
    require(all(re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)), "missing current workflow identity")
    all_groups = selected_groups(manifest)
    expected_policy = {
        "testRetries": 0, "testThreads": 1, "emptySelection": "fail",
        "allSelectedFailuresFatal": True, "productionAuthorityGranted": False,
        "finalProductQualification": False,
    }
    require(json.dumps(manifest["policy"], sort_keys=True) == json.dumps(expected_policy, sort_keys=True), "original strict scope policy changed")
    require(b"\r" not in lock, "aggregate source lock must use canonical repository LF bytes")
    allowed_locks = {sha256(lock), sha256(lock.replace(b"\n", b"\r\n"))}
    expected_dirs = {artifact_name(head, run_id, attempt, shard) for shard in SHARD_PACKAGES}
    require(evidence.is_dir() and not evidence.is_symlink(), "current shard evidence is missing")
    require({path.name for path in evidence.iterdir()} == expected_dirs, "missing, duplicate, historical or extra shard artifacts")
    results = []
    sources = []
    runners = []
    nextest_runs = []
    for shard in SHARD_PACKAGES:
        directory = evidence / artifact_name(head, run_id, attempt, shard)
        require(directory.is_dir() and not directory.is_symlink(), "redirected shard directory")
        receipt = read_json(directory / "receipt.json")
        require(receipt.get("schema") == "hepta.windows-current-ci-shard-receipt.v1", "missing complete shard receipt")
        require(receipt.get("shard") == shard, "wrong shard binding")
        require(receipt.get("status") == "PASS_DECLARED_WINDOWS_SHARD", "shard did not reach a passing terminal")
        require(receipt.get("declaredScopeDigest") == scope_digest(manifest), "scope changed or historical scope substituted")
        require(receipt.get("productionAuthorityGranted") is False and receipt.get("finalProductQualification") is False, "CI evidence must never grant product authority")
        require(type(receipt.get("testRetries")) is int and receipt["testRetries"] == 0, "test retry policy changed")
        identity = receipt["workflow"]
        require(identity.get("runId") == run_id and identity.get("runAttempt") == attempt, "historical workflow receipt")
        require(identity.get("runnerOs") == "Windows" and isinstance(identity.get("runnerName"), str) and bool(identity["runnerName"]), "missing native Windows runner identity")
        runners.append(identity["runnerName"])
        require(isinstance(receipt.get("platform"), str) and receipt["platform"].startswith("Windows-"), "non-Windows producer")
        before, after = receipt["sourceBefore"], receipt["sourceAfter"]
        require(set(before) == {"head", "tree", "trackedChanges", "cargoLockSha256"} and set(after) == set(before), "invalid source evidence shape")
        require(valid_source(head, before, after) and type(before["trackedChanges"]) is str and before["trackedChanges"] == "" and before["tree"] == tree and before["cargoLockSha256"] in allowed_locks, "wrong, changed or dirty native source")
        require(receipt.get("sourceUnchanged") is True, "native source terminal not intact")
        require(read_json(directory / "source-before.json") == before and read_json(directory / "source-after.json") == after, "source sidecars disagree with terminal receipt")
        sources.append(before)
        compiler = read_bytes(directory / "compiler.txt")
        compiler_text = compiler.decode("utf-8").replace("\r\n", "\n")
        require(sha256(compiler) == receipt.get("compilerSha256") and compiler_text.startswith("rustc 1.96.0 ") and "\nhost: x86_64-pc-windows-msvc\n" in compiler_text, "wrong native compiler evidence")
        groups = selected_groups(manifest, shard)
        rows = receipt["groups"]
        require(isinstance(rows, list) and [row.get("id") for row in rows] == [group["id"] for group in groups], "missing, duplicate, reordered or extra original group")
        require(read_json(directory / "groups.json") == rows, "group sidecar differs from terminal receipt")
        for group, row in zip(groups, rows):
            raw = read_bytes(directory / (group["id"] + ".log"))
            require(row.get("logSha256") == sha256(raw), "original group log changed")
            require(row.get("command") == original_command(group), "original command, filter, profile or retry budget changed")
            require(type(row.get("exitCode")) is int, "missing native command terminal")
            observed = assess(group, row["exitCode"], raw.decode("utf-8"))
            require(all(type(row.get(key)) is type(value) and row[key] == value for key, value in observed.items()), "claimed test outcome disagrees with original raw log")
            require(observed["passed"] is True, "an original selected test failed or did not run")
            envelope = single_nextest_run(group, raw.decode("utf-8"))
            nextest_runs.append(envelope["runId"])
            results.append({**observed, "shard": shard, "logSha256": sha256(raw), "command": row["command"], "source": before, "nextestRun": envelope})
        helpers = receipt["sandboxHelperPreparation"]
        if any(group["package"] == "codex-windows-sandbox" for group in groups):
            require(isinstance(helpers, dict) and helpers.get("passed") is True and type(helpers.get("exitCode")) is int and helpers["exitCode"] == 0, "original native sandbox helpers did not build")
            expected_helper_command = ["cargo", "build", "--locked", "-p", "codex-windows-sandbox", "--profile", "dev-small", "--message-format=json"]
            for name in SANDBOX_HELPERS:
                expected_helper_command.extend(["--bin", name])
            require(helpers.get("command") == expected_helper_command, "original native helper build command changed")
            require(read_json(directory / "sandbox-helper-preparation.json") == helpers, "helper preparation sidecar differs")
            validate_helper_bytes(directory, helpers, receipt.get("nativePaths"))
        else:
            require(helpers is None, "non-sandbox shard must not claim helper preparation")
    require(sources[0] == sources[1] and len(set(runners)) == len(SHARD_PACKAGES), "shards did not bind the same source on independent runners")
    require({row["id"] for row in results} == {group["id"] for group in all_groups} and len(results) == 19, "incomplete or duplicate aggregate group coverage")
    require(sum(row["selectedTestCount"] for row in results) == 167, "incomplete aggregate original case coverage")
    require(len(set(nextest_runs)) == len(results), "original group run IDs are duplicated")
    require(matrix_result == "success", "native matrix jobs did not all finish successfully")
    return {"groups": results, "groupCount": 19, "testCount": 167, "source": sources[0], "runners": runners}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--matrix-result", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    require(not output.is_relative_to(root), "aggregate diagnostics must stay outside source")
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "hepta.windows-current-ci-aggregate.v1", "status": "FAIL_DECLARED_WINDOWS_SCOPE",
        "head": args.expected_head, "runId": args.run_id, "runAttempt": args.run_attempt,
        "nativeMatrixResult": args.matrix_result, "productionAuthorityGranted": False,
        "finalProductQualification": False,
    }
    try:
        require(git(root, "rev-parse", "HEAD") == args.expected_head and not git(root, "status", "--porcelain", "--untracked-files=no"), "aggregate checkout is not the exact clean head")
        manifest = read_json(root / ".github/fixtures/windows-current-ci-scope.json")
        result.update(validate_shards(manifest, args.expected_head, git(root, "rev-parse", "HEAD^{tree}"), read_bytes(root / "codex-rs/Cargo.lock"), args.run_id, args.run_attempt, args.matrix_result, args.input.resolve()))
        result["status"] = "PASS_DECLARED_WINDOWS_SCOPE"
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "PASS_DECLARED_WINDOWS_SCOPE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
