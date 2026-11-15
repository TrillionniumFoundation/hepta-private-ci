"""Adversarial binding checks; all owners, events and effects here are fixtures."""

from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from .action_history import ActionEvent, encode
from .contracts import Evidence
from .native_ledger import Artifact, freeze_snapshot
from .observed_evaluation import UtilityContract
from .observed_history import history_model_row, summarize_history, summary_model_row
from .owner_bridge import freeze_owner_decision, join_owner_effect, owner_information_digest
from .test_observed_run import fixture_study


def fixture_history_study(root, *, train_actions=("a", "b"), epochs=3):
    """Extend retained fixture input via the actual freeze/join APIs, create-only."""
    old_path = fixture_study(root, train_actions=train_actions, epochs=epochs)
    root, old = old_path.parent, Artifact.read(old_path).payload
    contract = UtilityContract(**old["utility_contract"])
    entries = {"train": [], "dev": []}
    for index in range(18):
        before = Artifact.read(root / f"snapshot-{index}.json").payload
        d = Artifact.read(root / f"decision-{index}.json").payload
        original = Artifact.read(root / f"sample-{index}.json").payload
        observed = original["observed"]
        events = [ActionEvent(sequence=j, action_id=f"prior-{j}", candidate_id=f"prior-{j}",
                              action="a", stage="request", event_at=1. + j,
                              observed_at=1. + j, record_ref=f"fixture-prior-{index}-{j}")
                  for j in range(index % 3)]
        collection = before["collection"]
        collection["cursor"] = max(0, len(events) - 1)
        history = encode(events, actions=("a", "b"), decision_at=11.,
                         through_sequence=collection["cursor"], remaining_budget=index + 1., deadline_at=100.)
        snapshot_path = root / f"history-snapshot-{index}.json"
        snapshot = freeze_snapshot(snapshot_path, history, Artifact.make(collection))
        decision_path = root / f"history-decision-{index}.json"
        panel = {key: d["predictions"][key] for key in d["action_order"]}
        decision = freeze_owner_decision(
            decision_path, snapshot_path, predictions=panel, chosen_action=d["chosen_action"],
            policy_id=d["policy_id"], model_sha256=d["model_sha256"], task_group=d["task_group"],
            split=d["split"], information_set_digest=owner_information_digest(
                snapshot, d["action_order"], contract, d["success_definition"]),
            contract=contract, prediction_at=12., decision_at=13.,
            success_definition=d["success_definition"], source="fixture",
        )
        collection.update(cursor=collection["cursor"] + 1, available_at=40.)
        collection["rows"]["attempts"] = [{**before["identity"], "authority_epoch": 1,
            "grant_id": "fixture-grant", "grant_nonce_digest": "8" * 64,
            "record_command_id": "command", "started_at_ms": 1}]
        effect = Artifact.make({
            "schema": "pred1-independent-effect-v1", "target_domain": "independent_task_effect",
            "target_schema_sha256": d["target_schema_sha256"], "decision_digest": decision.digest,
            "snapshot_digest": snapshot.digest, "identity": before["identity"],
            "clock_id": before["clock_id"], "chosen_action": d["chosen_action"],
            "executed_action": d["chosen_action"], "executed_at": 14.,
            "execution_ref": observed["execution_ref"], "observer_ref": "fixture-observer",
            "evidence": observed["evidence"], "costs": observed["costs"],
            "full_wall_seconds": observed["full_wall_seconds"], "source": "fixture",
        })
        sample_path = root / f"history-sample-{index}.json"
        sample = join_owner_effect(sample_path, decision_path, Artifact.make(collection), effect)
        entries[d["split"]].append({key: {"path": path.name, "sha256": art.digest}
            for key, path, art in (("sample", sample_path, sample),
                                  ("decision", decision_path, decision),
                                  ("snapshot", snapshot_path, snapshot))})
    manifest = Artifact.make({**old, **entries, "action_ids": ["b", "a"],
                              "schema": "pred1-observed-history-study-v1"})
    path = root / "HISTORY_MANIFEST.json"
    manifest.save(path)
    return path


class ObservedHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        fixture_history_study(self.root)
        self.sample, self.decision, self.snapshot = [
            Artifact.read(self.root / f"history-{kind}-2.json")
            for kind in ("sample", "decision", "snapshot")]

    def test_full_frozen_history_and_censor_bounds_survive_without_rewriting(self):
        before = [a.encoded for a in (self.sample, self.decision, self.snapshot)]
        row = history_model_row(self.sample, self.decision, self.snapshot)
        self.assertEqual(row["history"], self.snapshot.payload["features"])
        self.assertEqual(len(row["history"]), 3)
        self.assertEqual(before, [a.encoded for a in (self.sample, self.decision, self.snapshot)])
        p = self.sample.payload
        p["observed"].update(evidence=asdict(Evidence(
            observation_status="verified_ongoing", time_kind="right_censored", time_lower=9.,
            observed_at=40., nonoccurrence_witness="fixture-coverage", confirmed_cost_lower_bound=.001)),
            costs=dict.fromkeys(p["observed"]["costs"]), full_wall_seconds=None)
        censored = history_model_row(Artifact.make(p), self.decision, self.snapshot)
        self.assertEqual(censored["evidence"]["time_lower"], 9.)
        self.assertEqual(censored["evidence"]["nonoccurrence_witness"], "fixture-coverage")
        self.assertIsNone(censored["duration_seconds"])
        self.assertIsNone(censored["action_cost"])

    def test_rehashed_wrong_snapshot_or_decision_cannot_supply_history(self):
        s = self.snapshot.payload
        s["features"][0][0] = 1. - s["features"][0][0]
        with self.assertRaisesRegex(ValueError, "snapshot binding"):
            history_model_row(self.sample, self.decision, Artifact.make(s))
        d = self.decision.payload
        d["prediction_at"] = 10.
        with self.assertRaisesRegex(ValueError, "decision binding"):
            history_model_row(self.sample, Artifact.make(d), self.snapshot)
        with self.assertRaises(ValueError):
            history_model_row(self.sample, self.decision, None)
        p = self.sample.payload
        p["observed"]["clock_id"] = "another-boot"
        with self.assertRaisesRegex(ValueError, "history clock"):
            history_model_row(Artifact.make(p), self.decision, self.snapshot)

    def test_coordinated_rehash_does_not_admit_late_history(self):
        s = self.snapshot.payload
        s["event_references"][0]["observed_at"] = 12.
        snap = Artifact.make(s)
        d = self.decision.payload
        d["snapshot_digest"] = snap.digest
        decision = Artifact.make(d)
        p = self.sample.payload
        p.update(snapshot_digest=snap.digest, decision_digest=decision.digest)
        p["observed"]["sample_id"] = decision.digest
        with self.assertRaisesRegex(ValueError, "event order or visibility"):
            history_model_row(Artifact.make(p), decision, snap)

    def test_fixed_summary_consumes_actual_history_and_retains_full_commitment(self):
        row = history_model_row(self.sample, self.decision, self.snapshot)
        features = self.snapshot.payload["feature_names"]
        summarized = summary_model_row(row, features)
        values, names = summarize_history(row["history"], features)
        self.assertEqual(summarized["history"], row["history"])
        self.assertEqual(summarized["features"], values)
        self.assertEqual(len(values), len(names))
        self.assertEqual(values[-1], 3 / 256)
        self.assertNotEqual(values, summarize_history(row["history"][-1:], features)[0])
        with self.assertRaises(ValueError):
            summarize_history(row["history"] * 100, features)


if __name__ == "__main__":
    unittest.main()
