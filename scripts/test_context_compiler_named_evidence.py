import json
from pathlib import Path
import tempfile
import unittest

from context_compiler_named_evidence import bind_named_tests, fixture_profile, named_passes


class NamedEvidenceTests(unittest.TestCase):
    def test_exact_native_and_nextest_passes(self):
        lines = ["test owner::test_case ... ok\n", " PASS [ 0.123s] (1/2) codex-hepta-agentd owner::nextest_case\n"]
        self.assertEqual(named_passes(lines), {"owner::test_case", "owner::nextest_case"})

    def test_skip_failure_source_and_substring_are_not_passes(self):
        for text in ["SKIP [0s] crate owner::test_case", "FAIL [0s] crate owner::test_case",
                     "test owner::test_case ... FAILED", "pub fn test_case() {}", "owner::test_case passed"]:
            self.assertEqual(named_passes([text]), set())

    def test_ansi_is_removed_without_accepting_unrelated_output(self):
        self.assertEqual(named_passes(["\x1b[32mPASS\x1b[0m [0s] crate owner::case"]), {"owner::case"})

    def test_named_inventory_is_required_even_with_a_green_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.log"
            path.write_text("test owner::other_case ... ok\ntest result: ok. 50 passed;\n")
            result = bind_named_tests(path, ["owner::required_case"])
            self.assertFalse(result["namedNativeTestsPassed"])
            self.assertEqual(result["missingNativeTests"], ["owner::required_case"])

    def test_duplicate_inventory_and_oversized_lines_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.log"
            path.write_text("")
            with self.assertRaises(ValueError):
                bind_named_tests(path, ["case", "case"])
        with self.assertRaises(ValueError):
            named_passes(["x" * (64 * 1024 + 1)])

    def test_missing_and_forged_profile_do_not_establish_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.log"
            path.write_text("no measurement\n")
            self.assertIsNone(fixture_profile(path))
            path.write_text('CONTEXT_OWNER_PROFILE {"schema":"forged","turns":257}\n')
            with self.assertRaises(ValueError):
                fixture_profile(path)

    def test_profile_retains_scope_and_exact_lifecycle(self):
        profile = {
            "schema": "hepta.context-owner-fixture-profile.v1", "turns": 257,
            "qualification_scope": "protocol_fixture_not_provider_or_target_host_acceptance",
            "full_owner_turn_p50_micros": 1, "full_owner_turn_p95_micros": 2,
            "full_owner_turn_p99_micros": 3,
            "diagnostics": {"staged_turns": 0, "active_attempts": 0, "preparing_turns": 0,
                            "unresolved_attempts": 0, "pre_send_records": 257, "final_records": 257,
                            "reserved_completion_bytes": 0, "authority": "deny_all"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.log"
            path.write_text("CONTEXT_OWNER_PROFILE " + json.dumps(profile) + "\n")
            self.assertEqual(fixture_profile(path), profile)
            profile["diagnostics"]["staged_turns"] = 1
            path.write_text("CONTEXT_OWNER_PROFILE " + json.dumps(profile) + "\n")
            with self.assertRaises(ValueError):
                fixture_profile(path)



class ConsumerProjectionTests(unittest.TestCase):
    def test_missing_real_consumer_and_missing_test_cannot_be_promoted(self):
        from context_compiler_named_evidence import consumer_projection
        rows = [{"id": "ingress", "definition": {"path": "owner.rs", "symbol": "stage"},
                 "consumer": None, "sourceState": "not_composed", "nativeTests": [], "command": None}]
        result = consumer_projection(rows, [], {"sourceCommit": "a" * 40})[0]
        self.assertFalse(result["namedNativeExecutionPassed"])
        self.assertEqual(result["authenticatedProductE2E"], "unverified")
        self.assertFalse(result["activation"])

    def test_named_pass_remains_native_only_and_failed_command_cannot_qualify(self):
        from context_compiler_named_evidence import consumer_projection
        rows = [{"id": "stage", "definition": {}, "consumer": {}, "sourceState": "source_composed",
                 "nativeTests": ["owner::test"], "command": "native"}]
        command = {"name": "native", "succeeded": True, "observedRequiredNativeTests": ["owner::test"]}
        result = consumer_projection(rows, [command], {})[0]
        self.assertTrue(result["namedNativeExecutionPassed"])
        self.assertEqual(result["authenticatedProductE2E"], "unverified")
        self.assertFalse(result["independentAcceptance"])
        command["succeeded"] = False
        self.assertFalse(consumer_projection(rows, [command], {})[0]["namedNativeExecutionPassed"])

if __name__ == "__main__":
    unittest.main()
