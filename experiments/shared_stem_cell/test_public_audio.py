"""Speech file/partition contracts and real connector fitting, synthetic tower only."""
from __future__ import annotations

import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
from zipfile import ZipFile

import numpy as np
import torch

from experiments.shared_stem_cell import public_audio as a, calibrated_fusion as f
from experiments.shared_stem_cell import execution as e, media_execution as m


def wav_bytes(samples=800, *, rate=8000, channels=1, offset=0):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(channels); target.setsampwidth(2); target.setframerate(rate)
        target.writeframes((np.arange(samples, dtype=np.int16) + offset).astype("<i2").tobytes())
    return stream.getvalue()


def tree_for(files):
    rows = [{"path": name, "mode": "100644", "type": "blob", "size": len(raw), "sha": a.git_blob(raw)}
            for name, raw in sorted(files.items())]
    raw = b"".join(b"100644 " + row["path"].encode() + b"\0" + bytes.fromhex(row["sha"]) for row in rows)
    digest = hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return {"sha": digest, "tree": rows, "truncated": False}


class FixtureTowers:
    simulated = True

    def __init__(self, root, models):
        self.calls = {"whisper": 0}
        self.identities = {"whisper": "synthetic-test-only"}
        self.materializations = {}

    def encode(self, name, item, root):
        assert name == "audio" and set(item) == {"path", "sha256"}
        assert Path(item["path"]).stem.isalnum() and "_" not in Path(item["path"]).stem
        samples = m.audio_bytes(m.reference(root, item))
        self.calls["whisper"] += 1
        x = torch.tensor([[float(samples.mean()), float(samples.std()), .1, .2],
                          [float(samples.max()), float(samples.min()), .3, .4]])
        return x, torch.tensor([0, 20000], dtype=torch.long)

    def close(self):
        pass


class PublicAudioTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def resources(self):
        rows = a.fixed_rows()
        files = {row["source_name"]: wav_bytes(offset=i+1) for i, row in enumerate(rows)}
        tree = tree_for(files)
        readme = b"TEST ONLY attribution, not actual FSDD audio."
        stream = io.BytesIO()
        with ZipFile(stream, "w") as z:
            prefix = f"free-spoken-digit-dataset-{a.DATA_REVISION}/"
            z.writestr(prefix + "README.md", readme)
            for name, raw in files.items():
                z.writestr(prefix + "recordings/" + name, raw)
        return tree, readme, stream.getvalue()

    def staged(self, root):
        tree, readme, archive = self.resources()
        def read(url, maximum):
            return e.canonical(tree) if "/git/trees/" in url else archive
        # Explicit synthetic pins ONLY within a mock test; run() never changes its real pins.
        with patch.object(a, "verify_tree", side_effect=lambda r: original(r, tree["sha"])), \
             patch.object(a, "README_BLOB", a.git_blob(readme)):
            return a.acquire(root, _read=read)

    def test_fixed_cohort_is_class_balanced_and_speaker_disjoint(self):
        rows = a.fixed_rows()
        self.assertEqual(len({r["case_id"] for r in rows}), 240)
        groups = {s: {r["speaker"] for r in rows if r["split"] == s} for s in a.SPEAKERS}
        self.assertTrue(all(not groups[x] & groups[y] for x in groups for y in groups if x != y))
        for split, speakers in a.SPEAKERS.items():
            selected = [r for r in rows if r["split"] == split]
            self.assertEqual(len(selected), 40 * len(speakers))
            self.assertEqual(a.Counter(r["source_name"][0] for r in selected),
                             {str(d): 4*len(speakers) for d in range(10)})

    def test_git_tree_hash_and_corruption(self):
        record = tree_for({"0_example_5.wav": wav_bytes()})
        self.assertEqual(len(a.verify_tree(record, record["sha"])), 1)
        altered = copy.deepcopy(record); altered["tree"][0]["sha"] = "0"*40
        with self.assertRaises(e.InputError): a.verify_tree(altered, record["sha"])
        altered = copy.deepcopy(record); altered["tree"].append(altered["tree"][0])
        with self.assertRaises(e.InputError): a.verify_tree(altered, record["sha"])
        altered = copy.deepcopy(record); altered["truncated"] = True
        with self.assertRaises(e.InputError): a.verify_tree(altered, record["sha"])

    def test_resampling_retains_duration_and_declares_quantization(self):
        source = wav_bytes()
        converted, receipt = a.convert_wav(source)
        self.assertEqual(len(m.audio_bytes(converted)), 1600)
        self.assertEqual(receipt["samples"], 2*receipt["source_samples"])
        self.assertEqual(receipt["converted_sha256"], e.sha(converted))
        self.assertEqual(a.convert_wav(source), (converted, receipt))
        self.assertFalse(receipt["amplitude_normalization"])

    def test_wrong_source_rates_channels_lengths_rejected(self):
        for raw in (wav_bytes(rate=16000), wav_bytes(channels=2), wav_bytes(samples=100),
                    wav_bytes(samples=33000), wav_bytes()[:-10]):
            with self.subTest(size=len(raw)), self.assertRaises(e.InputError): a.convert_wav(raw)

    def test_actual_archive_staging_uses_opaque_model_inputs(self):
        descriptor = self.staged(self.root)
        cases, labels = m.read_cases(self.root, descriptor, 10)
        self.assertEqual(len(cases), 240)
        self.assertEqual(len(labels), 240)
        for case in cases:
            self.assertEqual(set(case.inputs), {"audio"})
            self.assertEqual(Path(case.inputs["audio"]["path"]).stem, case.case_id)
            self.assertFalse(hasattr(case, "label"))
        self.assertTrue((self.root / "FSDD-README.txt").exists())

    def test_acquisition_rejects_changed_audio_before_training(self):
        tree, readme, archive = self.resources()
        tree["tree"][0]["sha"] = "0"*40
        with patch.object(a, "verify_tree", return_value={r["path"]: r for r in tree["tree"]}), \
             patch.object(a, "README_BLOB", a.git_blob(readme)), self.assertRaisesRegex(e.InputError, "audio blob"):
            a.acquire(self.root, _read=lambda url, maximum: e.canonical(tree) if "/git/trees/" in url else archive)

    def test_audio_training_and_sealed_selection_run_through_existing_pipeline(self):
        output = self.root / "study"
        def stage(root, model, revision, **kwargs):
            return {"path": "model", "kind": "whisper", "revision": revision, "files": {}}
        order = []
        actual_execute = f.execute_calibrated
        def execute(*args, **kwargs):
            self.assertTrue((output / "execution/calibration-selection.json").is_file())
            order.append("holdout")
            return actual_execute(*args, **kwargs)
        with patch.object(f, "execute_calibrated", side_effect=execute):
            result = a.run(output, _acquire=self.staged, _stage=stage, _towers=FixtureTowers)
        report = e.decode((output / "execution/report.json").read_bytes())
        selection = e.decode((output / "execution/calibration-selection.json").read_bytes())
        self.assertEqual(order, ["holdout"])
        self.assertTrue(result["simulated_towers"])
        self.assertEqual(report["tower_forward_calls"], {"whisper": 240})
        self.assertEqual(selection["costs"]["actual_optimizer_steps"], 80)
        self.assertEqual(selection["binding"]["model_identities"], {"whisper": "synthetic-test-only"})
        self.assertEqual({r["cases"] for r in report["scores"]}, {40})
        self.assertEqual(result["execution_report_sha256"], e.sha((output / "execution/report.json").read_bytes()))
        self.assertFalse(result["production_accepted"])

    def test_acquisition_failure_never_falls_back_to_synthetic_tower(self):
        def denied(_): raise OSError("test missing public bytes")
        with patch.object(m, "LocalTowers", side_effect=AssertionError("must not load")), \
             self.assertRaises(OSError): a.run(self.root / "failed", _acquire=denied)
        self.assertTrue((self.root / "failed/failure.json").is_file())
        self.assertFalse((self.root / "failed/report.json").exists())

    def test_cross_speaker_leakage_rejected_by_existing_media_gate(self):
        descriptor = self.staged(self.root)
        path = self.root / descriptor["path"]
        rows = [e.decode(line) for line in path.read_bytes().splitlines()]
        rows[-1]["group"] = rows[0]["group"]
        data = b"".join(e.canonical(row) for row in rows); path.write_bytes(data)
        with self.assertRaisesRegex(e.InputError, "leakage"):
            m.read_cases(self.root, {"path": path.name, "sha256": e.sha(data)}, 10)

    def test_audio_checkpoint_selection_does_not_admit_unimplemented_cross_modal_profile(self):
        x = (torch.zeros(4, 2, 4), torch.ones(4, 2, dtype=torch.bool), torch.tensor([[0, 1]]*4))
        self.assertEqual(f.validate({"audio": x}), {"audio": (2, 4)})
        with self.assertRaises(e.InputError): f.validate({"audio": x, "image": x})
        with self.assertRaises(e.InputError): f.validate({"video": x})


original = a.verify_tree

if __name__ == "__main__":
    unittest.main()
