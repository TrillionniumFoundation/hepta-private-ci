"""Synthetic tensor contract tests only: no pretrained semantic efficacy claim."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from selected_routing_policy import (Adapter, BM25, CalibratedExperts, Centroid, ELIGIBLE, EXPERTS,
    NEURAL, NearestExample, RUNTIME_SOURCES, RoutingCalibration, SelectedRoutingPolicy, SparseExperts, canonical, sha)
from routing_experiment import Ridge, predict, save_model


class Fixture:
    def __init__(self, root):
        self.root = root
        self.descriptor = {"model_id": "explicit-synthetic-contract-fixture", "embedding_dimension": 384}
        self.encoder_hash = sha(canonical(self.descriptor))
        self.X = np.tile(np.eye(384, dtype=np.float32)[:12], (10, 1))
        self.y = np.tile(np.arange(12), 10)
        self.rows = [dict(text=f"operation_{label} training example_{i}", label=int(label), split="train",
                          payload=["red", "blue", "red"], expected="poisoned golden must never be consulted")
                     for i, label in enumerate(self.y)]
        self.source_version = sha(canonical(self.rows))
        self.write("encoder_manifest.json", {"encoder_hash": self.encoder_hash, "source_version": self.source_version,
                                           "encoder": self.descriptor})
        for split, n in (("train", 120), ("calibration", 48)):
            self.write(split + "_rows.json", self.rows[:n])
            np.savez_compressed(root / (split + "_features.npz"), X=self.X[:n], y=self.y[:n])
        model = Adapter(384, 12, 8, 713, self.encoder_hash, self.source_version)
        model.train(self.X, self.y, steps=3, data_id="v14-original-skills", source_version=self.source_version)
        self.models = {n: model.clone() for n in NEURAL}
        self.models.update(ridge=Ridge(self.X, self.y, 12), centroid=Centroid(self.rows, self.X),
                           nearest=NearestExample(self.rows, self.X), bm25=BM25(self.rows))
        for group in ("fixed", "gradient", "random"):
            network = SparseExperts(model, [list(range(i, i + 4)) for i in (0, 4, 8)], top_k=2)
            network.train(self.X, self.y, steps=2, batch_size=20, lr=.01,
                          data_id="v14-original-skills", source_version=self.source_version)
            self.models[group + "_raw"] = CalibratedExperts(network)
            calibration = RoutingCalibration(network.partition)
            calibration.theta = np.array([.1, .2, -.1, .3, .05, -.02, -.03])
            calibration.receipt = {"status": "fitted", "parameters": calibration.theta.tolist()}
            self.models[group + "_calibrated"] = CalibratedExperts(network, calibration)
        (root / "seed-713").mkdir()
        for name, value in self.models.items():
            save_model(value, root / "seed-713" / name)
        self.select("centroid")

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical(value) + b"\n")

    def select(self, selected):
        self.write("seed-713/SELECTION.json", {"selected": selected, "new_holdout_scored": False,
                                             "scores": {n: 42 if n == selected else 40 for n in ELIGIBLE}})
        files = {"routing/" + str(p.relative_to(self.root)): {"bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
                 for p in self.root.rglob("*") if p.is_file() and p.name != "INDEX.json"}
        files.update({"routing/EXECUTED_SOURCE/" + n: {"bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
                      for n, p in RUNTIME_SOURCES.items()})
        self.write("INDEX.json", {"source_commit": "synthetic-unit-fixture", "files": files})
        self.index_sha = sha((self.root / "INDEX.json").read_bytes())

    def load(self, **overrides):
        args = {"expected_inventory_sha256": self.index_sha, "expected_encoder_hash": self.encoder_hash,
                "expected_source_version": self.source_version}
        return SelectedRoutingPolicy(self.root, self.root / "INDEX.json", **{**args, **overrides})


class SelectedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def test_all_eligible_checkpoint_families_restore_actual_predictions_and_training_state(self):
        f = self.fixture
        for name in ELIGIBLE:
            with self.subTest(candidate=name):
                f.select(name)
                policy = f.load()
                expected = int(predict(f.models[name], f.X[0:1], [f.rows[0]["text"]])[0])
                actual = policy.predict_cached("train", 0, source_version=f.source_version, selective=False)
                self.assertEqual(actual["prediction"], expected)
                if name in NEURAL:
                    self.assertEqual(policy.model.state_hash(), f.models[name].state_hash())
                if name in EXPERTS:
                    self.assertEqual(actual["receipt"]["expert_example_invocations"], 2)
                    for loaded, original in zip(policy.model.network.experts, f.models[name].network.experts):
                        self.assertEqual(loaded.state_hash(), original.state_hash())

    def test_next_caller_payload_is_executed_without_fixture_goldens_or_held_results(self):
        f = self.fixture
        policy = f.load()
        prediction = policy.predict_cached("train", 0, source_version=f.source_version)
        output = policy.execute_prediction(prediction, ["elm", "fir", "elm", "oak"])
        self.assertEqual(output["output"], ["elm", "fir", "oak"])
        self.assertIsNone(output["error"])
        self.assertFalse(any("held" in n or n.endswith("RESULTS.json") for n in policy.checked_files))
        self.assertGreater(policy.load_receipt["checkpoint_bytes_read"], 0)
        self.assertEqual(output["receipt"]["checkpoint_bytes_read_this_prediction"], 0)

    def test_original_artifact_corruption_is_rejected(self):
        f = self.fixture
        path = f.root / "seed-713/centroid/arrays.npz"
        path.write_bytes(path.read_bytes() + b"corruption")
        with self.assertRaises(ValueError):
            f.load()

    def test_numpy_object_arrays_are_never_unpickled_even_under_a_pinned_fixture_inventory(self):
        f = self.fixture
        path = f.root / "seed-713/centroid/arrays.npz"
        np.savez_compressed(path, features=np.array([{"not": "numeric"}], dtype=object), labels=np.arange(12))
        f.select("centroid")
        with self.assertRaisesRegex(ValueError, "Object arrays cannot be loaded"):
            f.load()

    def test_inventory_encoder_and_source_must_be_pinned(self):
        for field in ("expected_inventory_sha256", "expected_encoder_hash", "expected_source_version"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.fixture.load(**{field: "wrong"})
        policy = self.fixture.load()
        with self.assertRaises(ValueError):
            policy.predict_cached("train", 0, source_version="new-source-cut")
        with self.assertRaises(ValueError):
            policy.predict_cached("new_held", 0, source_version=self.fixture.source_version)

    def test_live_encoder_is_invoked_and_wrong_identity_rejected_before_encoding(self):
        f = self.fixture
        policy = f.load()
        class ContractEncoder:
            manifest_hash = f.encoder_hash
            stats = {"calls": 0, "examples": 0, "load_seconds": .1}
            def encode(self, texts):
                self.stats["calls"] += 1
                self.stats["examples"] += len(texts)
                return f.X[:len(texts)]
        encoder = ContractEncoder()
        with self.assertRaises(ValueError):
            policy.predict_text("different request", encoder, source_version="wrong")
        self.assertEqual(encoder.stats["calls"], 0)
        result = policy.predict_text("different request", encoder, source_version=f.source_version)
        self.assertEqual(encoder.stats["calls"], 1)
        self.assertEqual(result["receipt"]["encoder"]["statistics_delta"]["examples"], 1)
        encoder.manifest_hash = "wrong"
        with self.assertRaises(ValueError):
            policy.predict_text("different request", encoder, source_version=f.source_version)
        self.assertEqual(encoder.stats["calls"], 1)

    def test_recovery_does_not_reselect_using_saved_held_statistics(self):
        f = self.fixture
        f.write("seed-713/RESULTS.json", {"selected": "gradient_calibrated", "models": {"gradient_calibrated": 999999}})
        policy = f.load()
        self.assertEqual(policy.selected, "centroid")


if __name__ == "__main__":
    unittest.main()
