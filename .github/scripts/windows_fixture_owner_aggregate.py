"""Check all five additional owner jobs without executing native tests.

This aggregation cannot supersede the original single-job 65-minute result.
It retains the different execution topology and unknown complete cost.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import sys
import traceback
import xml.etree.ElementTree as ET

from windows_fixture_followup import leak_observations, select_groups
from windows_native_probe import fingerprint, source, write_json

LIMIT = 64 * 1024 * 1024


def read_bytes(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("artifact member is not a regular file")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if len(data) > LIMIT or any(
        getattr(before, key) != getattr(after, key) for key in fields
    ):
        raise ValueError("artifact member is oversized or changed during reading")
    return data


def read_json(path):
    return json.loads(read_bytes(path))


def verify_manifest(directory):
    entries = read_json(directory / "MANIFEST.json")
    starts = [
        PureWindowsPath(row["path"])
        for row in entries
        if PureWindowsPath(row["path"]).name == "started.json"
    ]
    if len(starts) != 1 or not starts[0].is_absolute():
        raise ValueError("manifest has no unique original output root")
    original_root = starts[0].parent
    verified = {}
    for entry in entries:
        relative = PureWindowsPath(entry["path"]).relative_to(original_root)
        if not relative.parts or ".." in relative.parts:
            raise ValueError("manifest member escaped original output root")
        name = relative.as_posix()
        if name in verified:
            raise ValueError("manifest repeats an artifact member")
        data = read_bytes(directory.joinpath(*relative.parts))
        if (
            len(data) != entry["st_size"]
            or hashlib.sha256(data).hexdigest() != entry["sha256"]
        ):
            raise ValueError("artifact member differs from original manifest")
        verified[name] = entry
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }
    if actual != set(verified) | {"MANIFEST.json"}:
        raise ValueError("downloaded artifact is missing or adds unmanifested files")
    return verified


def expected_selection(keys, group):
    names = [name for binary, name in keys if binary == group["binaryId"]]
    return (
        len(keys) == len(names) == len(set(names)) == group["expected"]
        and set(group["required"]).issubset(names)
        and all(
            name in group["required"]
            or any(name.startswith(prefix) for prefix in group["prefixes"])
            for name in names
        )
        and all(
            sum(name.startswith(prefix) for name in names) == count
            for prefix, count in group["prefixes"].items()
        )
    )


def verify_group(directory, group, scope, identity, parser_class):
    manifest = verify_manifest(directory)
    receipt = read_json(directory / "RECEIPT.json")
    if (
        receipt.get("sourceSha") != identity["source"]
        or receipt.get("testedSha") != identity["source"]
        or receipt.get("sourceTree") != identity["tree"]
        or receipt.get("observerSha") != identity["observer"]
        or receipt.get("github", {}).get("GITHUB_RUN_ID") != identity["run"]
        or receipt.get("github", {}).get("GITHUB_RUN_ATTEMPT") != identity["attempt"]
        or receipt.get("github", {}).get("GITHUB_SHA") != identity["observer"]
        or receipt.get("selectedGroupId") != group["id"]
        or receipt.get("selectedExpectedTotal") != group["expected"]
        or receipt.get("originalExpectedTotal") != scope["expectedTotal"]
        or receipt.get("scope") != scope
        or receipt.get("executionTopology") != "additional_owner_group_job"
        or receipt.get("originalSingleJobReplayed") is not False
        or receipt.get("originalSingleJobResultSuperseded") is not False
    ):
        raise ValueError("owner receipt belongs to another source, run, or scope")
    before = read_json(directory / "source-before.json")
    after = read_json(directory / "source-after.json")
    if (
        before != after
        or before["source"]["head"] != identity["source"]
        or before["source"]["tree"] != identity["tree"]
        or before["observer"]["head"] != identity["observer"]
        or any(row["allChanges"] for row in before.values())
        or receipt.get("sourceUnchanged") is not True
    ):
        raise ValueError("owner source snapshots are changed or incorrectly bound")
    for path in directory.glob("*-source.json"):
        if read_json(path) != before:
            raise ValueError("an intermediate owner source snapshot drifted")
    results = receipt.get("groups", [])
    if len(results) != 1 or results[0].get("scope") != group:
        raise ValueError("owner receipt does not contain its one complete group")
    result = results[0]
    selection = read_json(directory / group["id"] / "selection.json")
    keys = selection["selected"]
    if not expected_selection(keys, group) or result.get("selection") != selection:
        raise ValueError("owner selection is not the original closed case set")
    commands_passed = True
    for phase, key in (
        ("discovery", "discoveryExecution"),
        ("tests", "nativeExecution"),
    ):
        command = read_json(directory / group["id"] / (phase + ".json"))
        if result.get(key) != command or command.get("status") != "completed":
            raise ValueError("owner original invocation is inconsistent or incomplete")
        commands_passed = commands_passed and command.get("exitCode") == 0
    execution = result["nativeExecution"]
    junit_name = group["id"] + "/nextest-store/local/junit.xml"
    data = read_bytes(directory / junit_name)
    mtime = manifest[junit_name]["st_mtime_ns"] / 1_000_000_000
    if (
        not execution["startedUnix"] <= mtime <= execution["finishedUnix"]
        or b"<!DOCTYPE" in data
        or b"<!ENTITY" in data
    ):
        raise ValueError("original owner JUnit is stale or contains declarations")
    xml = ET.fromstring(data, parser=ET.XMLParser(target=parser_class()))
    negative = {
        "failure",
        "error",
        "skipped",
        "rerunFailure",
        "rerunError",
        "flakyFailure",
        "flakyError",
    }
    cases = list(xml.iter("testcase"))
    actual_keys = sorted([[row.get("classname"), row.get("name")] for row in cases])
    if (
        xml.tag not in ("testsuite", "testsuites")
        or actual_keys != sorted(keys)
        or len({tuple(key) for key in actual_keys}) != len(actual_keys)
        or result.get("junit", {}).get("sha256") != hashlib.sha256(data).hexdigest()
    ):
        raise ValueError("owner fresh JUnit does not match its complete discovery")
    failures = sum(
        row.find("failure") is not None or row.find("error") is not None
        for row in cases
    )
    skipped = sum(row.find("skipped") is not None for row in cases)
    retry_records = sum(
        row.tag in {"rerunFailure", "rerunError", "flakyFailure", "flakyError"}
        for row in xml.iter()
    )
    junit_passed = not any(row.tag in negative for row in xml.iter()) and not any(
        int(row.get(attribute, "0")) != 0
        for row in xml.iter()
        if row.tag in ("testsuite", "testsuites")
        for attribute in ("failures", "errors", "skipped", "disabled")
    )
    log = "\n".join(
        read_bytes(directory / group["id"] / ("tests." + stream)).decode("utf-8")
        for stream in ("stdout", "stderr")
    )
    guard_skips = [marker for marker in scope["explicitSkipMarkers"] if marker in log]
    leaks = leak_observations(log)
    passed = (
        commands_passed
        and junit_passed
        and not guard_skips
        and not any(leaks.values())
        and receipt.get("exitCode") == 0
        and receipt.get("status") == "passed_selected_scope"
        and result.get("passed") is True
        and result.get("binariesUnchanged") is True
        and result.get("explicitSkipMarkers") == []
        and not any(result.get("leakObservations", {"missing": [True]}).values())
    )
    if group["id"] == "cli-cloud" and (
        not result.get("cliHelperBindingsBefore")
        or result["cliHelperBindingsBefore"] != result.get("cliHelperBindingsAfter")
    ):
        raise ValueError("CLI helper metadata binding is missing or changed")
    return {
        "id": group["id"],
        "passed": passed,
        "cleanPassedClaimed": passed,
        "executed": len(cases) - skipped,
        "xmlPassedCount": len(cases) - skipped - failures,
        "passCountSemantics": "XML only; may include leaked cases or guard early returns",
        "failures": failures,
        "keys": actual_keys,
        "excludedByFilter": selection["excludedCount"],
        "selectedSkipped": skipped,
        "retryRecords": retry_records,
        "leakObserved": bool(any(leaks.values())),
        "explicitSkipMarkers": guard_skips,
        "originalReceiptStatus": receipt.get("status"),
        "originalNativeExitCode": execution["exitCode"],
        "receiptSha256": manifest["RECEIPT.json"]["sha256"],
        "artifactDirectory": str(directory),
        "commandWallSecondsNotFullCost": execution["wallSecondsNotFullCost"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--expected-observer", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.is_relative_to(repo) or output.is_relative_to(args.input.resolve()):
        raise ValueError("aggregation output must be outside source and originals")
    output.mkdir(parents=True, exist_ok=False)
    identity = {
        "source": args.expected_source,
        "tree": args.expected_tree,
        "observer": args.expected_observer,
        "run": args.run_id,
        "attempt": args.run_attempt,
    }
    report = {
        "status": "failed_or_incomplete",
        "identity": identity,
        "executionTopology": "five_additional_owner_group_jobs",
        "originalSingleJobResultSuperseded": False,
        "fullCost": None,
        "researchAdvancement": False,
        "fullWorkspacePassed": False,
        "durabilityQualified": False,
        "legacyIsolationQualified": False,
        "groups": [],
    }
    before, passed = None, False
    try:
        if any(
            not re.fullmatch(r"[0-9a-f]{40}", identity[key])
            for key in ("source", "tree", "observer")
        ):
            raise ValueError("all source identities must be full commit/tree hashes")
        before = source(repo)
        if before["head"] != identity["observer"] or before["allChanges"]:
            raise ValueError("aggregator checkout is not the exact clean observer")
        scope = read_json(repo / ".github/fixtures/windows-fixture-followup-scope.json")
        groups = select_groups(scope, None)
        sys.path.insert(0, str(repo / "scripts"))
        from hepta_ci_junit import NoDoctypeTreeBuilder

        expected_dirs = set()
        for group in groups:
            name = f"windows-fixture-owner-{group['id']}-{identity['source']}-{identity['run']}-{identity['attempt']}"
            expected_dirs.add(name)
            directory = args.input / name
            try:
                result = verify_group(
                    directory, group, scope, identity, NoDoctypeTreeBuilder
                )
            except Exception:
                result = {
                    "id": group["id"],
                    "passed": False,
                    "error": traceback.format_exc(),
                }
            report["groups"].append(result)
        actual_dirs = {path.name for path in args.input.iterdir()}
        if actual_dirs != expected_dirs:
            raise ValueError("owner artifact set is missing, duplicated, or unexpected")
        keys = [key for group in report["groups"] for key in group.get("keys", [])]
        report["validatedSelected"] = len(keys)
        report["validatedExecuted"] = sum(
            group.get("executed", 0) for group in report["groups"]
        )
        report["validatedXmlPassed"] = sum(
            group.get("xmlPassedCount", 0) for group in report["groups"]
        )
        report["validatedFailed"] = sum(
            group.get("failures", 0) for group in report["groups"]
        )
        report["groupsWithUnavailableAccounting"] = [
            group["id"] for group in report["groups"] if "executed" not in group
        ]
        report["expectedTotal"] = scope["expectedTotal"]
        passed = (
            all(group["passed"] for group in report["groups"])
            and len(keys) == scope["expectedTotal"]
            and len({tuple(key) for key in keys}) == len(keys)
        )
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        try:
            after = source(repo)
            report["observerUnchanged"] = before is not None and before == after
            report["observerBefore"], report["observerAfter"] = before, after
        except Exception:
            report["observerUnchanged"] = False
            report["observerAfterError"] = traceback.format_exc()
        passed = passed and report["observerUnchanged"]
        report["passed"] = passed
        report["cleanPassedClaimed"] = passed
        report["status"] = (
            "passed_additional_owner_groups" if passed else "failed_or_incomplete"
        )
        report["aggregator"] = fingerprint(Path(__file__))
        write_json(output / "AGGREGATE.json", report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
