"""Exercise the same expected-SHA entrypoint used by the contract workflow."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import test_hepta_implementation_maps as fixtures


class ExpectedCandidateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceIdentityTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.subject = fixtures.maps

    def cli(self, *args):
        output = io.StringIO()
        with (
            patch("sys.argv", ["hepta-implementation-maps.py", *args]),
            contextlib.redirect_stdout(output),
        ):
            self.subject.main()
        return json.loads(output.getvalue())

    def test_exact_candidate_cli_runs_the_source_verifier(self):
        candidate = self.subject.current_source_base()
        result = self.cli("verify", "--expected-sha", candidate["commit"])
        self.assertEqual(result["candidateSource"], candidate)
        self.assertEqual(result["status"], "PASS_HEPTA_IMPLEMENTATION_MAPS")

    def test_expected_source_is_not_the_historical_map_anchor(self):
        with (
            patch.object(self.subject, "load", wraps=self.subject.load) as load,
            self.assertRaises(SystemExit),
        ):
            self.cli("verify", "--expected-sha", self.fixture.anchor["commit"])
        load.assert_not_called()

    def test_same_tree_different_commit_still_rejects_wrong_event(self):
        before = self.subject.current_source_base()
        self.fixture.git("commit", "--allow-empty", "-qm", "new candidate event")
        after = self.subject.current_source_base()
        self.assertEqual(before["tree"], after["tree"])
        with (
            patch.object(self.subject, "load", wraps=self.subject.load) as load,
            self.assertRaises(SystemExit),
        ):
            self.cli("verify", "--expected-sha", before["commit"])
        load.assert_not_called()

    def test_short_ref_empty_and_noncanonical_sha_reject(self):
        current = self.subject.current_source_base()["commit"]
        for value in ("", "HEAD", current[:12], current.upper(), "g" * 40):
            with (
                self.subTest(value=value),
                patch.object(self.subject, "load", wraps=self.subject.load) as load,
                self.assertRaises(SystemExit),
            ):
                self.cli("verify", "--expected-sha", value)
            load.assert_not_called()

    def test_correct_sha_does_not_bypass_dirty_source_rejection(self):
        current = self.subject.current_source_base()["commit"]
        self.fixture.write("src/alpha/lib.rs", "pub fn changed() {}\n")
        with self.assertRaises(SystemExit):
            self.cli("verify", "--expected-sha", current)

    def test_expected_sha_cannot_be_used_to_generate_or_migrate(self):
        current = self.subject.current_source_base()["commit"]
        for command in ("generate", "migrate", "sync-plasticity-status"):
            with (
                self.subTest(command=command),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as result,
            ):
                self.cli(command, "--expected-sha", current)
            self.assertEqual(result.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
