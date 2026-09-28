#!/usr/bin/env python3
"""Always retain a candidate-bound dossier, including failures and missing work.

Exit zero only for a complete terminal-success lane. Uploading this diagnostic
manifest is never itself a successful qualification or a target-host approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cognitive_store_plan import NAME, load_plan, no_duplicates, spec_sha256
from hepta_ci_exec import observed_test_counts

HEX40 = re.compile(r"^[0-9a-f]{40}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], text=True, stderr=subprocess.PIPE,
    ).strip()


def read_regular(path: Path, maximum: int) -> bytes:
    """Bound and retain the exact evidence inode; never follow a FIFO/symlink."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ValueError("invalid or oversized evidence file")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        current = path.stat(follow_symlinks=False)
        def identity(value):
            return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
        if len(data) > maximum or identity(before) != identity(after) or identity(before) != identity(current):
            raise ValueError("evidence file changed during read")
    return data


def load_record(path: Path, context: dict, expected: dict | None = None) -> dict:
    result = {"name": path.name, "status": "not_executed", "reason": "required record absent"}
    if not os.path.lexists(path):
        return result
    try:
        content = read_regular(path, 1024 * 1024)
        result["recordSha256"] = hashlib.sha256(content).hexdigest()
        record = json.loads(content, object_pairs_hook=no_duplicates)
        if not isinstance(record, dict):
            raise ValueError("record is not an object")
        result.update(
            recordedStatus=record.get("status"), command=record.get("command"),
            commandExitCode=record.get("command_exit_code"),
            wrapperExitCode=record.get("exit_code"),
            observedPassedTests=record.get("observed_passed_tests"),
            observedFailedTests=record.get("observed_failed_tests"),
            minimumTests=record.get("minimum_tests"),
            timedOut=record.get("timed_out", False),
            outputLimitExceeded=record.get("output_limit_exceeded", False),
            diagnostic=record.get("error"),
        )
        problems = []
        if expected is None:
            problems.append("no independently resolved committed command specification")
        else:
            if expected["record"] != path.name:
                problems.append("record name differs from planned command")
            for key in ("command", "working_directory", "minimum_tests", "timeout_seconds"):
                if record.get(key) != expected[key]:
                    problems.append("record differs from committed plan: " + key)
            if type(record.get("minimum_tests")) is not int:
                problems.append("minimum test count is not an integer")
            if type(record.get("timeout_seconds")) not in (int, float):
                problems.append("command timeout is not numeric")
            expected_digest = spec_sha256(expected)
            result["commandSpecSha256"] = expected_digest
            if record.get("command_spec_sha256") != expected_digest:
                problems.append("command/workload/limit specification digest mismatch")
        for key in ("tested_sha", "source_sha", "base_sha", "lane", "run_id", "run_attempt"):
            if record.get(key) != context.get(key):
                problems.append("record identity mismatch: " + key)
        before, after = record.get("before") or {}, record.get("after") or {}
        for label, identity in (("before", before), ("after", after)):
            if (not isinstance(identity, dict) or identity.get("commit") != context["tested_sha"]
                    or identity.get("tree") != context["tested_tree"]
                    or identity.get("dirty") is not False):
                problems.append(label + " identity missing, changed or dirty")
        if record.get("status") == "skipped":
            result.update(status="evidence_invalid" if problems else "not_executed",
                          reason="; ".join(problems) if problems else record.get("error", "explicitly skipped"))
            return result
        log_name = record.get("log_file")
        if (not isinstance(log_name, str) or not log_name or log_name in {".", ".."}
                or Path(log_name).name != log_name or "\\" in log_name):
            problems.append("missing or unsafe command log")
        else:
            log_data = read_regular(path.parent / log_name, 64 * 1024 * 1024)
            result.update(logName=log_name, logBytes=len(log_data),
                          logSha256=hashlib.sha256(log_data).hexdigest())
            if (result["logSha256"] != record.get("log_sha256")
                    or type(record.get("log_bytes")) is not int
                    or result["logBytes"] != record.get("log_bytes")):
                problems.append("command log digest or length mismatch")
            # Derive counts again from the retained raw output. A self-reported
            # counter cannot override the named test runner's terminal summary.
            passed, failed = observed_test_counts(log_data.decode("utf-8", errors="replace"))
            for key, count in (("observed_passed_tests", passed), ("observed_failed_tests", failed)):
                if type(record.get(key)) is not int or record[key] != count:
                    problems.append("record test count differs from retained log: " + key)
        if problems:
            result.update(status="evidence_invalid", reason="; ".join(problems))
        elif record.get("status") in ("running", "interrupted"):
            result.update(status="incomplete", reason="command has no terminal execution")
        elif (record.get("status") == "passed"
              and type(record.get("command_exit_code")) is int and record["command_exit_code"] == 0
              and type(record.get("exit_code")) is int and record["exit_code"] == 0
              and record.get("timed_out", False) is False
              and record.get("output_limit_exceeded", False) is False
              and record["observed_failed_tests"] == 0
              and record["observed_passed_tests"] >= expected["minimum_tests"]):
            result.update(status="passed", reason=None)
        else:
            result.update(status="failed", reason=record.get("error") or "command did not pass")
    except (OSError, ValueError, TypeError, KeyError) as error:
        result.update(status="evidence_invalid", reason=str(error))
    return result


