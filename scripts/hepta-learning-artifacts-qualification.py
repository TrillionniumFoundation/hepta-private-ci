#!/usr/bin/env python3
"""Execute bounded artifact diagnostics without turning skipped work into evidence.

This report is an execution observation, not a trust root or deployment permit.
Validate its GitHub run/attempt/job and provenance independently before admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".hepta-evidence/learning-artifacts"
CRATE = "codex-hepta-learning-artifacts"
MAX_LOG = 64 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}\Z")
PASS = re.compile(r"^\s*PASS\s+\[[^\]]+\]\s+(\S+)\s+(\S+)\s*$", re.M)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STEPS = (
    ("build", ["cargo", "check", "--locked", "-p", CRATE, "--all-targets"]),
    ("strict-clippy", ["cargo", "clippy", "--locked", "-p", CRATE, "--all-targets", "--", "-D", "warnings"]),
    ("owner-regression", ["just", "test", "--locked", "-p", CRATE, "--status-level", "all", "--final-status-level", "fail"]),
    ("cross-crate", ["just", "test", "--locked", "-p", "codex-hepta-shadow-qualification", "lane_e_causal_candidate_chain_is_digest_bound_and_deny_all", "--status-level", "all"]),
    ("selected-reload", ["just", "test", "--locked", "-p", "codex-hepta-shadow-qualification", "existing_artifact_owner_new_process_predictions_and_revoked_rollback", "--status-level", "all"]),
    ("cognitive-read", ["just", "test", "--locked", "-p", "codex-hepta-agentd", "cognitive_ranker", "--status-level", "all"]),
    ("format", ["cargo", "fmt", "--package", CRATE, "--", "--check"]),
    ("lane-e-preflight", ["python3", "../scripts/hepta-lane-e-closure.py", "verify"]),
)
NEW_TESTS = (
    "art_13_recomputed_admission_cannot_reauthorize_withdrawn_dataset",
    "art_13_manifest_mutation_never_inherits_admission",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def require_sha(value: str) -> str:
    if not SHA.fullmatch(value) or value == "0" * 40:
        raise ValueError("a nonzero full commit SHA is required")
    return value


def materialize_candidate(source: str, base: str, lane: str) -> dict:
    source, base = require_sha(source), require_sha(base)
    if git("rev-parse", "HEAD") != source:
        raise ValueError("checkout is not the exact requested source")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("dirty tracked source is not admissible")
    source_tree = git("rev-parse", f"{source}^{{tree}}")
    git("cat-file", "-e", f"{base}^{{commit}}")
    if lane == "merge":
        merged = git("merge-tree", "--write-tree", base, source).splitlines()[0]
        require_sha(merged)
        env = dict(os.environ, GIT_AUTHOR_NAME="Artifact qualification", GIT_AUTHOR_EMAIL="qualification@invalid.example", GIT_COMMITTER_NAME="Artifact qualification", GIT_COMMITTER_EMAIL="qualification@invalid.example")
        candidate = subprocess.check_output(["git", "commit-tree", merged, "-p", base, "-p", source, "-m", "Ordered-parent artifact qualification candidate"], cwd=ROOT, env=env, text=True).strip()
        git("checkout", "--detach", candidate)
        if git("show", "-s", "--format=%P", "HEAD").split() != [base, source]:
            raise ValueError("ordered merge parent mismatch")
    elif lane != "source":
        raise ValueError("unsupported qualification lane")
    return {"source": source, "sourceTree": source_tree, "base": base, "lane": lane, "candidate": git("rev-parse", "HEAD"), "candidateTree": git("rev-parse", "HEAD^{tree}"), "parents": git("show", "-s", "--format=%P", "HEAD").split()}


def passed_tests(text: str) -> list[dict]:
    text = ANSI.sub("", text)
    return [{"binary": binary, "function": function} for binary, function in sorted(set(PASS.findall(text)))]


def execute(name: str, command: list[str]) -> dict:
    path = OUT / f"{name}.log"
    started = time.monotonic()
    total = 0
    code = 127
    env = dict(os.environ, CARGO_TERM_COLOR="never", CLICOLOR="0", NO_COLOR="1")
    with path.open("wb") as stream:
        try:
            with subprocess.Popen(command, cwd=ROOT / "codex-rs", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as child:
                assert child.stdout is not None
                while chunk := child.stdout.read(64 * 1024):
                    remaining = max(0, MAX_LOG - total)
                    stream.write(chunk[:remaining])
                    total += len(chunk)
                code = child.wait()
        except OSError as error:
            stream.write(f"command unavailable: {error}\n".encode())
        stream.flush()
        os.fsync(stream.fileno())
    data = path.read_bytes()
    tests = passed_tests(data.decode("utf-8", errors="replace"))
    test_command = command[:2] == ["just", "test"]
    ok = code == 0 and total <= MAX_LOG and (not test_command or bool(tests))
    return {"name": name, "argv": command, "exitCode": code, "status": "passed" if ok else "failed", "elapsedSeconds": round(time.monotonic() - started, 3), "log": path.name, "logSha256": digest(data), "logTruncated": total > MAX_LOG, "passedTests": tests}


def source_bindings() -> list[dict]:
    result = []
    paths = ["codex-rs/hepta-learning-artifacts", "codex-rs/hepta-agentd/src/cognitive_ranker.rs", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "qualification/lane-e/TEST_TRACEABILITY.json", ".github/workflows/hepta-learning-artifacts-qualification.yml", "scripts/hepta-learning-artifacts-qualification.py"]
    for path in paths:
        result.append({"path": path, "gitObject": git("rev-parse", f"HEAD:{path}")})
    return result


def traceability(results: list[dict]) -> list[dict]:
    trace = json.loads((ROOT / "qualification/lane-e/TEST_TRACEABILITY.json").read_text())
    observed = {result["name"]: {item["function"].split("::")[-1] for item in result["passedTests"]} for result in results if result["status"] == "passed"}
    native = observed.get("owner-regression", set())
    mapped = []
    for case in trace["cases"]:
        if case["module"] != "learning.artifacts":
            continue
        for test in case["tests"]:
            path = test["source"]
            own = path.startswith("codex-rs/hepta-learning-artifacts/")
            step = "owner-regression" if own else "selected-reload"
            mapped.append({"requirement": case["id"], "source": path, "sourceBlob": git("rev-parse", f"HEAD:{path}"), "function": test["function"], "execution": "passed" if test["function"] in observed.get(step, set()) else "unproven", "step": step})
    for name in NEW_TESTS:
        path = "codex-rs/hepta-learning-artifacts/src/admission_v3.rs"
        mapped.append({"requirement": "ART-13", "source": path, "sourceBlob": git("rev-parse", f"HEAD:{path}"), "function": name, "execution": "passed" if name in native else "unproven", "step": "owner-regression"})
    return mapped


def write_report(report: dict) -> None:
    body = dict(report)
    body["reportSha256"] = digest(canonical(report))
    temporary = OUT / "qualification.json.tmp"
    with temporary.open("wb") as stream:
        stream.write(canonical(body))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(OUT / "qualification.json")


def verify_report(report: dict, directory: Path, expected: str) -> None:
    require_sha(expected)
    body = dict(report)
    claimed = body.pop("reportSha256", None)
    if claimed != digest(canonical(body)):
        raise ValueError("report digest mismatch")
    if report["identity"]["source"] != expected:
        raise ValueError("source identity mismatch")
    identity = report["identity"]
    for key in ("sourceTree", "base", "candidate", "candidateTree"):
        require_sha(identity[key])
    if identity["lane"] == "source":
        if identity["candidate"] != expected or identity["candidateTree"] != identity["sourceTree"]:
            raise ValueError("source candidate mismatch")
    elif identity["lane"] == "merge":
        if identity["parents"] != [identity["base"], expected]:
            raise ValueError("ordered merge parent mismatch")
    else:
        raise ValueError("unknown qualification lane")
    rows = report["steps"]
    if [row["name"] for row in rows] != [name for name, _ in STEPS]:
        raise ValueError("missing, duplicate or reordered diagnostic step")
    for row, (name, argv) in zip(rows, STEPS, strict=True):
        if row["argv"] != argv or row["log"] != f"{name}.log":
            raise ValueError("unexpected command or log path")
        data = (directory / row["log"]).read_bytes()
        if len(data) > MAX_LOG or row["logSha256"] != digest(data):
            raise ValueError("log integrity failure")
        if row["status"] != "passed" or row["exitCode"] != 0 or row["logTruncated"]:
            raise ValueError("failed, truncated or incomplete diagnostic is not qualification")
        actual = passed_tests(data.decode("utf-8", errors="replace"))
        if actual != row["passedTests"] or (argv[:2] == ["just", "test"] and not actual):
            raise ValueError("test execution is missing or altered")
    if not report.get("trackedSourceUnchanged"):
        raise ValueError("source changed during qualification")
    traced = report.get("nativeTraceability", [])
    if {row["requirement"] for row in traced} != {f"ART-{index:02d}" for index in range(1, 14)}:
        raise ValueError("missing requirement coverage")
    if traced != traceability(rows) or any(row["execution"] != "passed" for row in traced):
        raise ValueError("required regression was not observed or mapping changed")
    if report.get("sourceBindings") != source_bindings():
        raise ValueError("source bindings do not match checkout")
    if report.get("activation") or report.get("independentAcceptance") or report.get("release"):
        raise ValueError("execution receipt cannot grant external authority")


def run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"schema": "hepta.learning-artifacts.qualification.v1", "identity": {}, "run": {key: os.environ.get(key, "") for key in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")}, "steps": [], "activation": False, "independentAcceptance": False, "release": False, "qualified": False}
    try:
        runner_blob = digest(Path(__file__).read_bytes())
        report["identity"] = materialize_candidate(os.environ.get("SOURCE_SHA", ""), os.environ.get("BASE_SHA", ""), os.environ.get("QUALIFICATION_LANE", ""))
        if runner_blob != digest(Path(__file__).read_bytes()):
            raise ValueError("merged runner differs; restart from the merged verifier")
        report["sourceBindings"] = source_bindings()
        write_report(report)
        for name, command in STEPS:
            result = execute(name, command)
            report["steps"].append(result)
            write_report(report)
            print(f"{name}: {result['status']} (exit {result['exitCode']})", flush=True)
        report["nativeTraceability"] = traceability(report["steps"])
        report["trackedSourceUnchanged"] = not git("status", "--porcelain", "--untracked-files=no")
        write_report(report)
        verify_report(json.loads((OUT / "qualification.json").read_text()), OUT, report["identity"]["source"])
        report["qualified"] = True
        write_report(report)
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        report["failure"] = str(error)
        write_report(report)
        print(f"qualification failed: {error}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "verify"))
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--source")
    args = parser.parse_args()
    if args.command == "run":
        return run()
    if args.receipt is None or args.source is None:
        parser.error("verify requires --receipt and --source")
    try:
        verify_report(json.loads(args.receipt.read_text()), args.receipt.parent, args.source)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"invalid qualification: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
