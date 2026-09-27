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
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from string import Template

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


def load_record(path: Path, context: dict) -> dict:
    result = {"name": path.name, "status": "not_executed", "reason": "required record absent"}
    if not path.is_file():
        return result
    result["recordSha256"] = sha256(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("record is not an object")
        result.update(
            recordedStatus=record.get("status"), command=record.get("command"),
            commandExitCode=record.get("command_exit_code"),
            wrapperExitCode=record.get("exit_code"),
            observedPassedTests=record.get("observed_passed_tests", 0),
            observedFailedTests=record.get("observed_failed_tests", 0),
            minimumTests=record.get("minimum_tests", 0),
            timedOut=record.get("timed_out", False),
            outputLimitExceeded=record.get("output_limit_exceeded", False),
            diagnostic=record.get("error"),
        )
        problems = []
        for key in ("tested_sha", "source_sha", "base_sha", "lane", "run_id", "run_attempt"):
            if record.get(key) != context.get(key):
                problems.append("record identity mismatch: " + key)
        before, after = record.get("before") or {}, record.get("after") or {}
        for label, identity in (("before", before), ("after", after)):
            if (identity.get("commit") != context["tested_sha"]
                    or identity.get("tree") != context["tested_tree"]
                    or identity.get("dirty") is not False):
                problems.append(label + " identity missing, changed or dirty")
        if record.get("status") == "skipped":
            result.update(status="evidence_invalid" if problems else "not_executed",
                          reason="; ".join(problems) if problems else record.get("error", "explicitly skipped"))
            return result
        log_name = record.get("log_file")
        if not isinstance(log_name, str) or Path(log_name).name != log_name:
            problems.append("missing or unsafe command log")
        else:
            log = path.parent / log_name
            if not log.is_file() or log.is_symlink():
                problems.append("command log missing or redirected")
            else:
                result.update(logName=log_name, logBytes=log.stat().st_size, logSha256=sha256(log))
                if (result["logSha256"] != record.get("log_sha256")
                        or result["logBytes"] != record.get("log_bytes")):
                    problems.append("command log digest or length mismatch")
        if problems:
            result.update(status="evidence_invalid", reason="; ".join(problems))
        elif record.get("status") in ("running", "interrupted", "skipped"):
            result.update(status="incomplete", reason="command has no terminal execution")
        elif (record.get("status") == "passed"
              and record.get("command_exit_code") == 0 and record.get("exit_code") == 0
              and not record.get("timed_out") and not record.get("output_limit_exceeded")
              and record.get("observed_failed_tests", 0) == 0
              and record.get("observed_passed_tests", 0) >= record.get("minimum_tests", 0)):
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
    if args.plan is not None:
        try:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            if plan.get("schema") != "hepta.cognitive-store-qualification-plan.v1":
                raise ValueError("unknown qualification plan")
            required.extend(item["record"] for item in plan["commands"])
            evidence_paths.extend(Template(path).substitute(os.environ) for path in plan["evidence"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            identity_errors.append("invalid qualification plan: " + str(error))
    required = sorted(set(required))
    if not required or any(Path(name).name != name for name in required):
        identity_errors.append("required command names must be nonempty safe basenames")
        required = [name for name in required if Path(name).name == name]
    commands = [load_record(args.records / name, context) for name in required]
    evidence = []
    for value in sorted(set(evidence_paths)):
        path = Path(value)
        item = {"name": path.name, "status": "missing"}
        if path.is_file() and not path.is_symlink():
            item.update(status="retained", bytes=path.stat().st_size, sha256=sha256(path))
        evidence.append(item)
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