def version(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--required", action="append", default=[])
    parser.add_argument("--evidence", action="append", default=[])
    args = parser.parse_args()
    context = {key.lower(): os.environ.get(key) for key in
               ("TESTED_SHA", "SOURCE_SHA", "BASE_SHA")}
    context.update(lane=os.environ.get("HEPTA_CI_LANE"), run_id=os.environ.get("GITHUB_RUN_ID"),
                   run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"), tested_tree=None)
    identity_errors = []
    identity = {}
    try:
        for key in ("tested_sha", "source_sha", "base_sha"):
            if HEX40.fullmatch(context[key] or "") is None:
                raise ValueError("invalid " + key)
        head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
        context["tested_tree"] = tree
        parents = git("show", "-s", "--format=%P", "HEAD").split()
        if head != context["tested_sha"] or git("status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("checkout differs from the clean tested candidate")
        if context["lane"] == "source-head":
            if head != context["source_sha"]:
                raise ValueError("source lane does not test the exact source")
        elif context["lane"] == "base-merge":
            if parents != [context["base_sha"], context["source_sha"]]:
                raise ValueError("merge parents differ from frozen base/source")
            if git("merge-tree", "--write-tree", context["base_sha"], context["source_sha"]) != tree:
                raise ValueError("merge tree differs from the deterministic merge")
        else:
            raise ValueError("invalid qualification lane")
        identity = {
            "sourceSha": context["source_sha"], "sourceTree": git("rev-parse", context["source_sha"] + "^{tree}"),
            "baseSha": context["base_sha"], "baseTree": git("rev-parse", context["base_sha"] + "^{tree}"),
            "testedSha": head, "testedTree": tree, "parents": parents,
            "workflowBlob": git("rev-parse", head + ":.github/workflows/cognitive-store-qualification.yml"),
        }
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        identity_errors.append(str(error))
    required = list(args.required)
    evidence_paths = list(args.evidence)
    expectations = {}
    if args.plan is None:
        identity_errors.append("a committed qualification plan is required for terminal success")
    else:
        try:
            root = Path(git("rev-parse", "--show-toplevel"))
            canonical_plan = root / "docs/modules/cognitive.store/QUALIFICATION_PLAN.json"
            if args.plan.resolve(strict=True) != canonical_plan:
                raise ValueError("qualification must use the canonical committed plan")
            if git("hash-object", str(canonical_plan)) != git(
                    "rev-parse", "HEAD:docs/modules/cognitive.store/QUALIFICATION_PLAN.json"):
                raise ValueError("qualification plan differs from the tested Git object")
            specs, planned_evidence = load_plan(canonical_plan, root, dict(os.environ))
            expectations = {item["record"]: item for item in specs}
            if any(name not in expectations for name in required):
                raise ValueError("requested record is not in the committed plan")
            required.extend(expectations)
            evidence_paths.extend(planned_evidence)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            identity_errors.append("invalid qualification plan: " + str(error))
    required = sorted(set(required))
    if not required or any(NAME.fullmatch(name) is None for name in required):
        identity_errors.append("required command names must be nonempty safe JSON basenames")
        required = [name for name in required if NAME.fullmatch(name) is not None]
    commands = [load_record(args.records / name, context, expectations.get(name)) for name in required]
    evidence = []
    for value in sorted(set(evidence_paths)):
        path = Path(value)
        item = {"name": path.name, "status": "missing"}
        if path.is_file() and not path.is_symlink():
            item.update(status="retained", bytes=path.stat().st_size, sha256=sha256(path))
        evidence.append(item)
    try:
        if (git("rev-parse", "HEAD") != context["tested_sha"] or
                git("status", "--porcelain", "--untracked-files=normal")):
            identity_errors.append("candidate changed during qualification collection")
    except (OSError, subprocess.SubprocessError) as error:
        identity_errors.append("cannot recheck final candidate: " + str(error))
    logs = [row["logName"] for row in commands if "logName" in row]
    if len(logs) != len(set(logs)):
        identity_errors.append("independent command records share a command log")
    passed = (not identity_errors and bool(commands)
              and all(row["status"] == "passed" for row in commands)
              and all(row["status"] == "retained" for row in evidence))
    receipt = {
        "schema": "hepta.cognitive-store-qualification-manifest.v2", **identity,
        "requestedIdentity": context, "identityErrors": identity_errors,
        "lane": context["lane"], "runId": context["run_id"], "runAttempt": context["run_attempt"],
        "job": os.environ.get("GITHUB_JOB"), "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"),
        "runner": {key: os.environ.get(key) for key in
                   ("RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")},
        "toolchain": {"rustc": version(["rustc", "--version", "--verbose"]),
                      "cargo": version(["cargo", "--version"]), "python": version(["python3", "--version"])},
        "generatedAt": datetime.now(timezone.utc).isoformat(), "commands": commands, "evidence": evidence,
        "result": "terminal-success" if passed else "terminal-failure",
        "executionComplete": bool(commands) and all(row["status"] in ("passed", "failed") for row in commands),
        "targetHostQualified": False, "independentAcceptance": False, "release": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
