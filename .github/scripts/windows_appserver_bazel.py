"""Observe the original Windows Bazel app-server wrapper and all sixteen shards.

Discovery is a separate list-only test action. Its Bazel success is never counted
as executed Rust tests. Native case evidence is the original libtest log; Bazel's
XML is retained at its actual granularity, which may be one wrapper testcase.
"""

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import traceback
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

TARGET = "//codex-rs/app-server:app-server-all-test"
SHARDS = 16
REQUIRED = (
    "suite::v2::imagegen_extension::standalone_image_edit_uses_attached_model_visible_image",
    "suite::v2::turn_start::turn_start_file_change_approval_accept_for_session_persists_v2",
    "suite::v2::app_list::list_apps_uses_thread_feature_flag_when_thread_id_is_provided",
)
ORIGINAL_FILTERS = (
    "suite::code_mode::code_mode_can_call_hidden_dynamic_tools",
    "tests::windows_tests::conpty_ctrl_c_interrupts_powershell_foreground_child",
)
CONTRACT_HASHES = {
    "workspace_root_test_launcher.bat.tpl": "4d509f1a57ffb4a890a96b775468af8e2d0d83538af76d358d10628d8b442dae",
    "defs.bzl": "5913d39c808e44b09790a98a33abcc6cc5f7e7faa19cea6255dc288bdfee6a7a",
    ".bazelrc": "1fb435555b4cb0b73f010ddc2fe83aca930d3881389cf86cb8215504a6284397",
    "codex-rs/app-server/BUILD.bazel": "887e4da0e534c1175e730b733400491c74d1ed300a91b718928039ea147786c3",
}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LIMIT = 64 * 1024 * 1024
BINARY_LIMIT = 1024 * 1024 * 1024
RAW_GUARDS = (
    "skipping cloud-managed sandbox subprocess:",
    "Skipping test in a remote test environment:",
    "Skipping test because it cannot execute when network is disabled in a Codex sandbox.",
)


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def bounded(path, execution=None):
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
    keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        not stat.S_ISREG(before.st_mode)
        or len(data) > LIMIT
        or any(getattr(before, key) != getattr(after, key) for key in keys)
        or (
            execution is not None
            and not execution["startedUnix"]
            <= after.st_mtime
            <= execution["finishedUnix"]
        )
    ):
        raise ValueError("output is stale, unstable, oversized, or not a regular file")
    return data


def local_output(uri, output_base):
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise ValueError("test output is not an original local file URI")
    value = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", value):
        value = value[1:]
    path = Path(value).resolve(strict=True)
    if not path.is_relative_to(output_base):
        raise ValueError("test output escaped the current Bazel output base")
    return path


def test_events(events):
    results, summaries, summary_ids = [], [], []
    for event in events:
        identity = event.get("id", {})
        if "testResult" in identity:
            if identity["testResult"].get("label") != TARGET:
                raise ValueError("BEP contains a different test target")
            results.append(event)
        if "testSummary" in identity:
            if identity["testSummary"].get("label") != TARGET:
                raise ValueError("BEP contains a different test summary")
            summaries.append(event["testSummary"])
            summary_ids.append(identity["testSummary"])
    if not results or len(summaries) != 1:
        raise ValueError("BEP has no complete original test result and summary")
    keys = [
        (
            row["id"]["testResult"].get("run", 0),
            row["id"]["testResult"].get("shard", 0),
            row["id"]["testResult"].get("attempt", 0),
        )
        for row in results
    ]
    if (
        len(set(keys)) != len(keys)
        or any(type(value) is not int for key in keys for value in key)
        or any(
            run != 1 or not 1 <= shard <= SHARDS or attempt < 1
            for run, shard, attempt in keys
        )
    ):
        raise ValueError("duplicate or invalid run/shard/attempt identity")
    configurations = {
        json.dumps(row["id"]["testResult"].get("configuration"), sort_keys=True)
        for row in results
    }
    if (
        len(configurations) != 1
        or json.dumps(summary_ids[0].get("configuration"), sort_keys=True)
        not in configurations
    ):
        raise ValueError("test actions belong to different configurations")
    # BEP reports shard ids one-based; TEST_SHARD_INDEX used by the original
    # FNV wrapper is zero-based. Keep both identities explicit.
    for shard in range(1, SHARDS + 1):
        attempts = sorted(attempt for _, value, attempt in keys if value == shard)
        if not attempts or attempts != list(range(1, len(attempts) + 1)):
            raise ValueError("a shard or one of its consecutive attempts is missing")
    summary = summaries[0]
    if (
        any(
            type(summary.get(name)) is not int
            for name in ("totalRunCount", "runCount", "shardCount", "attemptCount")
        )
        or summary.get("totalRunCount") != len(keys)
        or summary.get("runCount") != 1
        or summary.get("shardCount") != SHARDS
        or summary.get("attemptCount") != max(attempt for _, _, attempt in keys)
        or summary.get("totalNumCached", 0) != 0
    ):
        raise ValueError(
            "BEP summary does not match the original sixteen-shard attempt roster"
        )
    return results, summary


