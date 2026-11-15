"""Prospective binding checks with synthetic owner and observer artifacts."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .action_history import encode
from .contracts import Evidence
from .native_ledger import Artifact, ATTEMPT_FIELDS, IDENTITY_FIELDS, freeze_snapshot
from .observed_evaluation import COST_FIELDS, UtilityContract, score_observed
from .observed_models import fit_observed_model
from .owner_bridge import freeze_owner_decision, join_owner_effect, model_row, observed_from_artifact, owner_information_digest, predict_owner_choice


class OwnerBridgeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.identity = dict(zip(IDENTITY_FIELDS, ("owner", "run", "step", 1,
                             "1" * 64, "2" * 64, "3" * 64, "destination")))
        self.collection = Artifact.make({
            "schema": "pred1-native-collection-v1", "identity": self.identity,
            "clock_id": "fixture-clock", "cursor": 0, "available_at": 10.,
            "rows": {"attempts": [], "observations": [], "reconciliations": []},
            "database_path": "fixture", "scope": "fixture",
        })
        history = encode([], actions=("a", "b"), decision_at=11., through_sequence=0,
                         remaining_budget=10., deadline_at=20.)
        self.snapshot_path = self.root / "snapshot.json"
        self.snapshot = freeze_snapshot(self.snapshot_path, history, self.collection)
        self.prediction = dict(success_probability=.75, duration_values=[.01, .03],
                               duration_probabilities=[.5, .5], cost_values=[.003], cost_probabilities=[1.])
        self.contract = UtilityContract(cost_unit="fixture-resource", time_weight=.01, cost_weight=.1)
        self.options = dict(predictions={"a": self.prediction}, chosen_action="a", policy_id="Fixed1",
                            model_sha256="4" * 64, task_group="fixture-task", split="train",
                            information_set_digest=owner_information_digest(self.snapshot, ["a"], self.contract, "fixture success"), contract=self.contract,
                            prediction_at=11.9, decision_at=12., success_definition="fixture success", source="fixture")
        self.decision_path = self.root / "decision.json"
        self.decision = freeze_owner_decision(self.decision_path, self.snapshot_path, **self.options)
        later = self.collection.payload
        later.update(cursor=1, available_at=14.)
        attempt = {**self.identity, "authority_epoch": 1, "grant_id": "grant",
                   "grant_nonce_digest": "6" * 64, "record_command_id": "command", "started_at_ms": 1}
        self.assertEqual(set(attempt), set(ATTEMPT_FIELDS))
        later["rows"]["attempts"] = [attempt]
        self.later = Artifact.make(later)
        costs = dict.fromkeys(COST_FIELDS, 0.)
        costs["action"] = .003
        self.effect = {
            "schema": "pred1-independent-effect-v1", "target_domain": "independent_task_effect",
            "identity": self.identity, "decision_digest": self.decision.digest,
            "snapshot_digest": self.snapshot.digest, "clock_id": "fixture-clock",
            "target_schema_sha256": self.decision.payload["target_schema_sha256"],
            "chosen_action": "a", "executed_action": "a", "executed_at": 12.,
            "execution_ref": "fixture-execution", "observer_ref": "fixture-observer",
            "evidence": asdict(Evidence(observation_status="terminal", outcome=1, time_kind="exact",
                                       time_lower=.017, observed_at=14., final_cost=.003, receipt_ref="fixture-effect")),
            "costs": costs, "full_wall_seconds": 2.1, "source": "fixture",
        }

    def test_complete_join_preserves_continuous_readback_and_snapshot(self):
        before = self.snapshot_path.read_bytes(), self.decision_path.read_bytes()
        joined = join_owner_effect(self.root / "joined.json", self.decision_path, self.later, Artifact.make(self.effect))
        observed = observed_from_artifact(joined)
        row = model_row(joined)
        self.assertEqual(row["duration_seconds"], .017)
        self.assertEqual(row["action_cost"], .003)
        self.assertEqual(row["outcome_quality"], 1)
        self.assertEqual(row["features"], self.snapshot.payload["features"][-1])
        self.assertEqual(before, (self.snapshot_path.read_bytes(), self.decision_path.read_bytes()))
        self.assertFalse(joined.payload["source_provenance_authenticated"])
        score = score_observed(observed, self.contract)
        self.assertIsInstance(score, dict)

    def test_settlement_and_mismatched_binding_never_become_effect_labels(self):
        for name, value in (("target_domain", "OWNER_SETTLEMENT"), ("decision_digest", "f" * 64),
                            ("clock_id", "another-boot"), ("executed_action", "b"), ("executed_at", 11.),
                            ("target_schema_sha256", "f" * 64)):
            with self.subTest(field=name):
                effect = deepcopy(self.effect)
                effect[name] = value
                with self.assertRaises(ValueError):
                    join_owner_effect(self.root / "rejected.json", self.decision_path, self.later, Artifact.make(effect))
        self.assertFalse((self.root / "rejected.json").exists())

    def test_retrospective_dispatch_cannot_be_frozen_as_prospective(self):
        history = encode([], actions=("a",), decision_at=15., through_sequence=1,
                         remaining_budget=10., deadline_at=20.)
        freeze_snapshot(self.root / "late-snapshot.json", history, self.later)
        options = {**self.options, "prediction_at": 15., "decision_at": 16.}
        with self.assertRaises(ValueError):
            freeze_owner_decision(self.root / "late-decision.json", self.root / "late-snapshot.json", **options)

    def test_cancel_without_execution_stays_unknown_and_not_zero_label(self):
        effect = deepcopy(self.effect)
        effect.update(executed_action=None, executed_at=None, execution_ref=None,
                      evidence=asdict(Evidence(observation_status="cancel_requested", observed_at=14.)),
                      costs=dict.fromkeys(COST_FIELDS), full_wall_seconds=None)
        joined = join_owner_effect(self.root / "cancel.json", self.decision_path, self.later, Artifact.make(effect))
        row = model_row(joined)
        self.assertIsNone(row["outcome_quality"])
        self.assertIsNone(row["duration_seconds"])
        self.assertIsNone(row["action_cost"])
        self.assertEqual(row["outcome_status"], "cancel_requested")

    def test_false_same_information_and_understated_wall_are_rejected(self):
        with self.assertRaises(ValueError):
            freeze_owner_decision(self.root / "false-input.json", self.snapshot_path,
                                  **{**self.options, "information_set_digest": "f" * 64})
        effect = deepcopy(self.effect)
        effect.update(executed_at=13.5, full_wall_seconds=.017)
        with self.assertRaises(ValueError):
            join_owner_effect(self.root / "false-wall.json", self.decision_path, self.later, Artifact.make(effect))
        effect.update(executed_action=None, executed_at=None, execution_ref=None, full_wall_seconds=None,
                      costs=dict.fromkeys(COST_FIELDS),
                      evidence=asdict(Evidence(observation_status="verified_ongoing", time_kind="right_censored",
                                             time_lower=1., observed_at=14., nonoccurrence_witness="fixture-witness")))
        with self.assertRaises(ValueError):
            join_owner_effect(self.root / "no-origin.json", self.decision_path, self.later, Artifact.make(effect))

    def test_actual_checkpoint_panel_freezes_tie_order_and_inference_charge(self):
        rows = [{"sample_id": f"sample-{i}", "task_group": f"group-{i}", "split": "train",
                 "action_id": action, "features": self.snapshot.payload["features"][-1],
                 "outcome_quality": 1, "duration_seconds": .017, "action_cost": .003,
                 "outcome_status": "terminal", "time_status": "exact", "cost_status": "observed",
                 "source": "fixture"} for i, action in enumerate(("b", "a"))]
        model = fit_observed_model(rows, kind="empirical", feature_names=self.snapshot.payload["feature_names"],
                                   action_ids=["b", "a"], success_definition="fixture success", cost_unit=self.contract.cost_unit)
        checkpoint = self.root / "empirical.json"
        digest = model.save(checkpoint)
        before = self.snapshot_path.read_bytes()
        with patch(__package__ + ".owner_bridge.monotonic", side_effect=[11.2, 11.8, 12.]):
            artifact = predict_owner_choice(self.root / "predicted.json", self.snapshot_path, checkpoint,
                                            expected_sha256=digest, task_group="fixture-new", split="dev",
                                            contract=self.contract, inference_cost=.004)
        saved = Artifact.read(self.root / "predicted.json").payload
        self.assertEqual(saved["chosen_action"], "b")
        self.assertEqual(saved["action_order"], ["b", "a"])
        self.assertEqual(saved["inference_meter"]["head_calls"], 2)
        self.assertEqual(saved["inference_meter"]["declared_resource_cost"], .004)
        self.assertEqual(artifact.digest, Artifact.read(self.root / "predicted.json").digest)
        self.assertEqual(before, self.snapshot_path.read_bytes())
        with self.assertRaises(ValueError):
            freeze_owner_decision(self.root / "changed.json", self.snapshot_path,
                                  **self.options, expected_snapshot_sha256="f" * 64)


if __name__ == "__main__":
    unittest.main()
