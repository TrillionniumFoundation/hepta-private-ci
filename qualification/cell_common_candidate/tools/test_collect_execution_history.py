import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import collect_execution_history as history


class ExecutionHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "records"
        self.root.mkdir()

    def receipt(self, name, status="passed", source="a" * 40, start="2026-11-08T10:00:00+00:00",
                end="2026-11-08T10:01:00+00:00", body=b"Ran 1 test in 0.001s\n\nOK\n"):
        identity = {"commit": source, "tree": "b" * 40, "dirty": False}
        log = Path(name).name + ".log"
        (self.root / Path(name).parent / log).write_bytes(body)
        value = {"schema_version": 1, "lane": "source-head", "source_sha": source,
                 "tested_sha": source, "before": identity, "after": identity,
                 "command": ["python3", "-m", "unittest"], "status": status,
                 "started_at": start, "finished_at": end, "elapsed_seconds": 60.0,
                 "command_exit_code": 0, "exit_code": 0, "observed_passed_tests": 1,
                 "observed_failed_tests": 0, "log_file": log,
                 "log_sha256": hashlib.sha256(body).hexdigest()}
        (self.root / name).write_text(json.dumps(value))
        return value

    def collect(self, required=()):
        return history.collect(self.root, self.root / "history-checkpoint" / "first",
                               required=required, settle_seconds=0)

    def test_success_failure_and_preflight_rejection_are_retained_exactly(self):
        self.receipt("pass.json")
        failed = self.receipt("compile.json", status="failed", body=b"error: could not compile example\n")
        failed.update(command=["just", "test"], command_exit_code=101, exit_code=101,
                      observed_passed_tests=0)
        (self.root / "compile.json").write_text(json.dumps(failed))
        rejected = self.receipt("rejected.json", status="rejected")
        rejected.update(source_sha="", tested_sha="", command_exit_code=None,
                        exit_code=2, error="SOURCE_SHA required")
        for key in ("after", "log_file", "log_sha256", "observed_passed_tests", "observed_failed_tests"):
            rejected.pop(key)
        (self.root / "rejected.json").write_text(json.dumps(rejected))
        result = self.collect(required=["pass.json", "compile.json", "rejected.json"])
        self.assertEqual(result["status_counts"], {"failed": 1, "passed": 1, "rejected": 1})
        self.assertEqual(result["required_receipts_missing"], [])
        events = {event["receipt"]: event for event in result["events"]}
        self.assertEqual(events["compile.json"]["activity"]["classification"],
                         "compilation_failure_before_observed_tests")
        self.assertEqual(events["rejected.json"]["source"]["scope"], "preflight_observation_only")
        archive = self.root / "history-checkpoint/first/execution-evidence.tar.gz"
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                self.assertTrue(member.isfile())
                self.assertEqual(member.mode, 0o444)
                self.assertEqual(tar.extractfile(member).read(),
                                 (self.root / member.name.removeprefix("original/")).read_bytes())

    def test_running_mismatched_and_escaping_logs_do_not_enter_archive(self):
        self.receipt("running.json", status="running")
        self.receipt("mismatch.json")
        (self.root / "mismatch.json.log").write_bytes(b"different bytes")
        escape = self.receipt("escape.json")
        escape["log_file"] = "../outside.log"
        (self.root / "escape.json").write_text(json.dumps(escape))
        self.receipt("symlink.json")
        (self.root / "symlink.json.log").unlink()
        (self.root / "symlink.json.log").symlink_to(self.root / "mismatch.json.log")
        result = self.collect(required=["running.json"])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["files"], [])
        self.assertEqual(result["required_receipts_missing"], ["running.json"])
        self.assertTrue(all(name in {entry["path"] for entry in result["excluded"]}
                            for name in ("running.json", "mismatch.json", "escape.json", "symlink.json")))

    def test_changed_log_on_second_pass_discards_its_entire_event(self):
        self.receipt("changing.json")
        original = history.SnapshotReader.read
        seen = 0

        def changed(reader, name, limit=history.MAX_FILE):
            nonlocal seen
            if name == "changing.json.log":
                seen += 1
                if seen == 2:
                    (self.root / name).write_bytes(b"writer resumed\n")
            return original(reader, name, limit)

        with patch.object(history.SnapshotReader, "read", changed):
            result = self.collect()
        self.assertEqual(result["events"], [])
        self.assertEqual(result["files"], [])
        self.assertTrue(any("unstable" in entry["reason"] for entry in result["excluded"]))

    def test_different_sources_overlap_without_cost_or_time_inference(self):
        self.receipt("first.json", source="c" * 40, end="2026-11-08T10:02:00+00:00")
        self.receipt("second.json", source="d" * 40, start="2026-11-08T10:01:00+00:00",
                     end="2026-11-08T10:03:00+00:00")
        log = b"Finished dependency update\n"
        (self.root / "legacy.log").write_bytes(log)
        (self.root / "legacy.json").write_text(json.dumps({
            "argv": ["cargo", "update"], "cwd": "/unknown", "head": "e" * 40,
            "finished_utc": "unknown", "exit_code": 0, "log_sha256": hashlib.sha256(log).hexdigest()}))
        result = self.collect()
        self.assertEqual(result["source_commits_as_recorded"], ["c" * 40, "d" * 40, "e" * 40])
        self.assertEqual(len(result["overlapping_intervals"]), 1)
        legacy = next(event for event in result["events"] if event["receipt"] == "legacy.json")
        self.assertEqual(legacy["activity"]["classification"], "dependency_preparation")
        self.assertFalse(legacy["time"]["interval_known"])
        self.assertIsNone(legacy["time"]["elapsed_seconds_as_reported"])
        for key in ("physical_cost", "full_history_cost", "command_wall_sum_seconds", "cpu_seconds", "learning_cost"):
            self.assertIsNone(result[key])
        self.assertFalse(result["complete_execution_history"])
        self.assertFalse(result["final_candidate_pass"])

    def test_nested_output_does_not_hide_sibling_failed_history(self):
        (self.root / "group").mkdir()
        self.receipt("group/old-failure.json", status="failed")
        result = history.collect(self.root, self.root / "group/new-output", settle_seconds=0)
        self.assertEqual([event["receipt"] for event in result["events"]], ["group/old-failure.json"])

    def test_source_conflicts_stay_in_history_with_unknown_identity_scope(self):
        for name, change in [
            ("bad-shape.json", lambda value: value["before"].update(commit="bad", tree="bad")),
            ("declared-mismatch.json", lambda value: value.update(tested_sha="e" * 40)),
            ("dirty-conflict.json", lambda value: value["before"].update(dirty_porcelain=" M source.rs")),
        ]:
            value = self.receipt(name)
            change(value)
            value["elapsed_seconds"] = 10 ** 400
            (self.root / name).write_text(json.dumps(value))
        result = self.collect()
        self.assertEqual(len(result["events"]), 3)
        for event in result["events"]:
            self.assertEqual(event["source"]["scope"], "partial_or_unknown")
            self.assertIsNone(event["time"]["elapsed_seconds_as_reported"])
        self.assertNotIn("stage_status", result)
        self.assertEqual(result["qualification_evaluation"], "not_performed_by_collector")

    def test_explicit_external_pair_keeps_its_root_and_marks_missing_receipt_hash(self):
        external = self.root.parent / "external"
        external.mkdir()
        receipt, log = external / "completed.json", external / "completed.log"
        receipt.write_text(json.dumps({"argv": ["bazel", "mod", "deps"], "head": "e" * 40,
                                       "exit_code": 0, "finished_utc": "unknown"}))
        log.write_bytes(b"original dependency output\n")
        result = history.collect(self.root, self.root / "out", settle_seconds=0,
                                 external_pairs=[(receipt, log)])
        event = result["events"][0]
        self.assertEqual(event["record_root"], str(external))
        self.assertFalse(event["receipt_log_hash_verified"])
        self.assertEqual(event["log_linkage"], "explicit_pair_observed_hash_only_not_bound_by_receipt")
        self.assertEqual(event["activity"]["classification"], "dependency_preparation")
        self.assertFalse(event["time"]["interval_known"])
        with self.assertRaisesRegex(ValueError, "absolute sibling paths"):
            history.collect(self.root, self.root / "out-other", settle_seconds=0,
                            external_pairs=[(receipt, self.root / "outside.log")])

    def test_merge_parent_order_is_not_normalized_away(self):
        source, base, merged = "a" * 40, "b" * 40, "c" * 40
        identity = {"commit": merged, "tree": "d" * 40, "dirty": False, "parents": [source, base]}
        value = {"before": identity, "after": identity, "lane": "base-merge",
                 "source_sha": source, "base_sha": base, "tested_sha": merged}
        self.assertEqual(history.normalized_source(value, False)["scope"], "partial_or_unknown")
        identity["parents"] = [base, source]
        self.assertEqual(history.normalized_source(value, False)["scope"], "recorded_source_identity")


if __name__ == "__main__":
    unittest.main()
