"""Observer rejection controls only; no native product or Bazel execution."""

import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

import windows_appserver_bazel as observer


class Accounting(unittest.TestCase):
    def setUp(self):
        self.names = sorted(
            [
                *observer.REQUIRED,
                *(f"suite::fixture::case_{value:03d}" for value in range(80)),
                observer.ORIGINAL_FILTERS[0],
            ]
        )
        self.selection = observer.partition(self.names, observer.ORIGINAL_FILTERS)
        self.execution = {"startedUnix": 100.0, "finishedUnix": 120.0, "exitCode": 0}
        self.summary = {
            "overallStatus": "PASSED",
            "totalRunCount": 16,
            "runCount": 1,
            "shardCount": 16,
            "attemptCount": 1,
        }

    def log(self, names, changed=None, batches=1):
        changed = changed or {}
        if not names:
            return "wrapper empty shard\n"
        result = []
        for offset in range(0, len(names), max(1, len(names) // batches)):
            batch = names[offset : offset + max(1, len(names) // batches)]
            states = [changed.get(name, "ok") for name in batch]
            result.extend(
                f"test {name} ... {state}"
                for name, state in zip(batch, states, strict=True)
            )
            passed, failed, ignored = (
                states.count(value) for value in ("ok", "FAILED", "ignored")
            )
            status = "FAILED" if failed else "ok"
            result.append(
                f"test result: {status}. {passed} passed; {failed} failed; {ignored} ignored; 0 measured; {len(self.names) - len(batch)} filtered out; finished in 0.01s"
            )
        return "\n".join(result) + "\n"

    def observations(self, discovery=False):
        rows = []
        for shard in range(16):
            rows.append(
                {
                    "identity": {
                        "label": observer.TARGET,
                        "configuration": {"id": "same"},
                        "run": 1,
                        "shard": shard + 1,
                        "attempt": 1,
                    },
                    "result": {
                        "status": "PASSED",
                        "testAttemptStartMillisEpoch": "110000",
                    },
                    "freshUncached": True,
                    "captureErrors": [],
                    "xml": {
                        "passed": True,
                        "testcaseCount": 1,
                        "granularity": "original_Bazel_XML_not_assumed_per_Rust_case",
                    },
                    "log": "".join(name + ": test\n" for name in self.names)
                    if discovery
                    else self.log(self.selection["shards"][str(shard)], batches=2),
                }
            )
        return rows

    def events(self, rows=None, summary=None):
        rows = rows if rows is not None else self.observations()
        return [
            *(
                {"id": {"testResult": row["identity"]}, "testResult": row["result"]}
                for row in rows
            ),
            {
                "id": {
                    "testSummary": {
                        "label": observer.TARGET,
                        "configuration": {"id": "same"},
                    }
                },
                "testSummary": summary or self.summary,
            },
        ]

    def test_original_fnv_vectors_and_one_based_bep_are_distinct(self):
        self.assertEqual(observer.fnv_shard(""), 5)
        self.assertEqual(observer.fnv_shard("a"), 12)
        self.assertEqual(observer.fnv_shard("foobar"), 8)
        rows, summary = observer.test_events(self.events())
        self.assertEqual(
            [row["id"]["testResult"]["shard"] for row in rows], list(range(1, 17))
        )
        self.assertEqual(summary["totalRunCount"], 16)

    def test_partition_is_disjoint_and_original_exclusion_is_explicit(self):
        flattened = [
            name for names in self.selection["shards"].values() for name in names
        ]
        self.assertEqual(sorted(flattened), self.selection["selected"])
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(self.selection["excludedCount"], 1)
        self.assertEqual(
            self.selection["excludedByOriginalFilters"][0]["name"],
            observer.ORIGINAL_FILTERS[0],
        )
        self.assertTrue(self.selection["excludedCasesAreNotPassed"])

    def test_partition_rejects_missing_duplicate_and_required_exclusion(self):
        for names, filters in (
            (self.names[1:], observer.ORIGINAL_FILTERS),
            (self.names + self.names[:1], observer.ORIGINAL_FILTERS),
            (self.names, ("suite::v2",)),
        ):
            if not set(observer.REQUIRED).issubset(names):
                expected_failure = True
            else:
                expected_failure = len(names) != len(set(names)) or filters == (
                    "suite::v2",
                )
            if expected_failure:
                with (
                    self.subTest(names=names, filters=filters),
                    self.assertRaises(ValueError),
                ):
                    observer.partition(names, filters)

    def test_sixteen_equal_lists_are_zero_native_case_executions(self):
        result = observer.discovery_accounting(
            self.observations(True), self.summary, self.execution
        )
        self.assertEqual(result, self.names)
        self.assertEqual(len(result), len(self.names))

    def test_missing_duplicate_mismatched_and_executing_discovery_rejected(self):
        good = self.observations(True)
        variants = [good[:-1], good + good[:1]]
        mismatch = copy.deepcopy(good)
        mismatch[0]["log"] += "extra::case: test\n"
        variants.append(mismatch)
        executed = copy.deepcopy(good)
        executed[0]["log"] += "running 1 test\ntest fake ... ok\n"
        variants.append(executed)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                observer.discovery_accounting(value, self.summary, self.execution)

    def test_discovery_rejects_required_missing_duplicate_and_benchmark(self):
        good = self.observations(True)[0]["log"]
        for value in (
            good.replace(observer.REQUIRED[0] + ": test\n", ""),
            good + self.names[0] + ": test\n",
            good + "bench::case: benchmark\n",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                observer.discovery_names(value)

    def test_missing_duplicate_foreign_or_zero_based_bep_shard_rejected(self):
        variants = [
            self.events()[:-2] + self.events()[-1:],
            self.events() + self.events()[:1],
        ]
        for key, value in (
            ("label", observer.TARGET + "-bin"),
            ("shard", 0),
            ("shard", 17),
            ("run", 2),
            ("attempt", 0),
        ):
            changed = copy.deepcopy(self.events())
            changed[0]["id"]["testResult"][key] = value
            variants.append(changed)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                observer.test_events(value)

    def test_missing_retry_attempt_and_false_bep_summary_rejected(self):
        rows = self.observations()
        retry = copy.deepcopy(rows[0])
        retry["identity"]["attempt"] = 3
        with self.assertRaises(ValueError):
            observer.test_events(
                self.events(
                    rows + [retry],
                    {**self.summary, "totalRunCount": 17, "attemptCount": 3},
                )
            )
        for key, value in (
            ("totalRunCount", 17),
            ("runCount", 2),
            ("shardCount", 15),
            ("attemptCount", 2),
            ("totalNumCached", 1),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                observer.test_events(self.events(summary={**self.summary, key: value}))

    def test_bep_summary_configuration_and_integer_shape_are_bound(self):
        events = self.events()
        events[-1]["id"]["testSummary"]["configuration"] = {"id": "other"}
        with self.assertRaises(ValueError):
            observer.test_events(events)
        with self.assertRaises(ValueError):
            observer.test_events(
                self.events(summary={**self.summary, "runCount": True})
            )

    def test_complete_first_attempt_coverage_matches_all_selected_names(self):
        result = observer.execution_accounting(
            self.observations(), self.summary, self.execution, self.selection
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["firstAttemptCounts"]["executed"], len(self.names) - 1)
        self.assertEqual(result["firstAttemptUniqueSelectedCount"], len(self.names) - 1)
        self.assertEqual(result["retryAttemptsObserved"], 0)
        self.assertIn(
            "unknown", result["requiredRegressionCaseSilentEarlyReturnAbsence"]
        )

    def test_native_incomplete_union_and_cross_shard_duplicates_cannot_pass(self):
        missing = self.observations()[:-1]
        duplicated = self.observations()
        duplicated[-1]["log"] = duplicated[0]["log"]
        for rows in (missing, duplicated):
            result = observer.execution_accounting(
                rows, self.summary, self.execution, self.selection
            )
            self.assertFalse(result["passed"])
            self.assertFalse(result["firstAttemptCoverageComplete"])

    def test_retry_is_preserved_without_double_count_or_flaky_rescue(self):
        rows = self.observations()
        retry = copy.deepcopy(rows[0])
        retry["identity"]["attempt"] = 2
        rows[0]["result"]["status"] = "FAILED"
        summary = {
            **self.summary,
            "overallStatus": "FLAKY",
            "totalRunCount": 17,
            "attemptCount": 2,
        }
        observer.test_events(self.events(rows + [retry], summary))
        result = observer.execution_accounting(
            rows + [retry], summary, self.execution, self.selection
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["retryAttemptsObserved"], 1)
        self.assertEqual(result["firstAttemptUniqueSelectedCount"], len(self.names) - 1)

    def test_ordinary_ignored_is_named_and_never_counted_as_executed(self):
        rows = self.observations()
        name = next(
            value
            for value in self.selection["selected"]
            if value not in observer.REQUIRED
        )
        shard = observer.fnv_shard(name)
        rows[shard]["log"] = self.log(
            self.selection["shards"][str(shard)], {name: "ignored"}
        )
        result = observer.execution_accounting(
            rows, self.summary, self.execution, self.selection
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["firstAttemptCounts"]["ignoredCount"], 1)
        self.assertEqual(result["firstAttemptCounts"]["executed"], len(self.names) - 2)

    def test_required_ignored_failed_and_raw_guard_cannot_pass(self):
        name = observer.REQUIRED[0]
        shard = observer.fnv_shard(name)
        for state in ("ignored", "FAILED", "guard"):
            rows = self.observations()
            if state == "guard":
                rows[shard]["log"] += observer.RAW_GUARDS[0] + "fixture\n"
            else:
                rows[shard]["log"] = self.log(
                    self.selection["shards"][str(shard)], {name: state}
                )
            with self.subTest(state=state):
                self.assertFalse(
                    observer.execution_accounting(
                        rows, self.summary, self.execution, self.selection
                    )["passed"]
                )

    def test_batch_count_and_filter_count_must_match_actual_named_batch(self):
        names = self.selection["shards"]["0"]
        good = self.log(names, batches=2)
        for text in (
            good.replace("0 failed", "1 failed", 1),
            good.replace("0 measured", "1 measured", 1),
            good.replace(" filtered out", "9 filtered out", 1),
            good + f"test {names[0]} ... ok\n",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                observer.libtest_result(text, names, len(self.names))

    def test_stale_local_remote_cache_and_capture_error_cannot_pass(self):
        value = {"testAttemptStartMillisEpoch": "110000"}
        self.assertTrue(observer.freshness(value, self.execution))
        for changed in (
            {"cachedLocally": True},
            {"executionInfo": {"cachedRemotely": True}},
            {"testAttemptStartMillisEpoch": "99000"},
        ):
            self.assertFalse(observer.freshness({**value, **changed}, self.execution))
        for key, change in (
            ("freshUncached", False),
            ("captureErrors", ["missing XML"]),
        ):
            rows = self.observations()
            rows[0][key] = change
            self.assertFalse(
                observer.execution_accounting(
                    rows, self.summary, self.execution, self.selection
                )["passed"]
            )

    def test_xml_one_aggregate_is_not_inflated_into_rust_count(self):
        xml = observer.xml_observation(
            b'<testsuite tests="1"><testcase name="wrapper"/></testsuite>',
            ET.TreeBuilder,
        )
        self.assertTrue(xml["passed"])
        self.assertEqual(xml["testcaseCount"], 1)
        rows = self.observations()
        for row in rows:
            row["xml"] = xml
        result = observer.execution_accounting(
            rows, self.summary, self.execution, self.selection
        )
        self.assertEqual(result["firstAttemptCounts"]["executed"], len(self.names) - 1)
        self.assertTrue(result["xmlCountsAreNotRustCaseCounts"])

    def test_negative_xml_and_declarations_rejected(self):
        for child in (
            "failure",
            "error",
            "skipped",
            "rerunFailure",
            "rerunError",
            "flakyFailure",
            "flakyError",
        ):
            self.assertFalse(
                observer.xml_observation(
                    f'<testsuite><testcase name="wrapper"><{child}/></testcase></testsuite>'.encode(),
                    ET.TreeBuilder,
                )["passed"]
            )
        with self.assertRaises(ValueError):
            observer.xml_observation(b"<!DOCTYPE x><testsuite/>", ET.TreeBuilder)
        self.assertFalse(
            observer.xml_observation(
                b'<testsuite tests="999"><testcase name="wrapper"/></testsuite>',
                ET.TreeBuilder,
            )["passed"]
        )

    def test_original_arguments_preserve_budget_retries_target_and_no_execution_filter(
        self,
    ):
        for mode in ("discovery", "execution"):
            command = observer.bazel_command(
                "a" * 40, Path("records") / mode, mode, Path("C:/Git/bin/bash.exe")
            )
            self.assertEqual(command[-1], observer.TARGET)
            self.assertIn("--nocache_test_results", command)
            self.assertEqual("--test_arg=--list" in command, mode == "discovery")
            self.assertEqual(
                "--test_arg=--format=terse" in command, mode == "discovery"
            )
            self.assertFalse(
                any(
                    value.startswith(
                        (
                            "--test_timeout",
                            "--test_env",
                            "--runs_per_test",
                            "--flaky_test_attempts",
                            "--test_filter",
                            "--test_sharding_strategy",
                        )
                    )
                    for value in command
                )
            )
            if mode == "execution":
                self.assertFalse(
                    any(value.startswith("--test_arg") for value in command)
                )

    def test_final_source_binary_or_shell_drift_cannot_be_rescued(self):
        for changed in ("source", "binary", "shell"):
            receipt = {
                "passed": True,
                "executablesUnchanged": changed != "binary",
                "originalBashUnchanged": changed != "shell",
            }
            observer.finalize_status(receipt, changed != "source")
            self.assertFalse(receipt["passed"])
            self.assertEqual(receipt["status"], "failed_or_incomplete")
            receipt.update(executablesUnchanged=True, originalBashUnchanged=True)
            observer.finalize_status(receipt, True)
            self.assertFalse(receipt["passed"])

    def test_manifest_missing_ambiguous_and_escaped_mapping_rejected(self):
        self.assertEqual(
            observer.manifest_mapping("_main/a/b.exe C:/out/b.exe\n", "a/b.exe"),
            "C:/out/b.exe",
        )
        for text in (
            "other C:/x\n",
            "a/b.exe C:/one\n_main/a/b.exe C:/two\n",
            " escaped C:/one\n",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                observer.manifest_mapping(text, "a/b.exe")

    def test_generated_wrapper_maps_and_preserves_every_required_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = (
                root
                / "execroot/_main/bazel-out/windows-fastbuild/bin/codex-rs/app-server"
            )
            package.mkdir(parents=True)
            wrapper = package / "app-server-all-test.bat"
            exports = [
                ("test_bin", "app-server-all-test-bin"),
                ("CARGO_BIN_EXE_codex-app-server", "codex-app-server"),
                ("CARGO_BIN_EXE_codex-code-mode-host", "codex-code-mode-host"),
                ("CARGO_BIN_EXE_codex-command-runner", "codex-command-runner"),
                (
                    "CARGO_BIN_EXE_codex-windows-sandbox-setup",
                    "codex-windows-sandbox-setup",
                ),
            ]
            commands, mappings = [], []
            for export, name in exports:
                executable = package / (name + ".exe")
                executable.write_bytes(b"MZ observer file fixture, never executable")
                logical = "codex-rs/app-server/" + executable.name
                commands.extend(
                    [
                        f'call :resolve_runfile "{logical}"',
                        "if errorlevel 1 exit /b 1",
                        f'set "{export}=!resolve_runfile_result!"',
                    ]
                )
                mappings.append("_main/" + logical + " " + str(executable))
            wrapper.write_text("\n".join(commands) + "\n", encoding="utf-8")
            Path(str(wrapper) + ".runfiles_manifest").write_text(
                "\n".join(mappings) + "\n", encoding="utf-8"
            )
            output = root / "evidence"
            output.mkdir()
            files, before = observer.preserve_binaries(root, output)
            self.assertEqual(len(files), 7)
            self.assertEqual(
                before, [observer.artifact_fingerprint(path) for path in files]
            )
            self.assertEqual(len(list((output / "binaries").iterdir())), 7)
            binary = package / "codex-command-runner.exe"
            binary.write_bytes(b"MZ changed original")
            self.assertNotEqual(
                before, [observer.artifact_fingerprint(path) for path in files]
            )
            wrapper.write_text(
                wrapper.read_text().replace(
                    "CARGO_BIN_EXE_codex-command-runner", "unreviewed_export"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                observer.generated_binaries(root)

    def test_missing_or_bare_bash_never_falls_back_to_path(self):
        for value in (None, "bash", "bash.exe", "relative/bash.exe"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                observer.original_bash(value)

    def test_stale_or_foreign_original_output_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "test.log"
            path.write_text("original fixture", encoding="utf-8")
            with self.assertRaises(ValueError):
                observer.bounded(path, self.execution)
            with self.assertRaises(ValueError):
                observer.local_output("https://example.invalid/test.log", path.parent)

    def test_attempt_originals_are_saved_before_roster_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory = root / "evidence"
            directory.mkdir()
            original = root / "original"
            original.mkdir()
            log, xml = original / "test.log", original / "test.xml"
            log.write_text("actual failed action fixture\n", encoding="utf-8")
            xml.write_text(
                '<testsuite><testcase name="wrapper"><failure/></testcase></testsuite>',
                encoding="utf-8",
            )
            row = self.observations()[0]
            row["result"]["testActionOutput"] = [
                {"name": path.name, "uri": path.as_uri()} for path in (log, xml)
            ]
            now = time.time()
            row["result"]["testAttemptStartMillisEpoch"] = str(int(now * 1000))
            events = self.events([row], {**self.summary, "totalRunCount": 1})
            (directory / "bep.jsonl").write_text(
                "\n".join(json.dumps(value) for value in events), encoding="utf-8"
            )
            execution = {"startedUnix": now - 10, "finishedUnix": now + 10}
            with self.assertRaises(ValueError):
                observer.phase_outputs(directory, execution, root, ET.TreeBuilder)
            self.assertEqual(
                (directory / "original-action-0000/test.log").read_bytes(),
                log.read_bytes(),
            )
            self.assertEqual(
                (directory / "original-action-0000/test.xml").read_bytes(),
                xml.read_bytes(),
            )
            self.assertTrue((directory / "BEP_TEST_EVENTS.json").is_file())

    def malformed_phase(self, root, corrupt_xml=False, truncated_bep=False):
        directory = root / "evidence"
        directory.mkdir()
        rows = self.observations()[:2]
        now = time.time()
        for index, row in enumerate(rows):
            original = root / f"original-{index}"
            original.mkdir()
            log, xml = original / "test.log", original / "test.xml"
            log.write_text(f"actual action {index} original\n", encoding="utf-8")
            xml.write_text(
                "<testsuite><testcase"
                if corrupt_xml and index == 0
                else '<testsuite><testcase name="wrapper"/></testsuite>',
                encoding="utf-8",
            )
            row["result"]["testActionOutput"] = [
                {"name": path.name, "uri": path.as_uri()} for path in (log, xml)
            ]
            row["result"]["testAttemptStartMillisEpoch"] = str(int(now * 1000))
        data = "\n".join(json.dumps(value) for value in self.events(rows))
        if truncated_bep:
            data += '\n{"id": {"testSummary":'
        (directory / "bep.jsonl").write_text(data, encoding="utf-8")
        return directory, {"startedUnix": now - 10, "finishedUnix": now + 10}

    def assert_both_original_actions_preserved(self, root, directory):
        for index in range(2):
            for name in ("test.log", "test.xml"):
                self.assertEqual(
                    (directory / f"original-action-{index:04d}" / name).read_bytes(),
                    (root / f"original-{index}" / name).read_bytes(),
                )

    def test_corrupt_xml_does_not_discard_later_original_action_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory, execution = self.malformed_phase(root, corrupt_xml=True)
            with self.assertRaises(ValueError):
                observer.phase_outputs(directory, execution, root, ET.TreeBuilder)
            self.assert_both_original_actions_preserved(root, directory)
            first = json.loads(
                (directory / "original-action-0000/OBSERVATION.json").read_text()
            )
            self.assertTrue(first["captureErrors"])
            self.assertNotIn("xml", first)

    def test_truncated_bep_retains_reachable_outputs_and_still_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory, execution = self.malformed_phase(root, truncated_bep=True)
            with self.assertRaisesRegex(ValueError, "invalid or truncated"):
                observer.phase_outputs(directory, execution, root, ET.TreeBuilder)
            self.assert_both_original_actions_preserved(root, directory)
            collected = json.loads((directory / "BEP_TEST_EVENTS.json").read_text())
            self.assertEqual(len(collected["parseErrors"]), 1)


if __name__ == "__main__":
    unittest.main()
