import io
import json
from pathlib import Path
import struct
import unittest
import zipfile

from export_cell_head_bundle import build_bundle
from export_cell_head_bundle import verify_tensors

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/p37-head"


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((FIXTURE / "manifest.json").read_bytes())
        self.weights = (FIXTURE / "weights.npz").read_bytes()

    def rewrite_tensor(self, transform):
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.weights)) as source, zipfile.ZipFile(output, "w") as target:
            for name in source.namelist():
                value = source.read(name)
                if name == "task_head.bias.npy":
                    value = transform(value)
                target.writestr(name, value)
        return output.getvalue()

    def test_real_immutable_tensor_inventory_and_digest(self):
        verify_tensors(self.weights, self.manifest["report"])

    def test_nan_cannot_cross_the_export_boundary(self):
        altered = self.rewrite_tensor(lambda value: value[:-4] + struct.pack("<f", float("nan")))
        with self.assertRaisesRegex(ValueError, "tensor values"):
            verify_tensors(altered, self.manifest["report"])

    def test_finite_tampering_still_fails_tensor_digest(self):
        altered = self.rewrite_tensor(lambda value: value[:-4] + struct.pack("<f", 123.0))
        with self.assertRaisesRegex(ValueError, "tensor digest"):
            verify_tensors(altered, self.manifest["report"])

    def test_tensor_shape_is_part_of_the_identity(self):
        altered = self.rewrite_tensor(lambda value: value.replace(b"(4,)", b"(3,)", 1))
        with self.assertRaisesRegex(ValueError, "shape/dtype/order"):
            verify_tensors(altered, self.manifest["report"])

    def test_export_never_accepts_activation_authority(self):
        self.manifest["report"]["production_activation_allowed"] = True
        with self.assertRaisesRegex(ValueError, "authority mismatch"):
            build_bundle(json.dumps(self.manifest).encode(), self.weights, b"{}", lambda _: b"")

    def test_descendant_cannot_erase_inherited_sources_in_a_standalone_bundle(self):
        self.manifest["report"]["evolution"] = {
            "requires_evolution_snapshot": True,
            "parent_source_closure_sha256": "a" * 64,
        }
        with self.assertRaisesRegex(ValueError, "complete evolution source closure"):
            build_bundle(json.dumps(self.manifest).encode(), self.weights, b"{}", lambda _: b"")


if __name__ == "__main__":
    unittest.main()
