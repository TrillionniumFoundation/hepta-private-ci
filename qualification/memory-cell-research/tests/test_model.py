"""Behavioral checks of real gradients, training, and parameter-only persistence."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from memory_cells.encoding import FrozenEncoder, canonical_bytes
from memory_cells.model import MemoryCell


class MemoryModelTests(unittest.TestCase):
    def test_gradient_matches_independent_finite_differences(self):
        rng = np.random.default_rng(101)
        X = rng.normal(size=(5, 8))
        y = np.array([0, 1, 2, 1, 0])
        cell = MemoryCell(8, 3, 3, seed=4)
        _, grad_A, grad_B = cell.loss_and_gradients(X, y)
        epsilon = 1e-6
        for weights, expected in ((cell.A, grad_A), (cell.B, grad_B)):
            observed = np.empty_like(weights)
            for index in np.ndindex(weights.shape):
                before = weights[index]
                weights[index] = before + epsilon
                loss_plus = -np.log(cell.proba(X)[np.arange(len(y)), y]).mean()
                weights[index] = before - epsilon
                loss_minus = -np.log(cell.proba(X)[np.arange(len(y)), y]).mean()
                weights[index] = before
                observed[index] = (loss_plus - loss_minus) / (2 * epsilon)
            np.testing.assert_allclose(expected, observed, atol=1e-8, rtol=1e-5)

    def test_learns_new_associations_and_reloads_parameters(self):
        encoder = FrozenEncoder(64, 1)
        keys = [f"record:zx-{i:03d}" for i in range(24)]
        targets = np.random.default_rng(97).integers(0, 8, len(keys))
        X = encoder.encode(keys)
        cell = MemoryCell(64, 12, 8, seed=23)
        before = np.mean(cell.predict(X) == targets)
        receipt = cell.fit(X, targets, steps=220, lr=0.04)
        self.assertLess(before, 0.5)
        np.testing.assert_array_equal(cell.predict(X), targets)
        self.assertLess(receipt["final_loss"], receipt["initial_loss"] / 20)
        self.assertEqual(receipt["examples_seen"], 220 * len(X))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "cell"
            manifest = cell.save(
                directory,
                encoder_manifest=encoder.manifest(),
                lineage={"dataset": hashlib.sha256(b"fixture").hexdigest()},
            )
            reloaded = MemoryCell.load(
                directory, expected_encoder_digest=encoder.digest
            )
            np.testing.assert_array_equal(reloaded.proba(X), cell.proba(X))
            self.assertEqual(manifest["parameter_bytes"], cell.parameter_bytes)
            self.assertEqual(
                {p.name for p in directory.iterdir()}, {"manifest.json", "tensors.npz"}
            )
            manifest_text = (directory / "manifest.json").read_text()
            self.assertTrue(all(key not in manifest_text for key in keys))
            with self.assertRaises(FileExistsError):
                cell.save(directory, encoder_manifest=encoder.manifest())

    def test_clone_training_does_not_mutate_parent(self):
        encoder = FrozenEncoder(32, 3)
        X = encoder.encode(["alpha", "beta", "gamma", "delta"])
        cell = MemoryCell(32, 8, 4)
        original = cell.proba(X).copy()
        child = cell.clone(seed=1)
        child.fit(X, np.array([1, 0, 3, 2]), steps=60)
        np.testing.assert_array_equal(cell.proba(X), original)
        self.assertFalse(np.array_equal(child.proba(X), original))

    def test_rank_expansion_preserves_function_and_shrink_reports_loss(self):
        encoder = FrozenEncoder(32, 11)
        X = encoder.encode(["a:001", "b:002", "c:003", "d:004"])
        cell = MemoryCell(32, 8, 4)
        cell.fit(X, np.array([0, 1, 2, 3]), steps=60)
        original = cell.proba(X).copy()
        expanded, expanded_receipt = cell.resize_rank(12, seed=77)
        np.testing.assert_allclose(expanded.proba(X), original, atol=1e-14)
        self.assertTrue(expanded_receipt["algebraically_function_preserving"])
        self.assertEqual(expanded_receipt["inherited_units"], 8)
        smaller, smaller_receipt = cell.resize_rank(3)
        np.testing.assert_array_equal(smaller.A, cell.A[:, :3])
        np.testing.assert_array_equal(smaller.B, cell.B[:3])
        self.assertFalse(smaller_receipt["algebraically_function_preserving"])
        self.assertEqual(smaller_receipt["dropped_units"], 5)
        self.assertFalse(np.allclose(smaller.proba(X), original))
        np.testing.assert_array_equal(cell.proba(X), original)

    def test_encoder_round_trip_and_unicode_normalization(self):
        encoder = FrozenEncoder(64, 19)
        recovered = FrozenEncoder.from_manifest(
            json.loads(canonical_bytes(encoder.manifest()))
        )
        X = encoder.encode(["ＡLPHA record:42", "alpha record:42"])
        np.testing.assert_array_equal(X[0], X[1])
        np.testing.assert_array_equal(recovered.encode(["alpha record:42"]), X[:1])
        self.assertEqual(recovered.digest, encoder.digest)
        np.testing.assert_allclose(np.linalg.norm(X, axis=1), np.ones(2))

    def test_rejects_nonfinite_features_and_invalid_targets(self):
        cell = MemoryCell(8, 3, 4)
        for X, y in (
            (np.full((2, 8), np.nan), [0, 1]),
            (np.zeros((2, 8)), [0.0, 1.0]),
            (np.zeros((2, 8)), [0, 4]),
        ):
            with self.subTest(targets=y), self.assertRaises(ValueError):
                cell.fit(X, y, steps=1)

    def test_rejects_corrupt_and_wrong_encoder_artifacts(self):
        encoder = FrozenEncoder(16)
        cell = MemoryCell(16, 3, 4)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "cell"
            cell.save(directory, encoder_manifest=encoder.manifest())
            with self.assertRaisesRegex(ValueError, "encoder digest"):
                MemoryCell.load(directory, expected_encoder_digest="0" * 64)
            tensor_file = directory / "tensors.npz"
            changed = bytearray(tensor_file.read_bytes())
            changed[100] ^= 1
            tensor_file.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "tensor digest"):
                MemoryCell.load(directory)

    def test_rejects_self_consistently_hashed_invalid_tensor(self):
        encoder = FrozenEncoder(16)
        cell = MemoryCell(16, 3, 4)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "cell"
            manifest = cell.save(directory, encoder_manifest=encoder.manifest())
            malformed = io.BytesIO()
            np.savez(malformed, A=np.full((16, 3), np.nan), B=cell.B)
            data = malformed.getvalue()
            (directory / "tensors.npz").write_bytes(data)
            manifest["tensor_sha256"] = hashlib.sha256(data).hexdigest()
            manifest["tensor_nbytes"] = len(data)
            del manifest["manifest_sha256"]
            manifest["manifest_sha256"] = hashlib.sha256(
                canonical_bytes(manifest)
            ).hexdigest()
            (directory / "manifest.json").write_bytes(canonical_bytes(manifest))
            with self.assertRaisesRegex(ValueError, "finite state"):
                MemoryCell.load(directory)


if __name__ == "__main__":
    unittest.main()
