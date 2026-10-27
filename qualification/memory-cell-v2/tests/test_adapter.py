"""Numerical adapter persistence checks; no pretrained runtime is required."""

import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-research"))
sys.path.insert(0, str(PACKAGE))
from memory_cells.model import MemoryCell  # noqa: E402
from v2.adapter import load_cell, save_cell  # noqa: E402
from v2.encoder import canonical, sha  # noqa: E402


ENCODER = {"schema": "development-numeric-features.v1", "dimension": 16, "frozen": True}
SOURCE_COMMIT = "a" * 40
SUPPORT_DIGEST = "b" * 64


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features = np.random.default_rng(8001).normal(size=(24, 16))
        cls.features /= np.linalg.norm(cls.features, axis=1, keepdims=True)
        cls.targets = np.random.default_rng(8003).integers(0, 4, size=24)
        cls.cell = MemoryCell(16, 12, 4, seed=8001)
        cls.receipt = cls.cell.fit(cls.features, cls.targets, steps=600, lr=0.03)

    def save(self, path, cell=None):
        return save_cell(
            self.cell if cell is None else cell,
            path,
            ENCODER,
            source_commit=SOURCE_COMMIT,
            support_digest=SUPPORT_DIGEST,
        )

    def reseal(self, path, manifest):
        manifest.pop("manifest_sha256", None)
        manifest["manifest_sha256"] = sha(canonical(manifest))
        (path / "manifest.json").write_bytes(canonical(manifest))

    def test_real_training_survives_save_load_with_exact_encoder_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cell"
            manifest = self.save(path)
            loaded, actual_manifest = load_cell(
                path, expected_encoder_digest=sha(canonical(ENCODER))
            )
            self.assertEqual(actual_manifest, manifest)
            np.testing.assert_array_equal(loaded.predict(self.features), self.targets)
            np.testing.assert_array_equal(loaded.A, self.cell.A)
            np.testing.assert_array_equal(loaded.B, self.cell.B)
            self.assertEqual(loaded.total_steps, 600)
            self.assertEqual(loaded.parameter_bytes, manifest["parameter_bytes"])
            self.assertLess(
                self.receipt["final_loss"], self.receipt["initial_loss"] / 20
            )
            self.assertEqual(
                set(p.name for p in path.iterdir()), {"manifest.json", "tensors.npz"}
            )
            with self.assertRaises(ValueError):
                load_cell(path, expected_encoder_digest="0" * 64)

    def test_incomplete_extra_corrupt_and_encoder_shape_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for scenario in (
                "missing",
                "extra",
                "bytes",
                "dimension",
                "source",
                "support",
                "steps",
            ):
                path = Path(tmp) / scenario
                manifest = self.save(path)
                digest = manifest["encoder_digest"]
                if scenario == "missing":
                    (path / "tensors.npz").unlink()
                elif scenario == "extra":
                    (path / "samples.json").write_text("[]", encoding="utf-8")
                elif scenario == "bytes":
                    data = bytearray((path / "tensors.npz").read_bytes())
                    data[-1] ^= 1
                    (path / "tensors.npz").write_bytes(data)
                else:
                    if scenario == "dimension":
                        manifest["encoder"]["dimension"] = 17
                        digest = sha(canonical(manifest["encoder"]))
                        manifest["encoder_digest"] = digest
                    elif scenario == "source":
                        manifest["source_commit"] = "invalid-source"
                    elif scenario == "support":
                        manifest["support_digest"] = "invalid-support"
                    else:
                        manifest["total_steps"] = -1
                    self.reseal(path, manifest)
                with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                    load_cell(path, expected_encoder_digest=digest)

    def test_invalid_weights_are_rejected_before_creating_an_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            for scenario in ("shape", "nan", "dtype", "steps"):
                cell = self.cell.clone()
                if scenario == "shape":
                    cell.A = cell.A[:-1]
                elif scenario == "nan":
                    cell.A[0, 0] = np.nan
                elif scenario == "dtype":
                    cell.B = cell.B.astype(np.float32)
                else:
                    cell.total_steps = True
                path = Path(tmp) / scenario
                with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                    self.save(path, cell)
                self.assertFalse(path.exists())

    def test_forged_huge_array_header_rejected_before_array_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cell"
            manifest = self.save(path)
            bad_array = io.BytesIO()
            np.lib.format.write_array_header_1_0(
                bad_array,
                {
                    "descr": "<f8",
                    "fortran_order": False,
                    "shape": (1_000_000_000, 12),
                },
            )
            valid_array = io.BytesIO()
            np.save(valid_array, self.cell.B, allow_pickle=False)
            buffer = io.BytesIO()
            with zipfile.ZipFile(
                buffer, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr("A.npy", bad_array.getvalue())
                archive.writestr("B.npy", valid_array.getvalue())
            data = buffer.getvalue()
            (path / "tensors.npz").write_bytes(data)
            manifest.update(tensor_sha256=sha(data), tensor_bytes=len(data))
            self.reseal(path, manifest)
            with self.assertRaisesRegex(ValueError, "array header"):
                load_cell(path, expected_encoder_digest=manifest["encoder_digest"])

    def test_symlinked_artifact_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.save(root / "cell")
            try:
                (root / "link").symlink_to(root / "cell", target_is_directory=True)
            except OSError as error:
                self.skipTest(f"host does not permit symlinks: {error}")
            with self.assertRaisesRegex(ValueError, "symlink"):
                load_cell(
                    root / "link", expected_encoder_digest=manifest["encoder_digest"]
                )


if __name__ == "__main__":
    unittest.main()
