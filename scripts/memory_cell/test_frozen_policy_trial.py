"""Actual journal/backup/replay operations with an explicit fixture reader."""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from frozen_memory_session import FrozenMemorySession, publish
from frozen_policy_audit import summarize
from frozen_policy_trial import ARMS, PROFILE, checked_catalog, freeze_all, replay_all
from experience_policy import INITIAL, PROFILE as POLICY_PROFILE
from native import Document, Question, digest
from test_frozen_memory_session import Reader, select


class FrozenPolicyTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        train = Document("train", "train-root", "train-scope", "s", "2023-12-01", "private calibration text")
        self.docs = (train,) + tuple(
            Document(f"test-{i}", f"root-{i}", f"scope-{i}", "s", "2024-01-01", f"event {i}")
            for i in range(8)
        )
        self.sources, self.policy = self.root / "sources.json", self.root / "policy.json"
        self.source_sha = publish(self.sources, [asdict(d) for d in self.docs])
        policy = dict(schema=POLICY_PROFILE, weights=[float(i)/10 for i in range(10)],
            initial=INITIAL, training_scopes=[train.scope], roots=[train.root], revision=2,
            source_digest=digest([asdict(train)]), reader_identity=Reader.identity,
            test_queries_consumed=False, production_accepted=False, write_seconds=0.1)
        self.policy_sha = publish(self.policy, policy)
        self.frozen = self.root / "frozen"
        self.catalog_sha = freeze_all(self.sources, self.policy, self.frozen,
            source_sha=self.source_sha, policy_sha=self.policy_sha, commit="a"*40)
        self.catalog = checked_catalog(self.frozen, self.catalog_sha)
        self.current = self.root / "withdrawals.json"
        self.current_sha = publish(self.current, [])

    def recorded(self):
        reader, items = Reader(), []
        for entry in self.catalog["snapshots"]:
            q = Question("task-"+entry["scope"], entry["scope"], entry["scope"], "Which event?", "2024-02-01")
            session = FrozenMemorySession(self.frozen / entry["directory"],
                                          expected_snapshot=entry["snapshot_sha"])
            value = session.answer(q, select, reader, withdrawals=lambda: set())
            items.append(dict(query=asdict(q), arm=entry["arm"],
                snapshot_sha=entry["snapshot_sha"], result_sha=value["result_sha256"]))
        path = self.root / "REPLAY.json"
        hashed = publish(path, dict(schema=PROFILE, catalog_sha=self.catalog_sha,
                                  complete=True, results=items))
        return reader, path, hashed

    def test_all_scopes_freeze_before_tasks_and_train_text_is_not_evidence(self):
        self.assertEqual(len(self.catalog["snapshots"]), 32)
        self.assertFalse(self.catalog["task_payload_consumed"])
        for entry in self.catalog["snapshots"]:
            session = FrozenMemorySession(self.frozen / entry["directory"],
                                          expected_snapshot=entry["snapshot_sha"])
            self.assertEqual({d.scope for d in session.documents}, {entry["scope"]})
            self.assertIn("train-root", session.roots)
            self.assertNotIn("private calibration text", (session.directory / "snapshot.json").read_text())
            self.assertEqual(list(session.directory.glob("*.started.json")), [])

    def test_old_backup_replays_without_model_then_current_revocation_blocks(self):
        reader, path, hashed = self.recorded()
        backup = self.root / "backup"
        shutil.copytree(self.frozen, backup)
        replay_all(backup, path, self.root / "reopened.json", catalog_sha=self.catalog_sha,
            receipt_sha=hashed, withdrawal_path=self.current, withdrawal_sha=self.current_sha)
        result = json.loads((self.root / "reopened.json").read_text())
        self.assertEqual([r["status"] for r in result["results"]], ["replayed"]*32)
        self.assertEqual(result["model_calls"], 0)
        current = self.root / "new-current.json"
        current_sha = publish(current, ["train-root"])
        replay_all(backup, path, self.root / "denied.json", catalog_sha=self.catalog_sha,
            receipt_sha=hashed, withdrawal_path=current, withdrawal_sha=current_sha)
        result = json.loads((self.root / "denied.json").read_text())
        self.assertEqual([r["status"] for r in result["results"]], ["withdrawn"]*32)
        self.assertEqual(reader.calls, 32)
        self.assertFalse(result["production_accepted"])

    def test_changed_control_pin_and_incomplete_census_are_errors_not_withdrawals(self):
        _, path, hashed = self.recorded()
        with self.assertRaises(ValueError):
            replay_all(self.frozen, path, self.root / "wrong.json", catalog_sha=self.catalog_sha,
                receipt_sha=hashed, withdrawal_path=self.current, withdrawal_sha="0"*64)
        value = json.loads(path.read_text())
        value["results"].pop()
        bad = self.root / "bad.json"
        bad_sha = publish(bad, value)
        with self.assertRaises(ValueError):
            replay_all(self.frozen, bad, self.root / "incomplete.json", catalog_sha=self.catalog_sha,
                receipt_sha=bad_sha, withdrawal_path=self.current, withdrawal_sha=self.current_sha)
        self.assertFalse((self.root / "incomplete.json").exists())

    def test_duplicate_or_unsafe_catalogue_entries_reject(self):
        value = copy.deepcopy(self.catalog)
        for replacement in (value["snapshots"][1], value["snapshots"][0] | {"directory": "../escape"}):
            bad = copy.deepcopy(value)
            bad["snapshots"][0] = replacement
            (self.frozen / "CATALOG.json").write_text(json.dumps(bad))
            hashed = hashlib.sha256((self.frozen / "CATALOG.json").read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                checked_catalog(self.frozen, hashed)


def observations():
    return [dict(question_id=q, arm=a, kind="new_fact", candidate_digest="same-pool",
                 status="succeeded", strict_task_success=(a == "organized"),
                 selected=[a], receipt=dict(reader_identity="reader", reader_profile="fixed",
                    input_tokens=10, generated_tokens=2, seconds=0.1),
                 session_record=dict(query_train_tokens=0))
            for q in ("q1", "q2") for a in ARMS]


class FrozenPolicyAuditTests(unittest.TestCase):
    def test_beating_initialization_is_not_beating_organization(self):
        rows = observations()
        for row in rows:
            if row["arm"] == "learned" and row["question_id"] == "q1":
                row["strict_task_success"] = True
        report = summarize(rows, ["q1", "q2"])
        self.assertEqual(report["contrasts"]["initial"]["paired_wins"], 1)
        self.assertEqual(report["contrasts"]["organized"]["paired_losses"], 1)
        self.assertEqual(report["arms"]["learned"]["strict_successes"], 1)
        self.assertFalse(report["production_accepted"])

    def test_missing_failures_drift_and_invalid_counters_cannot_make_a_gain(self):
        rows = observations()
        with self.assertRaises(ValueError):
            summarize(rows[:-1], ["q1", "q2"])
        for name, value in (("input_tokens", True), ("seconds", float("nan")),
                            ("reader_profile", "changed")):
            bad = copy.deepcopy(rows)
            bad[0]["receipt"][name] = value
            with self.assertRaises(ValueError):
                summarize(bad, ["q1", "q2"])
        bad = copy.deepcopy(rows)
        bad[3] = dict(question_id="q1", arm="learned", kind="new_fact",
                      candidate_digest="same-pool", status="failed")
        report = summarize(bad, ["q1", "q2"])
        self.assertEqual(report["arms"]["learned"]["planned"], 2)
        self.assertEqual(report["contrasts"]["hybrid"]["missing_pairs"], 1)
        self.assertEqual(report["contrasts"]["hybrid"]["all_planned_delta_bounds"], [-0.5, 0.5])


if __name__ == "__main__":
    unittest.main()
