"""Typed prospective preparation on synthetic owner histories and effect rows."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .contracts import Evidence
from .native_ledger import Artifact
from .observed_evaluation import COST_FIELDS, UtilityContract
from .observed_gru import ObservedGRU, fit_observed_gru
from .observed_history import history_model_row, summarize_history, summary_model_row
from .observed_models import ObservedModel, _canonical, _digest, fit_observed_model
from .observed_policy import choose_fixed1
from .owner_bridge import freeze_owner_decision, join_owner_effect
from .owner_history_predict import SOURCE_FILES, predict_owner_history_choice
from .test_observed_history import fixture_history_study


class OwnerHistoryPredictTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        manifest_path = fixture_history_study(self.root / "inputs", epochs=2)
        self.manifest = Artifact.read(manifest_path).payload
        self.inputs = manifest_path.parent
        self.contract = UtilityContract(**self.manifest["utility_contract"])
        self.rows = [
            history_model_row(
                **{
                    name: Artifact.read(self.inputs / entry[name]["path"])
                    for name in ("sample", "decision", "snapshot")
                }
            )
            for entry in self.manifest["train"]
        ]
        self.snapshot_path = self.inputs / self.manifest["dev"][2]["snapshot"]["path"]
        self.snapshot = Artifact.read(self.snapshot_path)
        self.arguments = {
            "feature_names": self.manifest["feature_names"],
            "action_ids": self.manifest["action_ids"],
            "success_definition": self.manifest["success_definition"],
            "cost_unit": self.contract.cost_unit,
            "hidden_size": 3,
            "epochs": 2,
        }

    def checkpoint(self, kind, name=None):
        arguments = self.arguments
        if kind == "gru":
            model = fit_observed_gru(self.rows, **arguments)
        elif kind == "mlp":
            names = summarize_history(
                self.rows[0]["history"], arguments["feature_names"]
            )[1]
            rows = [
                summary_model_row(row, arguments["feature_names"]) for row in self.rows
            ]
            model = fit_observed_model(
                rows,
                kind=kind,
                **{**arguments, "feature_names": names},
                feature_encoding="history_last_mean_length_v1",
            )
        else:
            model = fit_observed_model(self.rows, kind=kind, **arguments)
        path = self.root / (name or kind + ".json")
        return model, path, model.save(path)

    def predict(self, kind, checkpoint, digest, name="prospective.json", **changes):
        options = {
            "model_kind": kind,
            "expected_sha256": digest,
            "expected_snapshot_sha256": self.snapshot.digest,
            "expected_clock_id": self.snapshot.payload["clock_id"],
            "expected_cursor": self.snapshot.payload["cursor"],
            "task_group": "new-fixture",
            "split": "dev",
            "contract": self.contract,
            "inference_cost": 0.004,
        }
        options.update(changes)
        with patch(
            __package__ + ".owner_history_predict.monotonic",
            side_effect=[11.2, 11.8, 12.0],
        ):
            return predict_owner_history_choice(
                self.root / name, self.snapshot_path, checkpoint, **options
            )

    def test_all_checkpoint_types_match_direct_inference_and_freeze_full_binding(self):
        original = self.snapshot_path.read_bytes()
        for kind in ("empirical", "mlp", "gru"):
            with self.subTest(kind=kind):
                model, checkpoint, digest = self.checkpoint(kind)
                history = self.snapshot.payload["features"]
                features = history if kind == "gru" else history[-1]
                if kind == "mlp":
                    features = summarize_history(
                        history, self.arguments["feature_names"]
                    )[0]
                loader = ObservedGRU if kind == "gru" else ObservedModel
                restored = loader.load(checkpoint, expected_sha256=digest)
                predictions = {
                    a: restored.predict(features, a)
                    for a in model.metadata["action_ids"]
                }
                self.assertEqual(
                    predictions, {a: model.predict(features, a) for a in predictions}
                )
                artifact = self.predict(
                    kind, checkpoint, digest, name=kind + "-decision.json"
                )
                p = artifact.payload
                self.assertEqual(p["predictions"], predictions)
                choice = choose_fixed1(
                    predictions,
                    self.contract,
                    preparation_seconds=0.0,
                    preparation_cost=0.004,
                )
                self.assertEqual(p["chosen_action"], choice["chosen_action"])
                self.assertEqual(p["action_order"], model.metadata["action_ids"])
                self.assertEqual(
                    (p["snapshot_digest"], p["snapshot_cursor"], p["clock_id"]),
                    (
                        self.snapshot.digest,
                        self.snapshot.payload["cursor"],
                        self.snapshot.payload["clock_id"],
                    ),
                )
                meter = p["inference_meter"]
                self.assertEqual(meter["candidate_prediction_calls"], 2)
                self.assertEqual(meter["checkpoint_validation_prediction_calls"], 2)
                self.assertEqual(
                    meter["recurrent_steps"],
                    2 * (len(history) + 1) if kind == "gru" else 0,
                )
                self.assertEqual(
                    meter["neural_forward_calls"], 0 if kind == "empirical" else 4
                )
                self.assertEqual(set(meter["source_sha256"]), set(SOURCE_FILES))
                self.assertFalse(meter["physical_cost_complete"])
                self.assertIsNone(meter["observed_policy_gain"])
        self.assertEqual(self.snapshot_path.read_bytes(), original)

    def test_new_choice_joins_only_separate_fixture_dispatch_and_effect(self):
        _, checkpoint, digest = self.checkpoint("gru")
        decision = self.predict("gru", checkpoint, digest)
        p, s = decision.payload, self.snapshot.payload
        collection = s["collection"]
        collection.update(cursor=s["cursor"] + 1, available_at=14.0)
        collection["rows"]["attempts"] = [
            {
                **s["identity"],
                "authority_epoch": 1,
                "grant_id": "fixture-grant",
                "grant_nonce_digest": "8" * 64,
                "record_command_id": "fixture-command",
                "started_at_ms": 1,
            }
        ]
        costs = dict.fromkeys(COST_FIELDS, 0.0)
        costs.update(action=0.003, inference=0.004)
        effect = Artifact.make(
            {
                "schema": "pred1-independent-effect-v1",
                "target_domain": "independent_task_effect",
                "target_schema_sha256": p["target_schema_sha256"],
                "decision_digest": decision.digest,
                "snapshot_digest": self.snapshot.digest,
                "identity": s["identity"],
                "clock_id": s["clock_id"],
                "chosen_action": p["chosen_action"],
                "executed_action": p["chosen_action"],
                "executed_at": 12.5,
                "execution_ref": "new-fixture-dispatch",
                "observer_ref": "independent-fixture-observer",
                "evidence": asdict(
                    Evidence(
                        observation_status="terminal",
                        outcome=1,
                        time_kind="exact",
                        time_lower=0.017,
                        observed_at=14.0,
                        final_cost=0.003,
                        receipt_ref="new-fixture-effect",
                    )
                ),
                "costs": costs,
                "full_wall_seconds": 3.0,
                "source": "fixture",
            }
        )
        joined = join_owner_effect(
            self.root / "joined.json",
            self.root / "prospective.json",
            Artifact.make(collection),
            effect,
        )
        row = history_model_row(joined, decision, self.snapshot)
        self.assertEqual(
            (row["history"], row["action_id"], row["duration_seconds"]),
            (s["features"], p["chosen_action"], 0.017),
        )
        self.assertEqual(row["history_binding"]["decision_sha256"], decision.digest)
        self.assertFalse(joined.payload["source_provenance_authenticated"])

    def test_rehashed_malformed_metadata_and_explicit_wrong_kind_are_refused(self):
        _, checkpoint, digest = self.checkpoint("mlp")
        with self.assertRaisesRegex(ValueError, "kind differs"):
            self.predict("empirical", checkpoint, digest)
        original = json.loads(checkpoint.read_bytes())
        for index, (field, value) in enumerate(
            (
                ("feature_encoding", "last_observed_row"),
                ("duration_unit", "milliseconds"),
                ("success_definition", ""),
            )
        ):
            envelope = json.loads(_canonical(original))
            envelope["payload"]["metadata"][field] = value
            envelope["payload_sha256"] = _digest(envelope["payload"])
            encoded = _canonical(envelope)
            malformed = self.root / f"malformed-{index}.json"
            malformed.write_bytes(encoded)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.predict("mlp", malformed, sha256(encoded).hexdigest())
        self.assertFalse((self.root / "prospective.json").exists())

    def test_wrong_snapshot_clock_cursor_and_unsupported_panel_are_refused(self):
        _, checkpoint, digest = self.checkpoint("empirical")
        for changes in (
            {"expected_snapshot_sha256": "f" * 64},
            {"expected_clock_id": "another-boot"},
            {"expected_cursor": self.snapshot.payload["cursor"] + 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.predict("empirical", checkpoint, digest, **changes)
        partial = fit_observed_model(
            [r for r in self.rows if r["action_id"] == "a"],
            kind="empirical",
            **self.arguments,
        )
        path = self.root / "unsupported.json"
        with self.assertRaisesRegex(ValueError, "unsupported actions"):
            self.predict("empirical", path, partial.save(path))
        self.assertFalse((self.root / "prospective.json").exists())

    def test_snapshot_replacement_between_forecast_and_freeze_is_refused(self):
        _, checkpoint, digest = self.checkpoint("gru")

        def swap_snapshot(*args, **kwargs):
            s = self.snapshot.payload
            s["cursor"] += 1
            s["collection"]["cursor"] += 1
            s["collection_digest"] = Artifact.make(s["collection"]).digest
            self.snapshot_path.write_bytes(Artifact.make(s).encoded)
            return freeze_owner_decision(*args, **kwargs)

        with patch(
            __package__ + ".owner_history_predict.freeze_owner_decision",
            side_effect=swap_snapshot,
        ):
            with self.assertRaisesRegex(ValueError, "snapshot bytes changed"):
                self.predict("gru", checkpoint, digest)
        self.assertFalse((self.root / "prospective.json").exists())

    def test_changed_inference_source_is_refused_before_freezing_choice(self):
        _, checkpoint, digest = self.checkpoint("gru")
        original_read, original_predict = Path.read_bytes, ObservedGRU.predict
        calls = []

        def counted_predict(model, history, action):
            calls.append(len(history))
            return original_predict(model, history, action)

        def changed_read(path):
            encoded = original_read(path)
            if path.name == "owner_history_predict.py" and len(calls) >= 4:
                return encoded + b"\n# simulated source drift\n"
            return encoded

        with (
            patch.object(ObservedGRU, "predict", counted_predict),
            patch.object(Path, "read_bytes", changed_read),
        ):
            with self.assertRaisesRegex(ValueError, "inference source changed"):
                self.predict("gru", checkpoint, digest)
        self.assertEqual(
            calls,
            [
                1,
                1,
                len(self.snapshot.payload["features"]),
                len(self.snapshot.payload["features"]),
            ],
        )
        self.assertFalse((self.root / "prospective.json").exists())


if __name__ == "__main__":
    unittest.main()
