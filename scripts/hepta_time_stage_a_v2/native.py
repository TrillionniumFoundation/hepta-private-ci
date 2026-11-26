"""Bind the exact sixteen names to original recorder, log, fresh JUnit and source."""

from collections import Counter
import os
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET

from . import contract as c
from .runtime import json_value, put, put_raw, read_json, require, sha256, stable_read


def verify_list(ctx, raw):
    listed, json_raw = json_value(raw), raw
    require(
        type(listed) is dict and "rust-suites" in listed,
        "nextest stdout is not one complete JSON object",
    )
    suites = listed["rust-suites"]
    require(
        type(listed["test-count"]) is int
        and listed["test-count"] == c.NATIVE_TESTS
        and type(suites) is dict
        and set(suites) == {c.BINARY_ID},
        "native list does not contain exactly the registered one-binary roster",
    )
    suite = suites[c.BINARY_ID]
    require(
        suite["package-name"] == c.PACKAGE
        and suite["binary-id"] == c.BINARY_ID
        and suite["status"] == "listed"
        and Path(suite["cwd"]).resolve() == ctx.root / "codex-rs/utils/time",
        "native suite identity/status/working directory changed",
    )
    cases = suite["testcases"]
    require(
        type(cases) is dict and set(cases) == {name for _, name in c.EXPECTED_PAIRS},
        "native listed names differ from the sixteen source controls",
    )
    require(
        all(
            row["ignored"] is False and row["filter-match"] == {"status": "matches"}
            for row in cases.values()
        ),
        "listed control is ignored or excluded by the exact filter",
    )
    put_raw(ctx.evidence / "native16.list.extracted-original.json", json_raw)
    put(
        ctx.evidence / "native16.list-verification.json",
        {
            "original_stdout_sha256": sha256(raw),
            "extracted_json_sha256": sha256(json_raw),
            "binary_ids": [c.BINARY_ID],
            "names": sorted(cases),
            "count": c.NATIVE_TESTS,
            "ignored": 0,
            "excluded": 0,
            "source_of_json": "Complete retained original stdout; original stderr retained separately",
        },
    )


def verify_native_log(ctx, record, candidate):
    expected_identity = {
        "commit": candidate["head"],
        "tree": candidate["tree"],
        "parents": candidate["parents"],
        "dirty": False,
    }
    require(
        record["status"] == "passed"
        and record["exit_code"] == 0
        and record["command_exit_code"] == record["returncode"] == 0
        and record["timed_out"] is False
        and record["output_limit_exceeded"] is False
        and record["command"] == c.native_command()
        and record["source_sha"] == record["tested_sha"] == candidate["head"]
        and record["lane"] == "source-head"
        and record["before"] == record["after"] == expected_identity
        and record["run_id"] == os.environ["GITHUB_RUN_ID"]
        and record["run_attempt"] == "1"
        and record["job"] == os.environ["GITHUB_JOB"]
        and record["minimum_tests"] == record["observed_passed_tests"] == c.NATIVE_TESTS
        and record["observed_failed_tests"] == 0,
        "original recorder did not bind a clean sixteen-control local candidate",
    )
    name = record["log_file"]
    require(
        Path(name).name == name and name.startswith("native16.execution.json."),
        "unexpected original native log locator",
    )
    raw, _ = stable_read(ctx.evidence / name)
    require(
        len(raw) == record["log_bytes"] and sha256(raw) == record["log_sha256"],
        "original native combined log changed",
    )
    output = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8"))
    require("\x1b" not in output, "unsupported escape sequence in native output")
    passes = re.findall(
        r"^\s*PASS\s+\[\s*[0-9.]+s\]\s+(\S+)\s+([A-Za-z_][A-Za-z0-9_:]*)\s*$",
        output,
        re.MULTILINE,
    )
    require(
        Counter(passes) == Counter(c.EXPECTED_PAIRS) and len(passes) == c.NATIVE_TESTS,
        "original log lacks each registered binary/name PASS exactly once",
    )
    require(
        not re.search(
            r"^\s*(?:SKIP|FAIL|FLAKY|LEAK|TIMEOUT|RETRY|EXECFAIL|ABORT|CANCEL|IGNORED)\b",
            output,
            re.MULTILINE,
        ),
        "original native output contains an incomplete, skipped, or failed control",
    )
    summaries = re.findall(
        r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+(\d+) tests? run:\s*([^\r\n]+)$",
        output,
        re.MULTILINE,
    )
    require(
        len(summaries) == 1
        and int(summaries[0][1]) == c.NATIVE_TESTS
        and re.fullmatch(r"16 passed(?: \(\d+ slow\))?, 0 skipped", summaries[0][2])
        is not None,
        "native summary is not one complete sixteen-pass zero-skip result",
    )
    ids = re.findall(
        r"^\s*Nextest run ID ([0-9a-f-]{36}) with nextest profile: local\s*$",
        output,
        re.MULTILINE,
    )
    starts = re.findall(
        r"^\s*Starting (\d+) tests across (\d+) binaries[^\r\n]*$", output, re.MULTILINE
    )
    require(
        len(ids) == 1 and starts == [("16", "1")],
        "native start/run UUID does not bind one exact single-binary invocation",
    )
    return {
        "nextest_run_id": ids[0],
        "original_combined_log_sha256": sha256(raw),
        "original_combined_log_bytes": len(raw),
        "pairs": [{"binary_id": a, "name": b} for a, b in sorted(c.EXPECTED_PAIRS)],
        "observed_passes": 16,
        "skips": 0,
        "duplicates": 0,
        "extra_passes": 0,
    }


