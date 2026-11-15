"""Wiring checks with synthetic snapshots and randomly initialized models."""

import copy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

from .action_history import ActionEvent, encode
from .contracts import JOINT_SUPPORT
from .crossed_training_fit import model_digest
from .models import KINDS, Model, softmax
from .native_ledger import Artifact, IDENTITY_FIELDS, freeze_snapshot, join_readback
from .shadow_model import ENCODING, feature_schema_digest, shadow_predict


class ShadowModelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.identity = dict(
            zip(
                IDENTITY_FIELDS,
                (
                    "fixture-owner",
                    "fixture-run",
                    "fixture-step",
                    1,
                    "1" * 64,
                    "2" * 64,
                    "3" * 64,
                    "fixture-destination",
                ),
            )
        )
        self.collection = Artifact.make(
            {
                "schema": "pred1-native-collection-v1",
                "identity": self.identity,
                "clock_id": "fixture-clock",
                "available_at": 10.0,
                "cursor": 0,
                "rows": {"attempts": [], "observations": [], "reconciliations": []},
                "database_path": "synthetic-fixture",
                "scope": "synthetic fixture only",
            }
        )
        history = encode(
            [
                ActionEvent(
                    0,
                    "fixture-action",
                    "fixture-candidate",
                    "write",
                    "request",
                    10.0,
                    "fixture-request",
                    event_at=9.0,
                )
            ],
            actions=("write", "wait"),
            decision_at=11.0,
            through_sequence=0,
            remaining_budget=12.0,
            deadline_at=20.0,
        )
        self.snapshot_path = self.root / "snapshot.json"
        self.snapshot = freeze_snapshot(self.snapshot_path, history, self.collection)
        self.features, self.names = history.features, list(history.feature_names)
        self.checkpoint = self.root / "checkpoint.npz"
        self.model = Model("dual_timescale", len(self.names), 2, 32, 4, 13)
        self.checksum = self.model.save(self.checkpoint)
        self.schema_digest = feature_schema_digest(self.names)
        self.contract = {
            "schema": "pred1-native-shadow-model-contract-v1",
            "checkpoint_sha256": self.checksum,
            "feature_names": self.names,
            "feature_encoding": ENCODING,
            "feature_schema_sha256": self.schema_digest,
            "action_columns": ["write", "wait"],
            "joint_support": JOINT_SUPPORT.tolist(),
            "target_domain": "declared_native_one_step",
            "success_definition": "fixture outcome only",
            "duration_unit": "fixture time",
            "cost_unit": "fixture cost",
            "model_origin": "fixture_random_initialization",
            "training_evidence_ref": None,
        }
        self.candidates = [
            {"candidate_id": "write", "action": [1.0, 0.0]},
            {"candidate_id": "wait", "action": [0.0, 1.0]},
        ]

    def predict(self, name="shadow.json", **overrides):
        values = dict(
            expected_checkpoint_sha256=self.checksum,
            expected_feature_schema_sha256=self.schema_digest,
            identity=self.identity,
            candidates=self.candidates,
            model_contract=self.contract,
        )
        values.update(overrides)
        return shadow_predict(
            self.root / name, self.snapshot_path, self.checkpoint, **values
        )

    def test_actual_forward_parity_all_model_kinds(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.model = Model(kind, len(self.names), 2, 32, 4, 13)
                self.checkpoint = self.root / (kind + ".npz")
                self.checksum = self.model.save(self.checkpoint)
                self.contract["checkpoint_sha256"] = self.checksum
                result = self.predict(kind + ".json").payload
                for prediction, query in zip(result["predictions"], self.candidates):
                    expected = self.model.forward(
                        self.features[None], np.array([query["action"]])
                    )
                    np.testing.assert_allclose(
                        prediction["logits"], expected[0], atol=1e-14
                    )
                    np.testing.assert_allclose(
                        prediction["probabilities"], softmax(expected)[0], atol=1e-14
                    )
                self.assertEqual(
                    result["metering"]["state_transition_calls"],
                    1 if kind == "single_step" else len(self.features),
                )

    def test_shared_prefix_counts_and_readonly_state(self):
        observe, head = Model.observe, Model.predict_from_state
        before = model_digest(self.model, optimizer=True)

        def checked_head(model, state, action):
            self.assertTrue(all(not value.flags.writeable for value in state.values()))
            return head(model, state, action)

        with patch.object(
            Model, "observe", autospec=True, side_effect=observe
        ) as observed:
            with patch.object(
                Model, "predict_from_state", autospec=True, side_effect=checked_head
            ) as queried:
                p = self.predict().payload
        self.assertEqual(observed.call_count, len(self.features))
        self.assertEqual(queried.call_count, 2)
        self.assertEqual(p["metering"]["candidate_head_calls"], queried.call_count)
        self.assertEqual(p["metering"]["history_encoder_passes"], 1)
        self.assertEqual(p["state_sha256_before_heads"], p["state_sha256_after_heads"])
        self.assertEqual(
            before, model_digest(Model.load(self.checkpoint), optimizer=True)
        )
        self.assertEqual(
            {
                k: p["metering"][k]
                for k in ("horizon", "latent_rollout_steps", "action_executions")
            },
            {"horizon": 1, "latent_rollout_steps": 0, "action_executions": 0},
        )

    def test_single_candidate_only_one_head_and_changed_query(self):
        a = self.predict("a.json", candidates=self.candidates[:1]).payload
        b = self.predict("b.json", candidates=self.candidates[1:]).payload
        self.assertEqual(a["metering"]["candidate_head_calls"], 1)
        self.assertEqual(b["metering"]["candidate_head_calls"], 1)
        self.assertFalse(
            np.array_equal(
                a["predictions"][0]["probabilities"],
                b["predictions"][0]["probabilities"],
            )
        )

    def test_checkpoint_schema_identity_and_contract_refuse(self):
        for overrides in (
            {"expected_checkpoint_sha256": "0" * 64},
            {"expected_feature_schema_sha256": "0" * 64},
            {"identity": {**self.identity, "run_id": "different"}},
            {"model_contract": None},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.predict(**overrides)
        for field, value in (
            ("duration_unit", ""),
            ("cost_unit", None),
            ("success_definition", ""),
            ("joint_support", []),
            ("feature_names", self.names[::-1]),
            ("action_columns", ["write", "write"]),
            ("training_evidence_ref", "random model did not train"),
            ("target_domain", "simulator"),
        ):
            contract = copy.deepcopy(self.contract)
            contract[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.predict(model_contract=contract)

    def test_nonfinite_inputs_parameters_and_outputs_refuse(self):
        for action in ([np.nan, 0.0], [1.0], [np.inf, 0.0]):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.predict(candidates=[{"candidate_id": "bad", "action": action}])
        with patch.object(
            Model, "predict_from_state", return_value=np.full((1, 32), np.nan)
        ):
            with self.assertRaises(ValueError):
                self.predict()
        self.model.params["by"][0] = np.nan
        self.checkpoint = self.root / "nonfinite.npz"
        self.checksum = self.model.save(self.checkpoint)
        self.contract["checkpoint_sha256"] = self.checksum
        with self.assertRaises(ValueError):
            self.predict()

    def test_state_mutation_and_duplicate_candidates_refuse(self):
        with self.assertRaises(ValueError):
            self.predict(candidates=self.candidates + self.candidates[:1])

        def mutate(model, state, action):
            state["fast"].setflags(write=True)
            state["fast"][:] += 1
            return np.zeros((1, 32))

        with patch.object(
            Model, "predict_from_state", autospec=True, side_effect=mutate
        ):
            with self.assertRaises(ValueError):
                self.predict()

    def test_create_only_and_later_readback_cannot_enter_snapshot(self):
        original = self.snapshot_path.read_bytes()
        result = self.predict()
        self.assertEqual(result.payload["snapshot_digest"], self.snapshot.digest)
        with self.assertRaises(FileExistsError):
            self.predict()
        later = Artifact.make(
            {**self.collection.payload, "available_at": 12.0, "cursor": 1}
        )
        readback = self.root / "readback.json"
        join_readback(readback, self.snapshot_path, later)
        self.snapshot_path = readback
        with self.assertRaises(ValueError):
            self.predict("readback-output.json")
        self.assertEqual((self.root / "snapshot.json").read_bytes(), original)

    def test_verified_bytes_ignore_checkpoint_path_replacement(self):
        load = Model.load

        def replace_path_then_load(source):
            self.assertIsInstance(source, BytesIO)
            self.checkpoint.write_bytes(b"replacement")
            return load(source)

        with patch.object(Model, "load", side_effect=replace_path_then_load):
            p = self.predict().payload
        self.assertEqual(p["checkpoint_sha256"], self.checksum)

    def test_checkpoint_limit_and_malformed_npy_fail_before_model_load(self):
        with patch(shadow_predict.__module__ + ".MAX_CHECKPOINT_BYTES", 10):
            with patch.object(Model, "load") as load, self.assertRaises(ValueError):
                self.predict()
            load.assert_not_called()
        original = self.checkpoint.read_bytes()
        for shape, descriptor in (((2**40,), "<f8"), ((), "|O")):
            buffer = BytesIO()
            np.lib.format.write_array_header_1_0(
                buffer, {"descr": descriptor, "fortran_order": False, "shape": shape}
            )
            crafted = BytesIO()
            with ZipFile(BytesIO(original)) as source, ZipFile(crafted, "w") as output:
                for item in source.infolist():
                    output.writestr(
                        item.filename,
                        buffer.getvalue()
                        if item.filename == "p_by.npy"
                        else source.read(item.filename),
                    )
            self.checkpoint.write_bytes(crafted.getvalue())
            self.checksum = sha256(crafted.getvalue()).hexdigest()
            self.contract["checkpoint_sha256"] = self.checksum
            with (
                self.subTest(shape=shape),
                patch.object(Model, "load") as load,
                self.assertRaises(ValueError),
            ):
                self.predict()
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
