#!/usr/bin/env python3
"""Read-only dual-lane execution over a previously bound Git candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import context_compiler_candidate as candidate

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def observed_tests(log: str) -> int:
    total = 0
    for line in ANSI.sub("", log).splitlines():
        if "test result:" not in line and "Summary" not in line:
            continue
        matched = re.search(r"\b(\d+) passed\b", line)
        if matched is None:
            matched = re.search(r"\b(\d+) tests run\b", line)
        if matched:
            total += int(matched.group(1))
    return total


def specs(legacy):
    commands = []
    for original in legacy.command_specs():
        spec = dict(original)
        spec["argv"] = list(original["argv"])
        if spec["argv"][:2] == ["cargo", "test"]:
            spec["argv"][:2] = ["just", "test"]
            spec["minimumTests"] = 1
        commands.append(spec)
    commands[2:2] = [
        {"name": "typed-slot-regressions", "cwd": legacy.CODEX_RS,
         "argv": ["just", "test", "--locked", "-p", "codex-api", "--lib", "context_slot"],
         "minimumTests": 11},
        {"name": "exact-body-regressions", "cwd": legacy.CODEX_RS,
         "argv": ["just", "test", "--locked", "-p", "codex-hepta-prompt-extension", "--lib", "exact_body"],
         "minimumTests": 8},
    ]
    return commands


def main() -> int:
    import context_compiler_qualification as legacy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-record", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    root = legacy.ROOT.resolve()
    output = args.output_dir.resolve()
    if output == root or root in output.parents:
        parser.error("execution evidence must be outside the checkout")
    output.mkdir(parents=True, exist_ok=True)
    record = json.loads(args.candidate_record.read_text(encoding="utf-8"))
    digest = record.pop("recordSha256", None)
    expected = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != expected:
        parser.error("candidate record digest mismatch")
    receipt = {
        "schema": "hepta.context-compiler-dual-lane-execution.v1",
        "candidate": record, "status": "running", "commands": [],
        "independentAcceptance": False, "activation": False, "release": False,
    }
    receipt_path = output / "context-compiler-qualification-receipt.json"
    failure = None
    try:
        candidate.verify(root, record)
        legacy.write_receipt(receipt_path, receipt)
        for index, spec in enumerate(specs(legacy), start=1):
            candidate.verify(root, record)
            log = output / "logs" / f"{index:02d}-{spec['name']}.log"
            result = legacy.run_command(spec, log)
            minimum = spec.get("minimumTests")
            if minimum is not None:
                # Summaries are at the tail; do not load an unbounded build log.
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 1024 * 1024))
                    count = observed_tests(stream.read().decode("utf-8", errors="replace"))
                result.update({"minimumTests": minimum, "testsObserved": count})
                result["succeeded"] = result["succeeded"] and count >= minimum
            receipt["commands"].append(result)
            candidate.verify(root, record)
            receipt.pop("receiptSha256", None)
            legacy.write_receipt(receipt_path, receipt)
        candidate.verify(root, record)
    except (Exception, KeyboardInterrupt) as error:
        failure = type(error).__name__
    receipt.pop("receiptSha256", None)
    receipt["failureClass"] = failure
    receipt["status"] = "passed" if (
        failure is None
        and len(receipt["commands"]) == len(specs(legacy))
        and all(item["succeeded"] or not item["required"] for item in receipt["commands"])
    ) else "failed"
    receipt["toolchain"] = {
        name: legacy.tool_version(argv)
        for name, argv in {
            "git": ["git", "--version"], "rustc": ["rustc", "-Vv"],
            "cargo": ["cargo", "--version"], "just": ["just", "--version"],
            "nextest": ["cargo", "nextest", "--version"],
        }.items()
    }
    receipt["createdAt"] = legacy.utc_now()
    receipt["manifestCanonicalSha256"] = legacy.canonical_manifest_sha256()
    import os
    receipt["workflowIdentity"] = {key: os.environ.get(key) for key in (
        "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_EVENT_NAME"
    )}
    legacy.write_receipt(receipt_path, receipt)
    print(f"qualification {receipt['status']}: {receipt_path}")
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
