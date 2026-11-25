"""Fixture-only effect joins; no live owner, native authorization or new labels."""

from copy import deepcopy
from dataclasses import asdict
import unittest

from . import test_owner_history_shadow as fixtures
from .contracts import Evidence
from .native_ledger import Artifact
from .observed_evaluation import COST_FIELDS, evaluate_observed, score_forecast
from .observed_policy import choose_fixed1
from .owner_bridge import model_row, observed_from_artifact
from .owner_shadow_calibration import (
    join_owner_shadow_effect,
    validate_owner_shadow_calibration,
)


class OwnerShadowCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.panel_fixture = fixtures.OwnerHistoryShadowTests("runTest")
        self.panel_fixture.setUp()
        self.addCleanup(self.panel_fixture.doCleanups)
        self.f = self.panel_fixture.f
        model, self.checkpoint, digest = self.f.checkpoint("empirical")
        panel = {
            a: model.predict(self.f.snapshot.payload["features"][-1], a)
            for a in model.metadata["action_ids"]
        }
        self.model_action = choose_fixed1(
            panel, self.f.contract, preparation_seconds=0, preparation_cost=0
        )["chosen_action"]
        self.action = "b" if self.model_action == "a" else "a"
        self.shadow = self.panel_fixture.predict(
            "empirical", self.checkpoint, digest, owner_action=self.action
        )
        self.shadow_path = self.f.root / "empirical-shadow.json"
        p, s = self.shadow.payload["owner_decision"], self.f.snapshot.payload
        self.expected = dict(
            expected_shadow_sha256=self.shadow.digest,
            expected_owner_action=self.action,
            expected_owner_policy_id="original-owner-policy",
            expected_task_group="shadow-fixture",
            expected_split="dev",
            expected_sha256=digest,
            expected_snapshot_sha256=self.f.snapshot.digest,
            expected_clock_id=s["clock_id"],
            expected_cursor=s["cursor"],
            contract=self.f.contract,
            expected_source="fixture",
        )
        c = s["collection"]
        c.update(cursor=s["cursor"] + 1, available_at=14.0)
        c["rows"]["attempts"] = [
            {
                **s["identity"],
                "authority_epoch": 1,
                "grant_id": "fixture-grant",
                "grant_nonce_digest": "8" * 64,
                "record_command_id": "fixture-command",
                "started_at_ms": 1,
            }
        ]
        self.collection = Artifact.make(c)
        costs = dict.fromkeys(COST_FIELDS, 0.0)
        costs.update(action=0.003, inference=0.004)
        self.effect = dict(
            schema="pred1-independent-effect-v1",
            target_domain="independent_task_effect",
            target_schema_sha256=p["target_schema_sha256"],
            decision_digest=self.shadow.payload["owner_decision_sha256"],
            snapshot_digest=self.f.snapshot.digest,
            identity=s["identity"],
            clock_id=s["clock_id"],
            chosen_action=self.action,
            executed_action=self.action,
            executed_at=12.5,
            execution_ref="fixture-execution",
            observer_ref="independent-fixture-observer",
            source="fixture",
            costs=costs,
            full_wall_seconds=3.0,
            evidence=asdict(
                Evidence(
                    observation_status="terminal",
                    outcome=1,
                    time_kind="exact",
                    time_lower=0.017,
                    observed_at=14.0,
                    final_cost=0.003,
                    receipt_ref="fixture-effect",
                )
            ),
        )

    def join(self, effect=None, collection=None, name="calibration.json", **changes):
        return join_owner_shadow_effect(
            self.f.root / name,
            self.shadow_path,
            self.f.snapshot_path,
            self.checkpoint,
            collection or self.collection,
            Artifact.make(self.effect if effect is None else effect),
            **{**self.expected, **changes},
        )

    def test_effect_joins_only_owner_action_and_never_exposes_policy_value(self):
        artifact = self.join()
        p = artifact.payload
        self.assertNotEqual(self.action, self.model_action)
        self.assertEqual(
            (p["owner_action"], p["executed_action"], p["owner_policy_id"]),
            (self.action, self.action, "original-owner-policy"),
        )
        forecast = self.shadow.payload["owner_decision"]["predictions"][self.action]
        self.assertEqual(
            p["forecast_scores"],
            score_forecast(forecast, Evidence(**self.effect["evidence"])),
        )
        self.assertEqual(p["costs"], self.effect["costs"])
        validate_owner_shadow_calibration(
            artifact,
            self.shadow_path,
            self.f.snapshot_path,
            self.checkpoint,
            self.collection,
            Artifact.make(self.effect),
            **self.expected,
        )
        for reader in (model_row, observed_from_artifact):
            with self.assertRaisesRegex(ValueError, "schema"):
                reader(artifact)
        with self.assertRaises(ValueError):
            evaluate_observed([artifact], self.f.contract)
        with self.assertRaises(FileExistsError):
            self.join()

    def test_unknown_cancellation_and_right_censoring_preserve_missingness(self):
        for status in (
            "receipt_missing",
            "awaiting",
            "cancel_requested",
            "verified_ongoing",
        ):
            effect = deepcopy(self.effect)
            evidence = dict(observation_status=status, observed_at=14.0)
            if status == "verified_ongoing":
                evidence.update(
                    time_kind="right_censored",
                    time_lower=1.0,
                    nonoccurrence_witness="fixture-nonoccurrence",
                )
            else:
                effect.update(
                    executed_action=None, executed_at=None, execution_ref=None
                )
            effect.update(
                evidence=asdict(Evidence(**evidence)),
                costs=dict.fromkeys(COST_FIELDS),
                full_wall_seconds=None,
            )
            p = self.join(effect, name=status + ".json").payload
            self.assertEqual(p["evidence"], effect["evidence"])
            self.assertEqual(
                (p["costs"], p["full_wall_seconds"]), (dict.fromkeys(COST_FIELDS), None)
            )
            if status == "verified_ongoing":
                self.assertEqual(
                    [
                        p["forecast_scores"][key]
                        for key in ("quality_brier", "duration_crps", "cost_crps")
                    ],
                    [None] * 3,
                )
            else:
                self.assertIsNone(p["forecast_scores"])

    def test_wrong_witness_action_clock_digest_cost_or_owner_are_refused(self):
        for key, value in (
            ("executed_action", self.model_action),
            ("clock_id", "other-boot"),
            ("decision_digest", self.shadow.digest),
            ("target_domain", "OWNER_SETTLEMENT"),
            ("full_wall_seconds", 0.0),
            ("costs", {**self.effect["costs"], "inference": 0.0}),
            ("identity", {**self.effect["identity"], "attempt": True}),
        ):
            effect = {**self.effect, key: value}
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.join(effect)
        collection = self.collection.payload
        collection["rows"]["attempts"][0]["attempt"] = True
        with self.assertRaises(ValueError):
            self.join(collection=Artifact.make(collection))
        with self.assertRaisesRegex(ValueError, "shadow bytes differ"):
            self.join(expected_shadow_sha256="f" * 64)
        self.assertFalse((self.f.root / "calibration.json").exists())

    def test_rehashed_scores_and_owner_identity_fail_full_replay(self):
        artifact = self.join()
        for key, value in (
            ("owner_action", self.model_action),
            ("owner_policy_id", "gru:history:Fixed1"),
            ("policy_value_allowed", True),
            ("forecast_scores", {"quality_brier": 0.0}),
            ("evidence", {**self.effect["evidence"], "outcome": 0}),
        ):
            p = {**artifact.payload, key: value}
            with (
                self.subTest(field=key),
                self.assertRaisesRegex(ValueError, "replay differs"),
            ):
                validate_owner_shadow_calibration(
                    Artifact.make(p),
                    self.shadow_path,
                    self.f.snapshot_path,
                    self.checkpoint,
                    self.collection,
                    Artifact.make(self.effect),
                    **self.expected,
                )