def freshness(result, execution):
    if result.get("cachedLocally", False) or result.get("executionInfo", {}).get(
        "cachedRemotely", False
    ):
        return False
    value = result.get("testAttemptStart")
    if value is not None:
        started = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    else:
        started = int(result["testAttemptStartMillisEpoch"]) / 1000
    return execution["startedUnix"] <= started <= execution["finishedUnix"]


def discovery_names(text, required=REQUIRED):
    text = ANSI.sub("", text)
    names = re.findall(r"^(.+): test\r?$", text, re.MULTILINE)
    benchmarks = re.findall(r"^(.+): benchmark\r?$", text, re.MULTILINE)
    if (
        not names
        or len(names) != len(set(names))
        or not set(required).issubset(names)
        or benchmarks
        or re.search(
            r"^test .+ \.\.\. |^test result:|^running \d+ tests?", text, re.MULTILINE
        )
    ):
        raise ValueError(
            "original wrapper discovery is incomplete, duplicated, or executed cases"
        )
    return sorted(names)


def original_selection(root, discovered):
    for name, expected in CONTRACT_HASHES.items():
        if hashlib.sha256(bounded(root / name)).hexdigest() != expected:
            raise ValueError(
                "the reviewed original wrapper/filter/shard contract changed"
            )
    text = bounded(root / ".bazelrc").decode("utf-8")
    values = re.findall(
        r"^common:ci-windows --test_env=CODEX_BAZEL_TEST_SKIP_FILTERS=([^\r\n]+)$",
        text,
        re.MULTILINE,
    )
    if values != [",".join(ORIGINAL_FILTERS)]:
        raise ValueError("the original Windows skip-filter contract changed")
    return partition(discovered, ORIGINAL_FILTERS)


def fnv_shard(name):
    value = 2166136261
    for byte in name.encode("utf-8"):
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value % SHARDS


def partition(discovered, filters):
    if len(discovered) != len(set(discovered)) or not set(REQUIRED).issubset(
        discovered
    ):
        raise ValueError(
            "partition requires the complete unique discovery and required cases"
        )
    excluded = [
        {
            "name": name,
            "matchingOriginalFilters": [value for value in filters if value in name],
        }
        for name in discovered
        if any(value in name for value in filters)
    ]
    excluded_names = {row["name"] for row in excluded}
    selected = sorted(set(discovered) - excluded_names)
    if not set(REQUIRED).issubset(selected):
        raise ValueError("an original regression case was excluded")
    shards = {
        str(index): [name for name in selected if fnv_shard(name) == index]
        for index in range(SHARDS)
    }
    flattened = [name for names in shards.values() for name in names]
    if len(flattened) != len(set(flattened)) or sorted(flattened) != selected:
        raise ValueError("shard partition is not a disjoint complete union")
    return {
        "discovered": sorted(discovered),
        "discoveredCount": len(discovered),
        "originalSkipFilters": list(filters),
        "excludedByOriginalFilters": excluded,
        "excludedCount": len(excluded),
        "selected": selected,
        "selectedCount": len(selected),
        "shards": shards,
        "partitionAlgorithm": "original_wrapper_FNV1a_u32_UTF8_mod_16",
        "excludedCasesAreNotPassed": True,
    }


