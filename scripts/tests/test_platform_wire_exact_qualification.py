"""Synthetic issuer regressions; none of these fixtures is deployment evidence."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import platform_wire_exact_qualification as exact
from platform_wire_managed_fleet_profile import fixture as fleet_fixture
from platform_wire_retention_profile import fixture as retention_fixture

SOURCE, BASE, MERGE, TREE = "a" * 40, "b" * 40, "c" * 40, "d" * 40


class ExactEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.lane = "source-head"
        self.tested, self.parents = SOURCE, [BASE]
        self.merge_tree = TREE
        self.dirty = ""
        self.env = {
            "SOURCE_SHA": SOURCE,
            "TESTED_SHA": SOURCE,
            "BASE_SHA": BASE,
            "HEPTA_CI_LANE": "source-head",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_REPOSITORY": "fixture/repo",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_WORKFLOW_REF": "fixture/repo/.github/workflows/platform-wire-exact.yml@refs/pull/1/merge",
            "GITHUB_WORKFLOW_SHA": MERGE,
            "GITHUB_WORKFLOW": "fixture",
        }
        self.write_records()

    def git(self, *args):
        if args == ("rev-parse", "HEAD"):
            return self.tested
        if args[0] == "rev-parse":
            return TREE
        if args[0] == "show":
            return " ".join(self.parents)
        if args[0] == "merge-tree":
            return self.merge_tree
        if args[0] == "status":
            return self.dirty
        raise AssertionError(args)

    def write_records(self):
        identity = dict(
            commit=self.tested, tree=TREE, parents=self.parents, dirty=False
        )
        for name, floor, argv in exact.commands(self.root):
            log = f"test result: ok. {floor} passed; 0 failed; 0 ignored;\n".encode()
            (self.root / (name + ".log")).write_bytes(log)
            record = {
                "schema_version": 1,
                "status": "passed",
                "command": argv,
                "command_exit_code": 0,
                "exit_code": 0,
                "returncode": 0,
                "observed_failed_tests": 0,
                "observed_passed_tests": floor,
                "minimum_tests": floor,
                "timed_out": False,
                "output_limit_exceeded": False,
                "source_sha": SOURCE,
                "tested_sha": self.tested,
                "run_id": "123",
                "run_attempt": "2",
                "lane": self.env["HEPTA_CI_LANE"],
                "before": identity,
                "after": identity,
                "log_file": name + ".log",
                "log_bytes": len(log),
                "log_sha256": hashlib.sha256(log).hexdigest(),
            }
            (self.root / (name + ".json")).write_text(json.dumps(record))
        (self.root / "managed-fleet-profile.measurements.json").write_text(
            json.dumps(fleet_fixture(8))
        )
        (self.root / "retention.measurements.json").write_text(
            json.dumps(retention_fixture(32))
        )

    def issue(self, setup="success", execution="success"):
        with (
            patch.object(exact, "git", side_effect=self.git),
            patch.dict(exact.os.environ, self.env, clear=True),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = exact.receipt(self.root, SOURCE, BASE, self.lane, setup, execution)
        return status, json.loads((self.root / "receipt.json").read_text())

    def mutate(self, field, value, name="gateway"):
        path = self.root / (name + ".json")
        record = json.loads(path.read_text())
        record[field] = value
        path.write_text(json.dumps(record))

    def test_full_source_receipt_binds_all_commands_and_raw_profiles(self):
        status, receipt = self.issue()
        self.assertEqual(status, 0)
        self.assertEqual(
            len(receipt["command_records"]), len(exact.commands(self.root))
        )
        self.assertEqual(
            receipt["measurements"]["retention.measurements.json"]["scenario_count"], 18
        )
        for field in (
            "authenticated_network_ingress",
            "five_path_grpc_qualified",
            "independent_acceptance",
            "activation",
            "release",
        ):
            self.assertIs(receipt[field], False)
        hashes = json.loads((self.root / "SHA256SUMS.json").read_text())
        self.assertEqual(
            hashes["receipt.json"],
            hashlib.sha256((self.root / "receipt.json").read_bytes()).hexdigest(),
        )

    def test_ordered_merge_accepts_only_its_own_subject(self):
        self.lane, self.tested, self.parents = "synthetic-merge", MERGE, [BASE, SOURCE]
        self.env.update(TESTED_SHA=MERGE, HEPTA_CI_LANE="base-merge")
        self.write_records()
        status, receipt = self.issue()
        self.assertEqual(status, 0)
        self.assertEqual(receipt["tested_parents"], [BASE, SOURCE])
        self.assertEqual(receipt["execution_lane"], "base-merge")

    def test_reversed_merge_or_wrong_recomputed_tree_rejects(self):
        self.lane, self.tested = "synthetic-merge", MERGE
        self.env.update(TESTED_SHA=MERGE, HEPTA_CI_LANE="base-merge")
        for parents, tree in (([SOURCE, BASE], TREE), ([BASE, SOURCE], "e" * 40)):
            self.parents, self.merge_tree = parents, tree
            self.write_records()
            self.assertEqual(self.issue()[0], 1)

    def test_changed_command_or_weakened_floor_cannot_pass(self):
        for field, value in (("command", ["true"]), ("minimum_tests", 1)):
            self.write_records()
            self.mutate(field, value)
            self.assertEqual(self.issue()[0], 1)

    def test_same_source_previous_attempt_is_not_current_evidence(self):
        self.mutate("run_attempt", "1")
        self.assertEqual(self.issue()[0], 1)

    def test_invented_test_count_cannot_override_raw_log(self):
        self.mutate("observed_passed_tests", 900)
        self.assertEqual(self.issue()[0], 1)

    def test_mutated_log_or_missing_command_rejects(self):
        (self.root / "gateway.log").write_text(
            "test result: ok. 900 passed; 0 failed;\n"
        )
        self.assertEqual(self.issue()[0], 1)
        self.write_records()
        (self.root / "native-worker.json").unlink()
        self.assertEqual(self.issue()[0], 1)

    def test_boolean_exit_status_and_duplicate_json_keys_reject(self):
        self.mutate("exit_code", False)
        self.assertEqual(self.issue()[0], 1)
        self.write_records()
        path = self.root / "gateway.json"
        path.write_text(path.read_text()[:-1] + ',"status":"passed"}')
        self.assertEqual(self.issue()[0], 1)

    def test_measurement_missing_mutated_or_overclaiming_rejects(self):
        path = self.root / "retention.measurements.json"
        for bad in (None, {"schema": "wrong"}):
            if bad is None:
                path.unlink()
            else:
                path.write_text(json.dumps(bad))
            self.assertEqual(self.issue()[0], 1)
        report = retention_fixture(32)
        report["authenticated_network_ingress"] = True
        path.write_text(json.dumps(report))
        self.assertEqual(self.issue()[0], 1)

    def test_queued_cancelled_failed_setup_never_become_passes(self):
        for setup, execution in (
            ("failure", "skipped"),
            ("success", "cancelled"),
            ("success", "failure"),
        ):
            status, receipt = self.issue(setup, execution)
            self.assertEqual(status, 1)
            self.assertNotEqual(receipt["status"], "passed")

    def test_changed_workflow_subject_or_dirty_checkout_rejects(self):
        for field, value in (
            ("SOURCE_SHA", BASE),
            ("GITHUB_WORKFLOW_SHA", ""),
            ("GITHUB_WORKFLOW_REF", "fixture/other"),
            ("GITHUB_RUN_ID", "not-a-run"),
        ):
            old = self.env[field]
            self.env[field] = value
            self.assertEqual(self.issue()[0], 1)
            self.env[field] = old
        self.dirty = " M source.rs"
        self.assertEqual(self.issue()[0], 1)

    def test_measurement_symlink_and_duplicate_keys_reject(self):
        path = self.root / "retention.measurements.json"
        saved = path.read_text()
        path.unlink()
        path.symlink_to(self.root / "managed-fleet-profile.measurements.json")
        self.assertEqual(self.issue()[0], 1)
        path.unlink()
        path.write_text(saved[:-1] + ',"profile":"release"}')
        self.assertEqual(self.issue()[0], 1)


if __name__ == "__main__":
    unittest.main()