def native_observation(ctx, candidate, snapshot, event):
    github_environment = {
        key: value for key, value in os.environ.items() if key.startswith("GITHUB_")
    }
    fields = ("SOURCE_SHA", "TESTED_SHA", "HEPTA_CI_LANE", "BASE_SHA")
    require(
        all(name not in os.environ for name in fields),
        "ambiguous inherited native source identity",
    )
    junit = ctx.root / "codex-rs/target/nextest/local/junit.xml"
    require(
        not junit.exists() and not junit.is_symlink(),
        "native JUnit path already exists before its original command",
    )
    explicit = {
        "SOURCE_SHA": candidate["head"],
        "TESTED_SHA": candidate["head"],
        "HEPTA_CI_LANE": "source-head",
        "BASE_SHA": "",
    }
    put(
        ctx.evidence / "native16.explicit-source-identity.json",
        {
            "github_event": event,
            "local_tested_identity": candidate,
            "explicit_native_inputs": explicit,
            "github_environment_modified": False,
            "source_role": "LOCAL_DERIVED_CANDIDATE_ONLY",
        },
    )
    try:
        os.environ.update(explicit)
        native_started = time.monotonic()
        cap = min(float(c.PHASE_CAPS["native16"]), ctx.remaining() - 3.0)
        require(cap > 1.5, "insufficient native command and reap budget")
        status = ctx.scope.owner.run(
            ctx.evidence / "native16.execution.json",
            c.native_command(),
            minimum_tests=c.NATIVE_TESTS,
            timeout_seconds=cap - 1.5,
        )
        elapsed = time.monotonic() - native_started
        require(elapsed <= cap, "native recorder exceeded its admitted elapsed cap")
        require(status == 0, "original native recorder failed")
        execution_raw, _ = stable_read(
            ctx.evidence / "native16.execution.json", 1024 * 1024
        )
        execution = json_value(execution_raw)
        original_log = verify_native_log(ctx, execution, candidate)
        collector = ctx.load_original(
            "scripts/hepta_ci_junit.py", "original_stage_a_junit"
        )
        original_xml, _ = stable_read(junit)
        copied = ctx.evidence / "native16.junit.xml"
        require(
            collector.collect(ctx.evidence / "native16.execution.json", junit, copied)
            == 0,
            "original fresh JUnit collector rejected the native observation",
        )
        retained, _ = stable_read(copied)
        fresh, _ = stable_read(junit)
        summary = read_json(copied.with_suffix(".summary.json"))
        require(
            retained == fresh == original_xml
            and summary["status"] == "passed"
            and summary["execution_sha256"] == sha256(execution_raw)
            and summary["source_sha"] == candidate["head"]
            and summary["source_tree"] == candidate["tree"]
            and summary["command"] == c.native_command()
            and summary["total_testcases"] == c.NATIVE_TESTS
            and summary["failures"]
            == summary["errors"]
            == summary["skipped_in_xml"]
            == 0
            and summary["junit_sha256"] == sha256(retained)
            and summary["junit_bytes"] == len(retained),
            "original JUnit is not the retained local candidate observation",
        )
        xml = ET.fromstring(
            retained, parser=ET.XMLParser(target=collector.NoDoctypeTreeBuilder())
        )
        suites = list(xml)
        require(
            xml.tag == "testsuites"
            and xml.attrib.get("uuid") == original_log["nextest_run_id"]
            and len(suites) == 1
            and suites[0].tag == "testsuite"
            and suites[0].attrib.get("name") == c.BINARY_ID,
            "JUnit UUID/suite differs from the one original nextest invocation",
        )
        require(
            not any(
                node.tag
                in (
                    "skipped",
                    "failure",
                    "error",
                    "rerunFailure",
                    "rerunError",
                    "flakyFailure",
                    "flakyError",
                )
                for node in xml.iter()
            ),
            "JUnit contains a non-passing control",
        )
        cases = list(xml.iter("testcase"))
        pairs = Counter(
            (case.attrib.get("classname"), case.attrib.get("name")) for case in cases
        )
        require(
            len(cases) == c.NATIVE_TESTS and pairs == Counter(c.EXPECTED_PAIRS),
            "JUnit does not contain the exact sixteen unique binary/name pairs",
        )
        ctx.assert_clean()
        after = ctx.snapshot(candidate["tree"])
        require(
            after == snapshot
            and ctx.git("rev-parse", "HEAD").decode().strip() == candidate["head"],
            "native source changed before final collection",
        )
        put(ctx.evidence / "local-source-after-native.json", after)
        ctx.check_time()
        return {
            "status": "LOCAL_DERIVED_CANDIDATE_NATIVE16_OBSERVED_REQUIRES_ROOT_REVIEW",
            "local_tested_identity": candidate,
            "actual_native_elapsed_seconds": elapsed,
            "original_log": original_log,
            "junit_sha256": sha256(retained),
            "fresh_original_collector_passed": True,
            "all_original_source_bytes_unchanged_during_native": True,
            **c.FALSE_QUALIFICATION,
        }
    finally:
        try:
            # Keep failed or rejected native XML as raw evidence too. This copy
            # grants no freshness/identity acceptance and does not retry collection.
            if junit.is_file() or junit.is_symlink():
                try:
                    raw_junit, info = stable_read(junit)
                    put_raw(
                        ctx.evidence
                        / "native16.unconditionally-retained-original.junit.xml",
                        raw_junit,
                    )
                    put(
                        ctx.evidence / "native16.unconditional-junit-retention.json",
                        {
                            "sha256": sha256(raw_junit),
                            "bytes": len(raw_junit),
                            "mtime_ns": info.st_mtime_ns,
                            "qualification": False,
                        },
                    )
                except Exception as error:
                    put(
                        ctx.evidence
                        / "native16.unconditional-junit-retention-error.json",
                        {
                            "error": f"{type(error).__name__}: {error}",
                            "qualification": False,
                        },
                    )
                    raise
        finally:
            for key in fields:
                os.environ.pop(key, None)
            require(
                github_environment
                == {
                    key: value
                    for key, value in os.environ.items()
                    if key.startswith("GITHUB_")
                },
                "a GitHub CI identity environment variable was modified",
            )