def libtest_result(text, expected, discovered_count):
    text = ANSI.sub("", text)
    row_pattern = re.compile(r"^test (.+) \.\.\. (ok|FAILED|ignored)(?:, (.*))?$")
    summary_pattern = re.compile(
        r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
        r"(\d+) measured; (\d+) filtered out;.*$"
    )
    rows, summaries, batch = [], [], []
    for line in text.splitlines():
        matched = row_pattern.fullmatch(line)
        if matched:
            name, state, reason = matched.groups()
            if reason is not None and state != "ignored":
                raise ValueError("unexpected original libtest status suffix")
            row = (name, state, reason)
            rows.append(row)
            batch.append(row)
        matched = summary_pattern.fullmatch(line)
        if matched:
            value = matched.groups()
            counts = [
                sum(state == wanted for _, state, _ in batch)
                for wanted in ("ok", "FAILED", "ignored")
            ]
            if (
                counts != [int(value[index]) for index in (1, 2, 3)]
                or int(value[4]) != 0
                or int(value[5]) != discovered_count - len(batch)
                or value[0] != ("FAILED" if counts[1] else "ok")
            ):
                raise ValueError(
                    "libtest batch rows, filters, and summary counts disagree"
                )
            summaries.append(value)
            batch = []
    names = [name for name, _, _ in rows]
    if batch or sorted(names) != sorted(expected) or len(names) != len(set(names)):
        raise ValueError(
            "original libtest results do not exactly equal this shard's declared subset"
        )
    if bool(summaries) != bool(expected):
        raise ValueError(
            "missing batch summary or an unexpected execution in an empty shard"
        )
    counts = {
        state: sum(row[1] == state for row in rows)
        for state in ("ok", "FAILED", "ignored")
    }
    guard_hits = [value for value in RAW_GUARDS if value in text]
    return {
        "caseEvidence": "original_libtest_test_log",
        "cases": [
            {"name": name, "status": state, "ignoredReason": reason}
            for name, state, reason in rows
        ],
        "executed": counts["ok"] + counts["FAILED"],
        "libtestOkCount": counts["ok"],
        "failedCount": counts["FAILED"],
        "ignoredCount": counts["ignored"],
        "ignoredNames": [name for name, state, _ in rows if state == "ignored"],
        "ignoredCasesAreNotExecuted": True,
        "originalBatchSummaries": summaries,
        "observedEarlyReturnGuardMarkers": guard_hits,
        "successStdoutAvailable": False,
        "silentEarlyReturnAbsentProven": False,
        "passed": counts["FAILED"] == 0 and not guard_hits,
    }


def xml_observation(data, parser_class):
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("Bazel XML contains forbidden declarations")
    root = ET.fromstring(data, parser=ET.XMLParser(target=parser_class()))
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected Bazel XML root")
    negative = {
        "failure",
        "error",
        "skipped",
        "rerunFailure",
        "rerunError",
        "flakyFailure",
        "flakyError",
    }
    cases = list(root.iter("testcase"))
    declared_negatives = [
        int(row.get(name, "0"))
        for row in root.iter()
        if row.tag in ("testsuite", "testsuites")
        for name in ("failures", "errors", "skipped", "disabled")
    ]
    declared_case_counts_match = all(
        int(row.get("tests")) == len(list(row.iter("testcase")))
        for row in root.iter()
        if row.tag in ("testsuite", "testsuites") and row.get("tests") is not None
    )
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "testcaseCount": len(cases),
        "testcases": [
            {"name": row.get("name"), "classname": row.get("classname")}
            for row in cases
        ],
        "granularity": "original_Bazel_XML_not_assumed_per_Rust_case",
        "declaredCaseCountsMatchActualXml": declared_case_counts_match,
        "passed": (
            bool(cases)
            and declared_case_counts_match
            and not any(declared_negatives)
            and all(row.get("status") in (None, "run", "passed") for row in cases)
            and not any(row.tag in negative for row in root.iter())
        ),
    }


def discovery_accounting(observations, summary, execution):
    if (
        execution["exitCode"] != 0
        or len(observations) != SHARDS
        or {row["identity"].get("shard", 0) for row in observations}
        != set(range(1, SHARDS + 1))
        or any(
            row["identity"].get("run", 0) != 1
            or row["identity"].get("attempt") != 1
            or not row["freshUncached"]
            or row.get("captureErrors")
            or not row.get("xml", {}).get("passed", False)
            or row["result"].get("status") != "PASSED"
            for row in observations
        )
        or summary.get("overallStatus") != "PASSED"
        or summary.get("totalRunCount") != SHARDS
    ):
        raise ValueError(
            "list-only discovery did not finish in sixteen original fresh first attempts"
        )
    lists = [discovery_names(row["log"]) for row in observations]
    if any(value != lists[0] for value in lists):
        raise ValueError("original discovery shards disagree on the complete list")
    return lists[0]


