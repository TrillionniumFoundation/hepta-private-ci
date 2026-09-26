#!/usr/bin/env python3
"""Execute and verify commit-addressed artifact qualification; never grant activation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

SCHEMA = "hepta.learning-artifacts.qualification.v1"
REQUIRED = ("closed-world", "build", "clippy", "tests")
DENIED = ("productionImplementation", "activation", "independentAcceptance", "release")
SHA = re.compile(r"[0-9a-f]{40}\Z")
COMMANDS = {
    "closed-world": ["python3", "scripts/hepta-lane-e-closure.py", "verify"],
    "build": ["cargo", "check", "--locked", "-p", "codex-hepta-learning-artifacts", "--all-targets"],
    "clippy": ["cargo", "clippy", "--locked", "-p", "codex-hepta-learning-artifacts", "--all-targets", "--", "-D", "warnings"],
    "tests": ["cargo", "test", "--locked", "-p", "codex-hepta-learning-artifacts", "--lib", "--", "--test-threads=1"],
}
CASE = re.compile(r"^test (\S+) \.\.\. (ok|FAILED|ignored)$", re.MULTILINE)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(root: Path, source: str, base: str, lane: str) -> dict:
    require(lane in ("source", "merge"), "unknown lane")
    require(bool(SHA.fullmatch(source)) and bool(SHA.fullmatch(base)), "full source/base SHA required")
    candidate = git(root, "rev-parse", "HEAD")
    parents = git(root, "show", "-s", "--format=%P", "HEAD").split()
    require(candidate == source if lane == "source" else parents == [base, source], "candidate/ordered-parent mismatch")
    require(not git(root, "status", "--porcelain", "--untracked-files=no"), "dirty tracked source")
    require(not git(root, "ls-files", "--others", "--exclude-standard", "--", "codex-rs/hepta-learning-artifacts"), "untracked crate source")
    blobs = {}
    for line in git(root, "ls-tree", "-r", "HEAD", "--", "codex-rs/hepta-learning-artifacts", "codex-rs/hepta-agentd/src/cognitive_ranker.rs", "qualification/lane-e/TEST_TRACEABILITY.json", "scripts/hepta_artifacts_evidence.py", ".github/workflows/hepta-learning-artifacts-qualification.yml").splitlines():
        meta, path = line.split("\t", 1)
        mode, kind, sha = meta.split()
        require(kind == "blob" and mode in ("100644", "100755"), "unexpected source object")
        require(git(root, "hash-object", "--", path) == sha, "source blob mismatch: " + path)
        blobs[path] = sha
    require(bool(blobs), "empty source inventory")
    return {"sourceCommit": source, "baseCommit": base, "candidateCommit": candidate,
            "candidateTree": git(root, "rev-parse", "HEAD^{tree}"), "parents": parents,
            "lane": lane, "sourceBlobs": blobs}


def assess_test_output(log: str) -> dict:
    cases = CASE.findall(log)
    names = [name for name, _ in cases]
    require(bool(cases), "zero executed tests")
    require(len(names) == len(set(names)), "duplicate executed test identity")
    require(all(outcome == "ok" for _, outcome in cases), "failed or ignored test")
    summaries = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)
    require(len(summaries) == 1, "missing or ambiguous terminal test summary")
    passed, failed, ignored, measured, filtered = map(int, summaries[0])
    require(passed == len(cases) and failed == ignored == measured == filtered == 0, "test inventory/summary mismatch")
    return {"passed": passed, "ignored": 0, "filtered": 0, "testNames": sorted(names)}


def traceability(root: Path, tests: dict, blobs: dict, tree: str | None = None) -> list:
    trace_path = "qualification/lane-e/TEST_TRACEABILITY.json"
    trace = json.loads(git(root, "show", tree + ":" + trace_path) if tree else (root / trace_path).read_text())
    cases = [item for item in trace["cases"] if item["module"] == "learning.artifacts"]
    require({item["id"] for item in cases} == {f"ART-{i:02d}" for i in range(1, 13)} and len(cases) == 12, "artifact requirements are not closed-world")
    result = []
    for item in cases:
        require(bool(item["tests"]), "requirement has no tests")
        for test in item["tests"]:
            path, function = test["source"], test["function"]
            # Cross-crate mappings remain covered by the Lane E workflow, not relabelled here.
            require(path in blobs, "mapped test outside qualified source inventory: " + path)
            matches = [name for name in tests["testNames"] if name.rsplit("::", 1)[-1] == function]
            require(len(matches) == 1, "test not executed or ambiguous: " + function)
            result.append({"requirement": item["id"], "source": path, "blob": blobs[path],
                           "symbol": function, "executedTest": matches[0], "command": "tests"})
    return result


def execute(command: list[str], cwd: Path, log: Path, timeout: int = 2400) -> dict:
    start = time.monotonic()
    timed_out = False
    log_limit_exceeded = False
    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        while process.poll() is None:
            timed_out = time.monotonic() - start > timeout
            log_limit_exceeded = log.stat().st_size > 32 * 1024 * 1024
            if timed_out or log_limit_exceeded:
                os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(0.1)
        code = process.wait()

    data = log.read_bytes()
    return {"argv": command, "exitCode": code, "timedOut": timed_out,
            "logLimitExceeded": log_limit_exceeded, "durationSeconds": round(time.monotonic() - start, 3), "log": log.name,
            "logSha256": digest(data), "logBytes": len(data)}


def run(root: Path, output: Path, source: str, base: str, lane: str) -> int:
    binding = identity(root, source, base, lane)
    output.mkdir(parents=True, exist_ok=False)
    commands = {name: (argv, root if name == "closed-world" else root / "codex-rs")
                for name, argv in COMMANDS.items()}
    results, problems = {}, []
    for name, (argv, cwd) in commands.items():
        print("Executing", name, flush=True)
        try:
            results[name] = execute(argv, cwd, output / (name + ".log"))
        except OSError as error:
            (output / (name + ".log")).write_text(str(error))
            data = (output / (name + ".log")).read_bytes()
            results[name] = {"argv": argv, "exitCode": 127, "timedOut": False, "logLimitExceeded": False, "log": name + ".log", "logSha256": digest(data), "logBytes": len(data)}
        if results[name]["exitCode"] != 0 or results[name]["timedOut"] or results[name]["logLimitExceeded"]:
            problems.append(name + " did not succeed")
    tests, trace = {}, []
    try:
        closure = json.loads((output / "closed-world.log").read_text())
        require(closure.get("ok") is True and closure.get("findings") == [], "closed-world output is not affirmative")
        tests = assess_test_output((output / "tests.log").read_text(errors="replace"))
        trace = traceability(root, tests, binding["sourceBlobs"])
        require(identity(root, source, base, lane) == binding, "source changed during qualification")
    except (ValueError, KeyError, OSError) as error:
        problems.append(str(error))
    receipt = {"schema": SCHEMA, **binding, "runId": os.environ.get("GITHUB_RUN_ID", "local"),
               "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"), "job": os.environ.get("GITHUB_JOB", "local"),
               "commands": results, "tests": tests, "traceability": trace,
               "qualified": not problems, "problems": problems,
               "claimBoundary": {key: False for key in DENIED}}
    (output / "qualification.json").write_bytes(canonical(receipt))
    print(json.dumps({"qualified": not problems, "problems": problems}, indent=2))
    return int(bool(problems))


def verify_receipt(path: Path, source: str, base: str, run_id: str, attempt: str) -> dict:
    value = json.loads(path.read_text())
    require(value["schema"] == SCHEMA and value["qualified"] is True and value["problems"] == [], "unqualified receipt")
    require((value["sourceCommit"], value["baseCommit"], value["runId"], value["runAttempt"]) == (source, base, run_id, attempt), "receipt source/run binding mismatch")
    require(value["claimBoundary"] == {key: False for key in DENIED} and all(flag is False for flag in value["claimBoundary"].values()), "authority escalation")
    require(value.get("job") == "qualification", "unexpected producer job")
    require(value["lane"] in ("source", "merge"), "unknown receipt lane")
    require(bool(SHA.fullmatch(value["candidateCommit"])) and bool(SHA.fullmatch(value["candidateTree"])), "invalid candidate identity")
    require(value["candidateCommit"] == source if value["lane"] == "source" else value["parents"] == [base, source], "receipt candidate/parent mismatch")
    require(set(value["commands"]) == set(REQUIRED), "missing or unknown command")
    for name, result in value["commands"].items():
        require(type(result["exitCode"]) is int and result["exitCode"] == 0 and result["timedOut"] is False and result["logLimitExceeded"] is False, "failed command")
        require(result["argv"] == COMMANDS[name], "command substitution")
        require(result["log"] == name + ".log", "unsafe log path")
        require(not (path.parent / result["log"]).is_symlink(), "symlink log")
        data = (path.parent / result["log"]).read_bytes()
        require(digest(data) == result["logSha256"] and len(data) == result["logBytes"], "log binding mismatch")
    closure = json.loads((path.parent / "closed-world.log").read_text())
    require(closure.get("ok") is True and closure.get("findings") == [], "closed-world output is not affirmative")
    require(assess_test_output((path.parent / "tests.log").read_text()) == value["tests"], "test receipt mismatch")
    require(bool(value["sourceBlobs"]) and all(SHA.fullmatch(sha) for sha in value["sourceBlobs"].values()), "invalid source inventory")
    require({row["requirement"] for row in value["traceability"]} == {f"ART-{i:02d}" for i in range(1, 13)}, "missing traceability")
    for row in value["traceability"]:
        require(value["sourceBlobs"].get(row["source"]) == row["blob"] and row["executedTest"] in value["tests"]["testNames"] and row["command"] == "tests", "unexecuted traceability")
    return value


def aggregate(directory: Path, source: str, base: str, run_id: str, attempt: str, needs: dict, root: Path | None = None) -> None:
    require(set(needs) == {"qualification"} and needs["qualification"]["result"] == "success", "failed, absent or skipped qualification job")
    paths = list(directory.rglob("qualification.json"))
    require(len(paths) == 2, "exactly two lane receipts required")
    receipts = [verify_receipt(path, source, base, run_id, attempt) for path in paths]
    require({item["lane"] for item in receipts} == {"source", "merge"}, "missing or duplicated lane")
    if root is not None:
        trees = {"source": git(root, "rev-parse", source + "^{tree}"),
                 "merge": git(root, "merge-tree", "--write-tree", base, source)}
        for receipt in receipts:
            require(receipt["candidateTree"] == trees[receipt["lane"]], "candidate tree mismatch")
            for path, blob in receipt["sourceBlobs"].items():
                require(git(root, "rev-parse", trees[receipt["lane"]] + ":" + path) == blob, "receipt source blob differs from Git tree")
            expected_trace = traceability(root, receipt["tests"], receipt["sourceBlobs"], trees[receipt["lane"]])
            require(expected_trace == receipt["traceability"], "requirement/test mapping drift")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "aggregate"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--lane", choices=("source", "merge"))
    args = parser.parse_args()
    try:
        if args.command == "run":
            return run(args.root, args.output, args.source, args.base, args.lane)
        aggregate(args.output, args.source, args.base, os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"], json.loads(os.environ["QUALIFICATION_NEEDS"]), args.root)
        return 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print("qualification rejected:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
