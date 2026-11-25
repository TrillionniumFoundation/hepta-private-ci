"""Synthetic checkpoint/owner fixtures, never live calibration evidence."""

from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from . import test_owner_history_predict as fixtures
from .native_ledger import Artifact
from .observed_evaluation import UtilityContract
from .observed_history import summarize_history
from .observed_models import _canonical, _digest
from .observed_policy import choose_fixed1
from .owner_bridge import model_row, observed_from_artifact
from .owner_history_shadow import (
    predict_owner_history_shadow,
    validate_owner_history_shadow,
)


class OwnerHistoryShadowTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.OwnerHistoryPredictTests("runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.options = dict(
            owner_action="b",
            owner_policy_id="original-owner-policy",
            expected_snapshot_sha256=self.f.snapshot.digest,
            expected_clock_id=self.f.snapshot.payload["clock_id"],
            expected_cursor=self.f.snapshot.payload["cursor"],
            expected_budget_contract_digest=self.f.contract.digest,
            task_group="shadow-fixture",
            split="dev",
            contract=self.f.contract,
            inference_cost=0.004,
            source="fixture",
        )

    def predict(self, kind, path, digest, **changes):
        options = {**self.options, **changes}
        with (
            patch(
                __package__ + ".owner_history_shadow.monotonic",
                side_effect=[11.2, 11.8, 12.0],
            ),
            patch(
                __package__ + ".observed_policy.choose_fixed1",
                side_effect=AssertionError("must not choose"),
            ),
        ):
            return predict_owner_history_shadow(
                self.f.root / (kind + "-shadow.json"),
                self.f.snapshot_path,
                path,
                model_kind=kind,
                expected_sha256=digest,
                **options,
            )

    def validate(self, artifact, path, digest, **changes):
        options = {
            key: self.options[key]
            for key in (
                "expected_snapshot_sha256",
                "expected_clock_id",
                "expected_cursor",
                "contract",
            )
        }
        options.update(
            expected_owner_action=self.options["owner_action"],
            expected_owner_policy_id=self.options["owner_policy_id"],
            expected_task_group=self.options["task_group"],
            expected_split=self.options["split"],
            expected_sha256=digest,
            expected_source="fixture",
        )
        return validate_owner_history_shadow(
            artifact, self.f.snapshot_path, path, **{**options, **changes}
        )

    def test_panel_keeps_owner_action_policy_and_rejects_policy_value_readers(self):
        for kind in ("empirical", "mlp", "gru"):
            with self.subTest(kind=kind):
                model, path, digest = self.f.checkpoint(kind)
                history = self.f.snapshot.payload["features"]
                features = history if kind == "gru" else history[-1]
                if kind == "mlp":
                    features = summarize_history(
                        history, self.f.arguments["feature_names"]
                    )[0]
                predictions = {
                    a: model.predict(features, a) for a in model.metadata["action_ids"]
                }
                chosen = choose_fixed1(
                    predictions,
                    self.f.contract,
                    preparation_seconds=0,
                    preparation_cost=0,
                )["chosen_action"]
                owner_action = "b" if chosen == "a" else "a"
                artifact = self.predict(kind, path, digest, owner_action=owner_action)
                p = artifact.payload
                self.assertEqual(
                    (p["owner_action"], p["owner_policy_id"], p["model_sha256"]),
                    (owner_action, "original-owner-policy", digest),
                )
                self.assertEqual(p["owner_decision"]["predictions"], predictions)
                self.validate(
                    artifact, path, digest, expected_owner_action=owner_action
                )
                for reader in (model_row, observed_from_artifact):
                    with self.assertRaisesRegex(ValueError, "schema"):
                        reader(artifact)

    def test_bad_owner_clock_budget_and_checkpoint_schema_fail_before_publication(self):
        _, path, digest = self.f.checkpoint("empirical")
        capped = UtilityContract(
            cost_unit=self.f.contract.cost_unit,
            time_weight=0,
            cost_weight=0,
            max_total_cost=0.001,
        )
        for changes in (
            {"owner_action": "absent"},
            {"expected_clock_id": "other-boot"},
            {"expected_budget_contract_digest": "f" * 64},
            {"contract": capped, "expected_budget_contract_digest": capped.digest},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.predict("empirical", path, digest, **changes)
        envelope = json.loads(path.read_bytes())
        envelope["payload"]["metadata"]["feature_encoding"] = "wrong-schema"
        envelope["payload_sha256"] = _digest(envelope["payload"])
        encoded = _canonical(envelope)
        path.write_bytes(encoded)
        with self.assertRaisesRegex(ValueError, "schema"):
            self.predict("empirical", path, sha256(encoded).hexdigest())
        self.assertFalse((self.f.root / "empirical-shadow.json").exists())

    def test_rehashed_tampering_is_rejected_by_replay_not_only_flags(self):
        _, path, digest = self.f.checkpoint("empirical")
        artifact = self.predict("empirical", path, digest)
        for route, value in (
            (("policy_value_allowed",), True),
            (("schema",), "pred1-observed-owner-effect-v1"),
            (("owner_decision", "predictions", "a", "success_probability"), 0.123456),
            (("owner_decision", "inference_meter", "candidate_prediction_calls"), 0),
            (("owner_decision", "inference_meter", "started_at"), 13.0),
            (("owner_decision", "policy_id"), "gru:history:Fixed1"),
            (("owner_decision", "task_group"), "another-task"),
            (("owner_decision", "split"), "confirm"),
        ):
            p = artifact.payload
            target = p
            for key in route[:-1]:
                target = target[key]
            target[route[-1]] = value
            p["owner_decision_sha256"] = Artifact.make(p["owner_decision"]).digest
            with self.subTest(route=route), self.assertRaises(ValueError):
                self.validate(Artifact.make(p), path, digest)
        p = artifact.payload
        p["owner_action"] = p["owner_decision"]["chosen_action"] = "a"
        p["owner_decision_sha256"] = Artifact.make(p["owner_decision"]).digest
        with self.assertRaisesRegex(ValueError, "binding differs"):
            self.validate(Artifact.make(p), path, digest)
