from pathlib import Path
import tempfile
import unittest

from context_compiler_named_evidence import bounded_lines

from context_compiler_execution import bind_test_count, observed_tests, specs
import context_compiler_qualification as legacy


def libtest(passed=1, failed=0, ignored=0):
    outcome = "FAILED" if failed else "ok"
    return (
        f"test result: {outcome}. {passed} passed; {failed} failed; "
        f"{ignored} ignored; 0 measured; 0 filtered out; finished in 0.01s"
    )


class ExecutionSummaryTests(unittest.TestCase):
    def test_response_stream_regressions_require_every_named_case(self):
        from context_compiler_named_evidence import bind_named_tests

        spec = next(
            value
            for value in specs(legacy)
            if value["name"] == "core-response-stream-regressions"
        )
        self.assertEqual(spec["argv"][:2], ["just", "test"])
        self.assertIn("codex-core", spec["argv"])
        self.assertIn("--lib", spec["argv"])
        names = spec["requiredNativeTests"]
        self.assertEqual(len(set(names)), 10)
        self.assertEqual(spec["minimumTests"], 10)
        self.assertEqual(
            spec["argv"][spec["argv"].index("-E") + 1],
            " | ".join(f"test({name})" for name in names),
        )
        for missing in [None, *names]:
            with self.subTest(missing=missing):
                # A green ten-test summary and an unrelated passing case must
                # not replace any required acknowledgement/cancellation case.
                observed = [name for name in names if name != missing]
                if missing is not None:
                    observed.append("client::tests::unrelated")
                summary = "Summary [1s] 10 tests run: 10 passed"
                result = {"succeeded": True}
                bind_test_count(summary, spec, result)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "native.log"
                    path.write_text(
                        "\n".join(f"PASS [0.1s] codex-core {name}" for name in observed)
                        + f"\n{summary}\n"
                    )
                    named = bind_named_tests(path, names)
                self.assertEqual(
                    result["succeeded"] and named["namedNativeTestsPassed"],
                    missing is None,
                )

    def test_websocket_identity_regression_requires_actual_named_nonzero_execution(
        self,
    ):
        from context_compiler_named_evidence import bind_named_tests

        spec = next(
            value
            for value in specs(legacy)
            if value["name"] == "core-websocket-connection-identity-regression"
        )
        self.assertIn("codex-core", spec["argv"])
        self.assertIn("--lib", spec["argv"])
        self.assertEqual(spec["minimumTests"], 1)
        name = "client::tests::websocket_connection_identity_binds_provider_and_stable_handshake_semantics"
        self.assertEqual(spec["requiredNativeTests"], [name])
        for count, observed, expected in [
            (0, name, False),
            (1, "client::tests::unrelated", False),
            (1, name, True),
        ]:
            with self.subTest(count=count, observed=observed):
                result = {"succeeded": True}
                log = f"Summary [1s] {count} tests run: {count} passed"
                bind_test_count(log, spec, result)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "native.log"
                    path.write_text(f"PASS [0.1s] (1/1) codex-core {observed}\n{log}\n")
                    named = bind_named_tests(path, spec["requiredNativeTests"])
                self.assertEqual(
                    result["succeeded"] and named["namedNativeTestsPassed"], expected
                )

    def test_protocol_wire_regression_requires_actual_named_nonzero_execution(self):
        from context_compiler_named_evidence import bind_named_tests

        spec = next(
            value
            for value in specs(legacy)
            if value["name"] == "agent-protocol-effect-wire-regression"
        )
        self.assertIn("codex-hepta-agent-protocol", spec["argv"])
        self.assertIn("--lib", spec["argv"])
        self.assertEqual(spec["minimumTests"], 1)
        name = "tests::automation_effect_wire_round_trip_is_strict_and_bounded"
        self.assertEqual(spec["requiredNativeTests"], [name])
        for count, observed in [(0, name), (1, "tests::unrelated")]:
            with self.subTest(count=count, observed=observed):
                result = {"succeeded": True}
                log = f"Summary [1s] {count} tests run: {count} passed"
                bind_test_count(log, spec, result)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "native.log"
                    path.write_text(
                        f"PASS [0.1s] (1/1) codex-hepta-agent-protocol {observed}\n{log}\n"
                    )
                    named = bind_named_tests(path, spec["requiredNativeTests"])
                self.assertFalse(
                    result["succeeded"] and named["namedNativeTestsPassed"]
                )

    def test_nextest_immediate_output_cannot_satisfy_larger_minimum(self):
        log = "\n".join(
            [
                "    " + libtest(),
                "    " + libtest(),
                "Summary [0.01s] 1 test run: 1 passed, 99 skipped",
            ]
        )
        result = {"succeeded": True}
        bind_test_count(log, {"minimumTests": 2, "testRunner": "nextest"}, result)
        self.assertEqual(
            result,
            {
                "succeeded": False,
                "minimumTests": 2,
                "testRunner": "nextest",
                "testsObserved": 1,
            },
        )

    def test_nextest_ansi_and_annotations(self):
        self.assertEqual(
            observed_tests(
                "\x1b[32m     Summary\x1b[0m [31.019s] 57 tests run: "
                "55 passed (1 flaky, 2 slow), 2 failed, 3750 skipped",
                runner="nextest",
            ),
            55,
        )

    def test_nextest_leaky_success_and_failed_annotations(self):
        result = {"succeeded": True}
        bind_test_count(
            "Summary [0.103s] 1 test run: 1 passed (1 leaky), 24 skipped",
            {"minimumTests": 1, "testRunner": "nextest"},
            result,
        )
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["testsObserved"], 1)
        result = {"succeeded": False}
        bind_test_count(
            "Summary [1s] 3 tests run: 2 passed (1 flaky, 1 slow, 1 leaky), "
            "1 failed (1 due to being leaky), 5 skipped",
            {"minimumTests": 1, "testRunner": "nextest"},
            result,
        )
        self.assertFalse(result["succeeded"])
        self.assertEqual(result["testsObserved"], 2)
        self.assertNotIn("testCountEvidenceFailure", result)

    def test_nextest_zero_passes_does_not_count_run_or_skipped(self):
        self.assertEqual(
            observed_tests(
                "Summary [1s] 2 tests run: 0 passed, 2 failed, 120 skipped",
                runner="nextest",
            ),
            0,
        )

    def test_nextest_missing_duplicate_and_malformed_fail_closed(self):
        valid = "Summary [1s] 1 test run: 1 passed"
        for log in [
            "",
            libtest(),
            valid + "\n" + valid,
            "Summary [1s] 9 tests run",
            "Summary [1s] 1 test run: 1 passed garbage",
            valid + "\nSummary incomplete",
            "unrelated " + valid,
            "Summary [1s] 1 test run: 2 passed",
            "Summary [1s] 2 tests run: 1 passed",
            "Summary [1s] 1 test run: 1 passed, 4 failed",
        ]:
            with self.subTest(log=log):
                result = {"succeeded": True}
                bind_test_count(
                    log, {"minimumTests": 1, "testRunner": "nextest"}, result
                )
                self.assertFalse(result["succeeded"])
                self.assertTrue(result["testCountEvidenceFailure"])
                self.assertEqual(result["testsObserved"], 0)

    def test_nested_summary_text_cannot_override_genuine_runner_summary(self):
        result = {"succeeded": True}
        bind_test_count(
            "    Summary [1s] 2 tests run: 2 passed\n"
            "Summary [1s] 1 test run: 1 passed\n",
            {"minimumTests": 2, "testRunner": "nextest"},
            result,
        )
        self.assertFalse(result["succeeded"])
        self.assertTrue(result["testCountEvidenceFailure"])

    def test_stream_checks_earlier_summary_outside_the_former_tail_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "command.log"
            path.write_text(
                "Summary [1s] 1 test run: 1 passed\n"
                + "ordinary output\n" * 100000
                + "Summary [1s] 1 test run: 1 passed\n"
            )
            result = {"succeeded": True}
            bind_test_count(
                bounded_lines(path),
                {"minimumTests": 1, "testRunner": "nextest"},
                result,
            )
            self.assertFalse(result["succeeded"])
            self.assertTrue(result["testCountEvidenceFailure"])

    def test_stream_decode_and_line_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "command.log"
            for prefix in [b"x" * (64 * 1024 + 1), b"\xff"]:
                path.write_bytes(prefix + b"\nSummary [1s] 1 test run: 1 passed\n")
                result = {"succeeded": True}
                bind_test_count(
                    bounded_lines(path),
                    {"minimumTests": 1, "testRunner": "nextest"},
                    result,
                )
                self.assertFalse(result["succeeded"])
                self.assertTrue(result["testCountEvidenceFailure"])

    def test_retained_e7dad_receipt_summary_fixtures(self):
        # Parser fixtures only, never execution evidence for this source revision.
        # GitHub run 36980052695 artifact 11216783951, ZIP SHA256:
        # d24544c31824779699abec2187e04eb91b9d7dbf676ea10e050ad5ee4c174000
        fixtures = [
            (
                10,
                "     Summary [ 103.146s] 10 tests run: 10 passed (1 slow), 257 skipped",
            ),
            (4, "     Summary [   0.014s] 4 tests run: 4 passed, 263 skipped"),
            (3, "     Summary [   0.020s] 3 tests run: 3 passed, 264 skipped"),
            (
                55,
                "     Summary [  31.019s] 57 tests run: 55 passed (1 flaky), 2 failed, 3750 skipped",
            ),
        ]
        for expected, summary in fixtures:
            with self.subTest(summary=summary):
                self.assertEqual(observed_tests(summary, runner="nextest"), expected)

    def test_command_failure_cannot_be_overridden_by_count(self):
        result = {"succeeded": False}
        bind_test_count(
            "Summary [1s] 8 tests run: 8 passed",
            {"minimumTests": 1, "testRunner": "nextest"},
            result,
        )
        self.assertFalse(result["succeeded"])
        self.assertEqual(result["testsObserved"], 8)

    def test_libtest_multiple_suites_count_passes_only(self):
        self.assertEqual(
            observed_tests(
                libtest(11, 2, 4) + "\n" + libtest(8, 0, 12), runner="libtest"
            ),
            19,
        )

    def test_libtest_no_passes(self):
        self.assertEqual(observed_tests(libtest(0, 1, 8), runner="libtest"), 0)

    def test_libtest_absent_and_malformed_fail_closed(self):
        for log in [
            "",
            "there are 500 passed in the specification",
            "test result: ok. 11 passed;",
            "    " + libtest(),
        ]:
            with self.subTest(log=log), self.assertRaises(ValueError):
                observed_tests(log, runner="libtest")

    def test_runner_contract_is_required_and_not_inferred_from_output(self):
        with self.assertRaises(ValueError):
            observed_tests(libtest(), runner="unknown")
        with self.assertRaises(ValueError):
            observed_tests("Summary [1s] 1 test run: 1 passed", runner="libtest")
        for spec in specs(legacy):
            if "minimumTests" in spec:
                self.assertEqual(spec["argv"][:2], ["just", "test"])
                self.assertEqual(spec["testRunner"], "nextest")


if __name__ == "__main__":
    unittest.main(verbosity=2)