def execution_accounting(observations, summary, execution, selection):
    attempts = []
    for row in observations:
        shard = row["identity"].get("shard", 0) - 1
        parsed = {"passed": False, "complete": False}
        try:
            if row.get("captureErrors"):
                raise ValueError(
                    "original action outputs could not be completely preserved"
                )
            parsed = libtest_result(
                row["log"],
                selection["shards"][str(shard)],
                selection["discoveredCount"],
            )
            parsed["complete"] = True
        except (KeyError, ValueError) as error:
            parsed["error"] = str(error)
        attempts.append(
            {
                "identity": row["identity"],
                "wrapperZeroBasedShardIndex": shard,
                "originalBazelStatus": row["result"].get("status"),
                "freshUncached": row["freshUncached"],
                "originalXml": row.get("xml"),
                "libtest": parsed,
            }
        )
    first = [row for row in attempts if row["identity"].get("attempt") == 1]
    names = [case["name"] for row in first for case in row["libtest"].get("cases", [])]
    complete = (
        len(first) == SHARDS
        and {row["identity"].get("shard", 0) for row in first}
        == set(range(1, SHARDS + 1))
        and all(row["libtest"]["complete"] for row in first)
        and len(names) == len(set(names))
        and sorted(names) == selection["selected"]
    )
    required = [
        {
            "name": name,
            "observations": [
                case
                for row in first
                for case in row["libtest"].get("cases", [])
                if case["name"] == name
            ],
        }
        for name in REQUIRED
    ]
    required_ok = all(
        len(row["observations"]) == 1 and row["observations"][0]["status"] == "ok"
        for row in required
    )
    no_retry = len(attempts) == SHARDS and all(
        row["identity"].get("attempt") == 1 for row in attempts
    )
    passed = (
        execution["exitCode"] == 0
        and complete
        and no_retry
        and required_ok
        and summary.get("overallStatus") == "PASSED"
        and summary.get("totalRunCount") == SHARDS
        and all(
            row["freshUncached"]
            and row["originalBazelStatus"] == "PASSED"
            and row["libtest"]["passed"]
            and row.get("originalXml", {}).get("passed", False)
            for row in attempts
        )
    )
    return {
        "attempts": attempts,
        "attemptCount": len(attempts),
        "retryAttemptsObserved": sum(
            row["identity"].get("attempt", 0) > 1 for row in attempts
        ),
        "originalBazelOverallStatus": summary.get("overallStatus"),
        "originalBazelCommandExitCode": execution["exitCode"],
        "firstAttemptCoverageComplete": complete,
        "uniqueFirstAttemptNamesObserved": sorted(names),
        "firstAttemptUniqueSelectedCount": len(set(names)),
        "firstAttemptCounts": {
            key: sum(row["libtest"].get(key, 0) for row in first)
            for key in ("executed", "libtestOkCount", "failedCount", "ignoredCount")
        },
        "firstAttemptCountsArePartial": not complete,
        "requiredRegressionCases": required,
        "requiredRegressionCasesReportedOkAndNotIgnored": required_ok,
        "requiredRegressionCaseSilentEarlyReturnAbsence": "unknown_original_success_stdout_not_requested",
        "coverageNeverAddsRetryAttempts": True,
        "xmlCountsAreNotRustCaseCounts": True,
        "passed": passed,
    }


