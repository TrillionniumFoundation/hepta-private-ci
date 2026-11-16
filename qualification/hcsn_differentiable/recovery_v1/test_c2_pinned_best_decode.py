"""Negative tests for frozen original-C2 best.pt semantic decoder (no training)."""
from collections import OrderedDict
import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest

try:
    from .c2_pinned_best_decode import (
        CheckpointHold, DATA_SHA, NAMES, ORIGINAL_JOB, audit, decode_pinned,
    )
except ImportError:
    from c2_pinned_best_decode import (
        CheckpointHold, DATA_SHA, NAMES, ORIGINAL_JOB, audit, decode_pinned,
    )

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "Requires native torch to test actual weights_only decoding")
class PinnedBestDecodeTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.fits = self.root / "fits"
        self.fits.mkdir()
        self.pinned = {}

    def state(self, seed, *, epoch=12):
        return {
            "model": {f"tensor.{j}": torch.ones(2, dtype=torch.float32) for j in range(23)},
            "model_configuration": {"arm": "hcsn", "seed": seed},
            "optimizer": {"state": {}, "param_groups": []},
            "torch_rng": torch.get_rng_state(),
            "order_rng": random.Random(1).getstate(),
            "epochs_completed": epoch, "main_updates": epoch * 12,
            "data_manifest_sha256": DATA_SHA,
        }

    def data(self, seed, **changes):
        value = self.state(seed)
        value.update(changes)
        out = io.BytesIO()
        torch.save(value, out)
        return out.getvalue()

    def populate(self):
        entries = []
        for name in NAMES:
            seed = int(name.split("-")[1][1:])
            path = self.fits / name / "best.pt"
            path.parent.mkdir()
            raw = self.data(seed)
            path.write_bytes(raw)
            entries.append({"candidate": name, "file": "best.pt", "path": str(path),
                            "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        for idx in range(6):
            entries.append({"candidate": f"fake-{idx}", "file": "result.json",
                            "path": str(self.fits / f"fake-{idx}" / "result.json"),
                            "size_bytes": 1, "sha256": "a" * 64})
        manifest = self.root / "inventory.json"
        manifest.write_text(json.dumps({
            "schema": "hcsn-original-c2-fits-readonly-inventory-v1",
            "original_job_id": ORIGINAL_JOB, "original_fits_root": str(self.fits),
            "files": entries}))
        return manifest

    def test_synthetic_two_safe_decodes_never_adopt(self):
        report = audit(self.fits, self.populate())
        self.assertEqual(report["decoded_best_count"], 2)
        self.assertFalse(report["all_six_independently_replayed"])
        self.assertEqual(report["scientific_admission"], "HOLD_NO_GO")

    def test_native_ordereddict_state_dict_is_admitted_without_go(self):
        state = self.state(211)
        state["model"] = OrderedDict(state["model"])
        out = io.BytesIO()
        torch.save(state, out)
        row = decode_pinned(out.getvalue(), name=NAMES[0])
        self.assertEqual(row["model_tensor_count"], 23)
        self.assertEqual(row["status"], "PINNED_BEST_DECODED_NOT_REPLAYED")

    def test_wrong_seed_cannot_deserialize_as_another_fit(self):
        with self.assertRaises(CheckpointHold):
            decode_pinned(self.data(307), name=NAMES[0])

    def test_nonfinite_model_tensor_held(self):
        state = self.state(211)
        state["model"]["tensor.0"][0] = float("nan")
        out = io.BytesIO()
        torch.save(state, out)
        with self.assertRaisesRegex(CheckpointHold, "nonfinite"):
            decode_pinned(out.getvalue(), name=NAMES[0])

    def test_nonfinite_optimizer_tensor_held(self):
        state = self.state(211)
        state["optimizer"]["state"] = {0: {"exp_avg": torch.tensor([float("inf")])}}
        out = io.BytesIO()
        torch.save(state, out)
        with self.assertRaisesRegex(CheckpointHold, "nonfinite"):
            decode_pinned(out.getvalue(), name=NAMES[0])

    def test_wrong_data_manifest_held(self):
        with self.assertRaisesRegex(CheckpointHold, "data-manifest"):
            decode_pinned(self.data(211, data_manifest_sha256="b" * 64), name=NAMES[0])

    def test_malformed_counter_held(self):
        with self.assertRaisesRegex(CheckpointHold, "counter"):
            decode_pinned(self.data(211, epochs_completed=250), name=NAMES[0])

    def test_zero_and_corrupt_originals_held(self):
        inv = self.populate()
        p = self.fits / NAMES[0] / "best.pt"
        p.write_bytes(b"")
        result = audit(self.fits, inv)
        self.assertEqual(result["decoded_best_count"], 1)
        self.assertEqual(result["rows"][0]["status"], "HOLD")
        p.write_bytes(b"not-the-pinned-torch")
        result = audit(self.fits, inv)
        self.assertEqual(result["decoded_best_count"], 1)
        self.assertIn("bytes differ", result["rows"][0]["error"])

    def test_symlink_to_original_held(self):
        inv = self.populate()
        target = self.fits / NAMES[0] / "best.pt"
        other = self.root / "redirect.pt"
        target.rename(other)
        target.symlink_to(other)
        result = audit(self.fits, inv)
        self.assertEqual(result["decoded_best_count"], 1)
        self.assertEqual(result["rows"][0]["status"], "HOLD")

    def test_manifest_mismatch_fails_closed(self):
        inv = self.populate()
        document = json.loads(inv.read_text())
        document["original_job_id"] = "wrong-job"
        inv.write_text(json.dumps(document))
        with self.assertRaisesRegex(CheckpointHold, "identity differs"):
            audit(self.fits, inv)

    def test_duplicate_manifest_key_held(self):
        inv = self.populate()
        value = inv.read_text()
        inv.write_text(value.replace('"original_job_id":', '"original_job_id":"duplicate","original_job_id":'))
        with self.assertRaisesRegex(CheckpointHold, "duplicate"):
            audit(self.fits, inv)


if __name__ == "__main__":
    unittest.main()

