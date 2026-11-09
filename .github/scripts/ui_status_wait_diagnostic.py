"""Run and preserve the original seven-case UI group on a diagnostic source.

This observer does not qualify the base source or infer a root cause. It adds no
browser retry, timeout, mock, filter, or network operation to the original group.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time


BASE_SHA = "d1b32a67cbe9ada0b7d911bdc7d08820253bb1ca"
BASE_TREE = "f95a33684df6aac0a32326e20b63d4017d7b1968"
STATUS_SPEC = "apps/hepta-control-ui/e2e/robrix-product-status.spec.mjs"
HOLD_HELPER = "apps/hepta-control-ui/tools/hold-owner-response.mjs"
DRIVER = ".github/scripts/ui_status_wait_diagnostic.py"
WORKFLOW = ".github/workflows/hepta-ui-status-wait-diagnostic.yml"
ALLOWED_CHANGES = {STATUS_SPEC, HOLD_HELPER, DRIVER, WORKFLOW}
BASE_UI_HASHES = {
    STATUS_SPEC: "a3217983fc51959767eddf9d43ad5ec9aab72e765b385decba234b8f7d9ec2aa",
    HOLD_HELPER: "953c32a3a4628b1b5e7aaf5f85f49192a8fa9fff872aff2702a14f673e872c70",
}
EXPECTED_CASES = {
    f"actual missing-owner status {width} {scenario}"
    for width in (1280, 640)
    for scenario in ("timeout", "navigation", "background")
} | {"bounded SDK stream terminal controls"}
COMMAND = [
    "xvfb-run",
    "-a",
    "npx",
    "playwright",
    "test",
    "--config=playwright.product.config.mjs",
]


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def source(root):
    return {
        "head": git(root, "rev-parse", "HEAD"),
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
        "changes": git(root, "status", "--porcelain", "--untracked-files=all"),
    }


def stable(path):
    if path.is_symlink():
        raise ValueError(f"unexpected evidence symlink: {path}")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(64 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        not stat.S_ISREG(before.st_mode)
        or len(data) > 64 * 1024 * 1024
        or any(getattr(before, key) != getattr(after, key) for key in fields)
    ):
        raise ValueError(f"unstable or oversized evidence: {path}")
    return data, {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mtime": after.st_mtime,
    }


def checked_source(root, expected):
    value = source(root)
    if value["head"] != expected or value["changes"]:
        raise ValueError("diagnostic source is not the exact clean checkout")
    return value


def admit(root, output, expected):
    output.mkdir(exist_ok=False)
    current = source(root)
    write(output / "SOURCE_BEFORE.json", current)
    checked_source(root, expected)
    if git(root, "rev-parse", BASE_SHA + "^{tree}") != BASE_TREE:
        raise ValueError("base source tree mismatch")
    subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", BASE_SHA, expected],
        check=True,
    )
    changes = set(git(root, "diff", "--name-only", BASE_SHA, expected).splitlines())
    if changes != ALLOWED_CHANGES:
        raise ValueError("diagnostic branch changes more than the reviewed four files")
    for path, digest in BASE_UI_HASHES.items():
        data = subprocess.check_output(
            ["git", "-C", str(root), "show", f"{BASE_SHA}:{path}"]
        )
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("original reviewed UI source bytes do not match")
    preserved = output / "source"
    inputs = []
    for name in sorted(
        ALLOWED_CHANGES
        | {
            ".github/workflows/ui-product-foundation.yml",
            "apps/hepta-control-ui/playwright.product.config.mjs",
            "apps/hepta-control-ui/e2e/robrix-font-transport.spec.mjs",
            "apps/hepta-control-ui/package-lock.json",
            "apps/hepta-control-ui/tools/build-product-preview.py",
            "apps/hepta-control-ui/tools/build-robrix.mjs",
        }
    ):
        data, identity = stable(root / name)
        destination = preserved / name.replace("/", "__").lstrip(".")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
        inputs.append({**identity, "preserved": str(destination.relative_to(output))})
    write(
        output / "ADMISSION.json",
        {
            "diagnosticOnly": True,
            "actualSource": current,
            "baseSourceSha": BASE_SHA,
            "baseSourceTree": BASE_TREE,
            "changedPaths": sorted(changes),
            "inputs": inputs,
            "originalCases": sorted(EXPECTED_CASES),
            "command": COMMAND,
            "configurationUnchanged": True,
            "originalTimeoutSeconds": 90,
            "rootCause": "not_determined",
            "fullCost": None,
            "scope": "one original gateway browser group; not the complete UI workflow",
            "notExecutedByThisWorkflow": [
                "SDK/native/headless Rust tests",
                "gateway Rust regression tests",
                "default/populated/sidebar three-browser suites and their pixel gates",
            ],
            "limitations": [
                "Synchronous diagnostic I/O may perturb timing.",
                "Original trace remains off; breadcrumbs do not replace a browser trace.",
                "A diagnostic pass is not acceptance of the base source or a proven fix.",
            ],
        },
    )


def run_group(root, output, expected):
    before = json.loads((output / "SOURCE_BEFORE.json").read_text())
    if checked_source(root, expected) != before:
        raise ValueError("source changed during build preparation")
    app = root / "apps/hepta-control-ui"
    for name in ("product-status", "product-status-results.json"):
        if (app / "test-results" / name).exists():
            raise ValueError("original browser output already exists before execution")
    started = time.time()
    monotonic = time.monotonic()
    write(
        output / "COMMAND_STARTED.json",
        {
            "command": COMMAND,
            "cwd": str(app),
            "startedUnix": started,
            "source": before,
            "launchStatus": "attempted",
            "diagnosticOnly": True,
        },
    )
    # Preserve the original child's complete combined byte stream. This outer
    # recorder adds no timeout or retry; the original 90 s cases and 60 min job apply.
    with (output / "browser-command.log").open("xb") as stream:
        result = subprocess.run(
            COMMAND, cwd=app, stdout=stream, stderr=subprocess.STDOUT
        )
    write(
        output / "COMMAND_FINISHED.json",
        {
            "command": COMMAND,
            "exitCode": result.returncode,
            "startedUnix": started,
            "finishedUnix": time.time(),
            "commandWallSeconds": time.monotonic() - monotonic,
            "combinedStdoutStderr": True,
            "log": stable(output / "browser-command.log")[1],
            "physicalCost": None,
            "fullHistoryCost": None,
        },
    )
    return result.returncode


def specs(suite):
    yield from suite.get("specs", [])
    for child in suite.get("suites", []):
        yield from specs(child)


def observe(root, output, expected):
    result = {
        "diagnosticOnly": True,
        "originalCaseSetExact": False,
        "allOriginalCasesPassed": False,
        "sourceUnchanged": False,
        "researchAdvancement": False,
        "productionQualified": False,
        "baseSourceQualified": False,
        "rootCause": "not_determined_by_collector",
        "physicalCost": None,
        "fullHistoryCost": None,
    }
    before = None
    valid = False
    try:
        before = json.loads((output / "SOURCE_BEFORE.json").read_text())
        after = source(root)
        write(output / "SOURCE_AFTER.json", after)
        result["actualSource"] = after
        result["sourceUnchanged"] = (
            after == before and after["head"] == expected and not after["changes"]
        )
        command = json.loads((output / "COMMAND_FINISHED.json").read_text())
        result["commandExit"] = command["exitCode"]
        report, identity = stable(
            root / "apps/hepta-control-ui/test-results/product-status-results.json"
        )
        result["originalReport"] = identity
        if not command["startedUnix"] <= identity["mtime"] <= command["finishedUnix"]:
            raise ValueError("browser report is outside the actual command interval")
        rows = []
        for spec in specs(json.loads(report)):
            for test in spec.get("tests", []):
                rows.append(
                    {
                        "title": spec["title"],
                        "project": test.get("projectName"),
                        "expectedStatus": test.get("expectedStatus"),
                        "reportedStatus": test.get("status"),
                        "attempts": [
                            {
                                "status": item.get("status"),
                                "retry": item.get("retry"),
                                "durationMs": item.get("duration"),
                            }
                            for item in test.get("results", [])
                        ],
                    }
                )
        result["originalCases"] = rows
        result["originalCaseSetExact"] = (
            len(rows) == len(EXPECTED_CASES)
            and {row["title"] for row in rows} == EXPECTED_CASES
            and all(row["project"] == "chromium" for row in rows)
        )
        result["singleAttemptPerOriginalCase"] = all(
            len(row["attempts"]) == 1 and row["attempts"][0]["retry"] == 0
            for row in rows
        )
        result["originalCasesCompletedWithoutSkip"] = all(
            len(row["attempts"]) == 1
            and row["attempts"][0]["status"] in {"passed", "failed", "timedOut"}
            for row in rows
        )
        valid = (
            result["sourceUnchanged"]
            and result["originalCaseSetExact"]
            and result["singleAttemptPerOriginalCase"]
            and result["originalCasesCompletedWithoutSkip"]
        )
        result["allOriginalCasesPassed"] = (
            valid
            and command["exitCode"] == 0
            and all(
                row["expectedStatus"] == "passed"
                and row["reportedStatus"] == "expected"
                and row["attempts"][0]["status"] == "passed"
                for row in rows
            )
        )
        progress = []
        directory = root / "apps/hepta-control-ui/test-results/product-status"
        for path in sorted(directory.rglob("status-wait-progress.jsonl")):
            data, identity = stable(path)
            records = [json.loads(line) for line in data.splitlines()]
            coherent = (
                bool(records)
                and len(records) <= 512
                and all(
                    row["sequence"] == index
                    and row["sourceSha"] == expected
                    and row["sourceTree"] == after["tree"]
                    and row["diagnosticOnly"] is True
                    and row.get("title") == records[0].get("title")
                    for index, row in enumerate(records, 1)
                )
            )
            progress.append(
                {
                    **identity,
                    "caseTitle": records[0].get("title") if records else None,
                    "records": len(records),
                    "sourceAndSequenceCoherent": coherent,
                    "capacityReached": any(
                        row.get("event") == "diagnostic-capacity-reached"
                        for row in records
                    ),
                }
            )
        result["progressFiles"] = progress
        result["progressTimingIsDiagnosticOnly"] = True
        result["progressSourceBoundAndNotTruncated"] = (
            len(progress) == 6
            and {row["caseTitle"] for row in progress}
            == EXPECTED_CASES - {"bounded SDK stream terminal controls"}
            and all(
                row["sourceAndSequenceCoherent"] and not row["capacityReached"]
                for row in progress
            )
        )
    except Exception as error:
        valid = False
        result["observationError"] = str(error)
    finally:
        try:
            final_source = source(root)
            write(output / "SOURCE_FINAL.json", final_source)
            result["finalSource"] = final_source
            result["sourceUnchanged"] = (
                before is not None
                and final_source == before
                and final_source["head"] == expected
                and not final_source["changes"]
            )
        except Exception as error:
            result["sourceUnchanged"] = False
            result["finalSourceError"] = str(error)
        if not result["sourceUnchanged"]:
            valid = False
            result["allOriginalCasesPassed"] = False
        result["observationStatus"] = (
            "original_execution_observed"
            if valid
            else "incomplete_or_invalid_observation"
        )
        write(output / "OBSERVATION.json", result)
        identities = []
        for path in sorted(output.rglob("*")):
            if path.is_file():
                identities.append(stable(path)[1])
        write(output / "MANIFEST.json", identities)
    return (
        0
        if valid
        and result["allOriginalCasesPassed"]
        and result.get("progressSourceBoundAndNotTruncated", False)
        else 1
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("admit", "run", "observe"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    try:
        if args.mode == "admit":
            admit(root, output, args.source_sha)
            return 0
        if args.mode == "run":
            return run_group(root, output, args.source_sha)
        return observe(root, output, args.source_sha)
    except Exception as error:
        if output.is_dir():
            write(
                output / f"DRIVER_FAILURE-{args.mode}.json",
                {
                    "mode": args.mode,
                    "error": str(error),
                    "diagnosticOnly": True,
                    "fullHistoryCost": None,
                    "qualification": False,
                },
            )
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