def phase_outputs(directory, execution, output_base, parser_class):
    data = bounded(directory / "bep.jsonl", execution)
    events, parse_errors = [], []
    for number, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line.decode("utf-8"))
            if not isinstance(event, dict) or not isinstance(event.get("id"), dict):
                raise ValueError("BEP event or identity is not an object")
            if "testResult" in event["id"] and (
                not isinstance(event["id"]["testResult"], dict)
                or not isinstance(event.get("testResult"), dict)
            ):
                raise ValueError("BEP test result identity or payload is not an object")
            events.append(event)
        except ValueError as error:
            parse_errors.append({"line": number, "error": str(error)})
    results = [event for event in events if "testResult" in event.get("id", {})]
    observations = []
    used_paths = set()
    for index, event in enumerate(results):
        identity, result = event["id"]["testResult"], event["testResult"]
        # The ordinal is not supplied by BEP and cannot contain a traversal.
        attempt = directory / f"original-action-{index:04d}"
        attempt.mkdir(exist_ok=False)
        row = {
            "identity": identity,
            "result": result,
            "freshUncached": False,
            "files": [],
            "captureErrors": [],
        }
        try:
            row["freshUncached"] = freshness(result, execution)
        except (KeyError, ValueError) as error:
            row["captureErrors"].append(str(error))
        names = set()
        for original in result.get("testActionOutput", []):
            name = original.get("name")
            if name not in ("test.log", "test.xml"):
                continue
            try:
                if name in names:
                    raise ValueError("duplicate named test output")
                names.add(name)
                path = local_output(original["uri"], output_base)
                content = bounded(path, execution)
                (attempt / name).write_bytes(content)
                row["files"].append(
                    {
                        "name": name,
                        "original": str(path),
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
                if str(path) in used_paths:
                    raise ValueError(
                        "different attempts refer to the same mutable original output"
                    )
                used_paths.add(str(path))
                if name == "test.log":
                    row["log"] = content.decode("utf-8")
                else:
                    row["xml"] = xml_observation(content, parser_class)
            except (OSError, KeyError, ValueError, ET.ParseError) as error:
                row["captureErrors"].append(str(error))
        if names != {"test.log", "test.xml"}:
            row["captureErrors"].append(
                "original Bazel test.log/test.xml output is incomplete"
            )
        write(
            attempt / "OBSERVATION.json",
            {key: value for key, value in row.items() if key != "log"},
        )
        observations.append(row)
    write(
        directory / "BEP_TEST_EVENTS.json",
        {
            "results": results,
            "parseErrors": parse_errors,
            "summaries": [
                event for event in events if "testSummary" in event.get("id", {})
            ],
        },
    )
    # Preserve every reachable original attempt before applying roster checks.
    if parse_errors:
        raise ValueError("BEP contains invalid or truncated original event lines")
    _, summary = test_events(events)
    return observations, summary


def artifact_fingerprint(path, limit=BINARY_LIMIT):
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError("artifact is not a bounded regular file")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in keys):
        raise ValueError("artifact changed while hashing")
    return {
        "path": str(path),
        "sha256": digest,
        **{key: getattr(after, key) for key in keys},
    }


def manifest_mapping(text, logical):
    matches = []
    for line in text.splitlines():
        if line.startswith(" "):
            raise ValueError(
                "escaped runfiles manifests are outside the reviewed original batch parser"
            )
        key, separator, value = line.partition(" ")
        if key == logical or key.endswith("/" + logical):
            matches.append(value if separator else key)
    if not matches or len(set(matches)) != 1:
        raise ValueError(
            "runfile is missing or has ambiguous physical mappings: " + logical
        )
    return matches[0]


def generated_binaries(output_base):
    matches = [
        path.resolve(strict=True)
        for path in (output_base / "execroot").rglob("app-server-all-test.bat")
        if path.is_file()
        and path.parent.as_posix().endswith("/bin/codex-rs/app-server")
    ]
    if len(set(matches)) != 1:
        raise ValueError("expected exactly one generated original app-server wrapper")
    wrapper = matches[0]
    content = bounded(wrapper).decode("utf-8")
    exports = re.findall(
        r'call :resolve_runfile "([^"\r\n]+)"\r?\nif errorlevel 1 exit /b 1\r?\nset "([^"=\r\n]+)=!resolve_runfile_result!"',
        content,
    )
    selected = [
        (name, logical)
        for logical, name in exports
        if name == "test_bin" or name.startswith("CARGO_BIN_EXE_")
    ]
    required = {
        "test_bin",
        "CARGO_BIN_EXE_codex-app-server",
        "CARGO_BIN_EXE_codex-code-mode-host",
        "CARGO_BIN_EXE_codex-command-runner",
        "CARGO_BIN_EXE_codex-windows-sandbox-setup",
    }
    if not required.issubset(name for name, _ in selected) or len(selected) != len(
        {name for name, _ in selected}
    ):
        raise ValueError("generated wrapper lacks unique required executable exports")
    candidates = [
        Path(str(wrapper) + ".runfiles_manifest"),
        wrapper.with_suffix(".runfiles_manifest"),
        Path(str(wrapper) + ".exe.runfiles_manifest"),
        Path(str(wrapper) + ".runfiles") / "MANIFEST",
    ]
    manifests = list(
        dict.fromkeys(
            path.resolve(strict=True) for path in candidates if path.is_file()
        )
    )
    if not manifests:
        raise ValueError(
            "the generated wrapper's original runfiles manifest is missing"
        )
    maps = []
    for manifest in manifests:
        text = bounded(manifest).decode("utf-8")
        value = []
        for name, logical in selected:
            physical = Path(manifest_mapping(text, logical))
            if not physical.is_absolute():
                raise ValueError("runfiles binary mapping must be absolute")
            physical = physical.resolve(strict=True)
            if (
                not physical.is_relative_to(output_base)
                or physical.suffix.lower() != ".exe"
            ):
                raise ValueError(
                    "runfiles binary escaped this output base or is not an executable"
                )
            with physical.open("rb") as stream:
                if stream.read(2) != b"MZ":
                    raise ValueError("mapped Windows executable has no PE DOS header")
            value.append(
                {"export": name, "logical": logical, "physical": str(physical)}
            )
        maps.append(value)
    if any(value != maps[0] for value in maps):
        raise ValueError("generated runfiles manifests disagree on binary identities")
    files = list(
        dict.fromkeys(
            [wrapper, *manifests, *(Path(row["physical"]) for row in maps[0])]
        )
    )
    if sum(path.stat().st_size for path in files) > 3 * BINARY_LIMIT:
        raise ValueError("bounded original executable preservation exceeds three GiB")
    return files, {
        "wrapper": str(wrapper),
        "runfilesManifests": [str(path) for path in manifests],
        "exports": maps[0],
        "runtimeEphemeralStagingBytesCaptured": False,
        "boundary": "Generated original wrapper/runfiles mapping and all mapped executable bytes; no claim to observe each ephemeral installed copy or the child environment.",
    }


def preserve_binaries(output_base, output):
    files, mapping = generated_binaries(output_base)
    before = [artifact_fingerprint(path) for path in files]
    directory = output / "binaries"
    directory.mkdir(exist_ok=False)
    preserved = []
    for index, (path, identity) in enumerate(zip(files, before, strict=True)):
        destination = directory / f"{index:02d}-{path.name}"
        with path.open("rb") as original, destination.open("xb") as copied:
            shutil.copyfileobj(original, copied, length=2 * 1024 * 1024)
        copy_identity = artifact_fingerprint(destination)
        if (
            copy_identity["sha256"] != identity["sha256"]
            or copy_identity["st_size"] != identity["st_size"]
        ):
            raise ValueError("preserved original executable bytes changed in transport")
        preserved.append({"original": identity, "preserved": copy_identity})
    if [artifact_fingerprint(path) for path in files] != before:
        raise ValueError("generated executable changed while preserving its bytes")
    write(output / "RUNFILES_BINARY_MAPPING.json", mapping)
    write(output / "BINARIES_BEFORE.json", before)
    write(output / "PRESERVED_BINARIES.json", preserved)
    return files, before


def original_bash(value):
    if value is None:
        raise ValueError("the original workflow Bash executable is required")
    path = Path(value)
    if not path.is_absolute() or path.name.lower() != "bash.exe":
        raise ValueError(
            "the original workflow must provide an absolute Bash executable"
        )
    path = path.resolve(strict=True)
    bounded(path)
    return path


def bazel_command(source_sha, directory, mode, bash_executable):
    command = [
        str(bash_executable),
        "./.github/scripts/run-bazel-ci.sh",
        "--print-failed-action-summary",
        "--print-failed-test-logs",
        "--windows-msvc-host-platform",
        "--remote-download-toplevel",
        "--",
        "test",
        "--platforms=//:windows_x86_64_msvc",
        "--skip_incompatible_explicit_targets",
        "--test_tag_filters=-argument-comment-lint",
        "--test_verbose_timeout_warnings",
        "--build_metadata=COMMIT_SHA=" + source_sha,
        "--build_event_json_file=" + (directory / "bep.jsonl").as_posix(),
        "--nocache_test_results",
    ]
    if mode == "discovery":
        command += ["--test_arg=--list", "--test_arg=--format=terse"]
    command += ["--", TARGET]
    return command


def finalize_status(receipt, source_unchanged):
    receipt["sourceUnchanged"] = source_unchanged
    if not (
        source_unchanged
        and receipt.get("executablesUnchanged") is True
        and receipt.get("originalBashUnchanged") is True
    ):
        receipt["passed"] = False
    receipt["status"] = (
        "original_public_target_reported_pass_without_retry"
        if receipt["passed"]
        else "failed_or_incomplete"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("admit", "run"), required=True)
    parser.add_argument("--bash-executable")
    for name in (
        "root",
        "observer",
        "output",
        "source-sha",
        "tested-sha",
        "source-tree",
        "observer-sha",
    ):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    root, observer, output = (
        Path(value).resolve() for value in (args.root, args.observer, args.output)
    )
    sys.path.insert(0, str(observer / ".github/scripts"))
    from windows_native_probe import fingerprint, source
    from windows_fixture_followup import capture

    def identities():
        value = {"tested": source(root), "observer": source(observer)}
        if (
            args.source_sha != args.tested_sha
            or value["tested"]["head"] != args.source_sha
            or value["tested"]["tree"] != args.source_tree
            or value["observer"]["head"] != args.observer_sha
            or any(item["allChanges"] for item in value.values())
        ):
            raise ValueError(
                "source/observer identity or clean checkout assertion failed"
            )
        return value

    if args.mode == "admit":
        output.mkdir(exist_ok=False)
        write(output / "SOURCE_BEFORE.json", identities())
        write(
            output / "STARTED.json",
            {
                "sourceSha": args.source_sha,
                "testedSha": args.tested_sha,
                "observerSha": args.observer_sha,
                "target": TARGET,
                "originalShardCount": SHARDS,
                "nativeExecution": "not_run",
                "qualification": False,
                "fullCost": None,
                "fullWorkspace": False,
            },
        )
        write(
            output / "HOST.json",
            {
                "platform": platform.platform(),
                "python": sys.version,
                "environment": {
                    key: os.environ.get(key)
                    for key in (
                        "ImageOS",
                        "ImageVersion",
                        "RUNNER_OS",
                        "SystemRoot",
                        "WINDIR",
                        "COMSPEC",
                        "PROGRAMDATA",
                        "GITHUB_RUN_ID",
                        "GITHUB_RUN_ATTEMPT",
                    )
                },
                "notTheBazelTestProcessEnvironment": True,
            },
        )
        return 0

    receipt = {
        "status": "incomplete",
        "passed": False,
        "sourceSha": args.source_sha,
        "testedSha": args.tested_sha,
        "observerSha": args.observer_sha,
        "target": TARGET,
        "originalShardCount": SHARDS,
        "discoveryExecution": "not_run",
        "nativeExecution": "not_run",
        "fullWorkspace": False,
        "researchAdvancement": False,
        "fullCost": None,
        "durabilityQualified": False,
        "legacyIsolationQualified": False,
        "originalRunnerDifferences": {
            "scope": "one_original_public_target_not_the_whole_Windows_shard",
            "buildbuddyApiKeyProvidedByWorkflow": False,
            "buildbuddyApiKeyPresentInCoordinator": bool(
                os.environ.get("BUILDBUDDY_API_KEY")
            ),
            "withoutKey": "original_wrapper_uses_its_supported_keyless_path",
        },
        "successfulCaseSilentEarlyReturnAbsence": "unknown_original_libtest_capture_preserved",
        "ignoredAndOriginalFilterExcludedCasesNeverCountAsExecuted": True,
    }
    baseline = None
    bash_executable = None
    bash_before = None
    files = []
    binaries_before = None
    try:
        baseline = json.loads(
            (output / "SOURCE_BEFORE.json").read_text(encoding="utf-8")
        )

        def check(name):
            current = identities()
            write(output / (name + "-source.json"), current)
            if current != baseline:
                raise ValueError("source changed since admission")

        check("after-prepare")
        bash_executable = original_bash(args.bash_executable)
        bash_before = fingerprint(bash_executable)
        write(output / "ORIGINAL_BASH_BEFORE.json", bash_before)
        preserved_shell = output / "launch-shell"
        preserved_shell.mkdir(exist_ok=False)
        shutil.copyfile(bash_executable, preserved_shell / "bash.exe")
        if fingerprint(preserved_shell / "bash.exe")["sha256"] != bash_before["sha256"]:
            raise ValueError("original Bash executable transport changed its bytes")
        shell_version = capture(
            output, "original-bash-version", [str(bash_executable), "--version"], root
        )
        receipt["originalBashVersionCommand"] = shell_version
        if shell_version["exitCode"] != 0:
            raise ValueError("the original workflow Bash version query failed")
        check("after-shell-identification")
        for name, expected in CONTRACT_HASHES.items():
            if hashlib.sha256(bounded(root / name)).hexdigest() != expected:
                raise ValueError("reviewed original runner contract bytes changed")
        write(
            output / "ORIGINAL_SCOPE.json",
            {
                "target": TARGET,
                "shardCount": SHARDS,
                "originalTimeoutAttribute": "long",
                "originalFlakyAttribute": True,
                "requiredRegressionNames": REQUIRED,
                "originalSkipFilters": ORIGINAL_FILTERS,
                "discoveredCaseCount": None,
                "contractFileHashes": CONTRACT_HASHES,
                "noCaseFilterOrTimeoutOverride": True,
            },
        )
        spec = importlib.util.spec_from_file_location(
            "tested_junit", root / "scripts/hepta_ci_junit.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        # The original setup may only reserve this location. Bazel creates it.
        output_base = Path(os.environ["BAZEL_OUTPUT_BASE"]).resolve()
        observer_files = output / "observer-source"
        observer_files.mkdir(exist_ok=False)
        observer_origins = []
        for path in (
            ".github/scripts/windows_appserver_bazel.py",
            ".github/scripts/test_windows_appserver_bazel.py",
            ".github/scripts/windows_native_probe.py",
            ".github/scripts/windows_current_ci.py",
            ".github/scripts/windows_fixture_followup.py",
            ".github/workflows/hepta-windows-appserver-bazel.yml",
        ):
            original = observer / path
            content = bounded(original)
            preserved = observer_files / Path(path).name
            preserved.write_bytes(content)
            observer_origins.append(
                {"original": fingerprint(original), "preserved": fingerprint(preserved)}
            )
        write(output / "OBSERVER_FILES.json", observer_origins)
        runner_files = (
            ".bazelrc",
            ".bazelversion",
            "MODULE.bazel.lock",
            "defs.bzl",
            "workspace_root_test_launcher.bat.tpl",
            ".github/workflows/bazel.yml",
            ".github/actions/prepare-bazel-ci/action.yml",
            ".github/actions/setup-bazel-ci/action.yml",
            ".github/scripts/run-bazel-ci.sh",
            ".github/scripts/run_bazel_with_buildbuddy.py",
            "scripts/hepta_ci_junit.py",
            "codex-rs/app-server/BUILD.bazel",
            "codex-rs/app-server/tests/common/test_app_server.rs",
            "codex-rs/utils/cargo-bin/src/lib.rs",
            "codex-rs/windows-sandbox-rs/BUILD.bazel",
        )
        originals = output / "original-source"
        originals.mkdir(exist_ok=False)
        runner_origins = []
        for path in runner_files:
            content = bounded(root / path)
            destination = originals / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            runner_origins.append(
                {
                    "original": fingerprint(root / path),
                    "preserved": fingerprint(destination),
                }
            )
        write(output / "ORIGINAL_RUNNER_FILES.json", runner_origins)
        selection = None
        for mode in ("discovery", "execution"):
            check(mode + "-before")
            directory = output / mode
            directory.mkdir(exist_ok=False)
            command = bazel_command(args.source_sha, directory, mode, bash_executable)
            receipt[
                "discoveryExecution" if mode == "discovery" else "nativeExecution"
            ] = "command_launched_case_execution_unverified"
            execution = capture(directory, "command", command, root)
            receipt[mode + "Command"] = execution
            observations, summary = phase_outputs(
                directory, execution, output_base, module.NoDoctypeTreeBuilder
            )
            check(mode + "-after")
            receipt[mode + "BazelSummary"] = summary
            receipt[mode + "AttemptIdentities"] = [
                row["identity"] for row in observations
            ]
            receipt[mode + "AttemptCount"] = len(observations)
            receipt[mode + "FreshUncached"] = all(
                row["freshUncached"] for row in observations
            )
            if mode == "discovery":
                names = discovery_accounting(observations, summary, execution)
                selection = original_selection(root, names)
                receipt["discoveryExecution"] = (
                    "completed_list_only_zero_cases_executed"
                )
                write(
                    directory / "DISCOVERY.json",
                    {
                        "names": names,
                        "count": len(names),
                        "rustTestsExecuted": 0,
                        "originalListActions": SHARDS,
                        "repeatedListsAreNotAdditionalCases": True,
                    },
                )
                write(output / "SELECTION.json", selection)
                files, binaries_before = preserve_binaries(output_base, output)
                check("after-binary-preservation")
            else:
                accounting = execution_accounting(
                    observations, summary, execution, selection
                )
                write(directory / "ACCOUNTING.json", accounting)
                receipt["nativeAccounting"] = accounting
                receipt["nativeExecution"] = "test_actions_observed"
                receipt["originalXmlObservations"] = [
                    row.get("xml") for row in observations
                ]
                receipt["passed"] = accounting["passed"]
    except Exception as error:
        receipt["error"] = str(error)
        (output / "exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
        receipt["passed"] = False
    finally:
        try:
            after = [artifact_fingerprint(path) for path in files]
            write(output / "BINARIES_AFTER.json", after)
            receipt["executablesUnchanged"] = bool(files) and binaries_before == after
        except Exception as error:
            receipt["executablesUnchanged"] = False
            receipt["executablesAfterError"] = str(error)
        if not receipt["executablesUnchanged"]:
            receipt["passed"] = False
        try:
            bash_after = (
                fingerprint(bash_executable) if bash_executable is not None else None
            )
            write(output / "ORIGINAL_BASH_AFTER.json", bash_after)
            receipt["originalBashUnchanged"] = (
                bash_before is not None and bash_before == bash_after
            )
        except Exception as error:
            receipt["originalBashUnchanged"] = False
            receipt["originalBashAfterError"] = str(error)
        if not receipt["originalBashUnchanged"]:
            receipt["passed"] = False
        try:
            final = identities()
            write(output / "SOURCE_AFTER.json", final)
            receipt["sourceUnchanged"] = baseline is not None and final == baseline
        except Exception as error:
            receipt["sourceUnchanged"] = False
            receipt["sourceAfterError"] = str(error)
        finalize_status(receipt, receipt["sourceUnchanged"])
        write(output / "RECEIPT.json", receipt)
        write(
            output / "MANIFEST.json",
            [fingerprint(path) for path in sorted(output.rglob("*")) if path.is_file()],
        )
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
