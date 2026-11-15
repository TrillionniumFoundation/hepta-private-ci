"""Actual pretrained-worker checks and train-only PCA contracts.

Set PERC_TEST_MOBILENET_WEIGHTS to the official mobilenet_v3_small-047dcff4.pth.
Rendered test images exercise engineering behavior, not real-task qualification.
"""

import base64
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from perc1.producer import FrozenMobileNet, produce
from perc1.projection import fit_projection, project
from perc1.schema import Invalid, sha

WEIGHTS_SHA = "047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f"


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.features = np.arange(4 * 576, dtype=float).reshape(4, 576)
        self.args = {
            "captures": [
                {"sha256": sha(str(i).encode()), "split": "train"} for i in range(4)
            ],
            "groups": ["group-a", "group-a", "group-b", "group-b"],
            "backbone_sha256": WEIGHTS_SHA,
            "dimension": 2,
        }

    def test_finite_projection_and_backbone_pin(self):
        projection = fit_projection(self.features, **self.args)
        result = project(self.features, projection, WEIGHTS_SHA)
        self.assertEqual(result.shape, (4, 2))
        self.assertTrue(np.isfinite(result).all() and (np.abs(result) <= 1).all())
        self.assertFalse(projection["training"]["scientific_qualified"])
        with self.assertRaises(Invalid):
            project(self.features, projection, sha(b"other backbone"))
        projection["scale"][0] = 0
        with self.assertRaises(Invalid):
            project(self.features, projection, WEIGHTS_SHA)

    def test_training_metadata_tamper_rejected(self):
        projection = fit_projection(self.features, **self.args)
        for key, value in (
            ("wall_ns", float("nan")),
            ("captures_sha256", "0" * 64),
            ("rows", 1),
            ("scientific_qualified", True),
            ("source_groups", ["b", "a"]),
        ):
            changed = copy.deepcopy(projection)
            changed["training"][key] = value
            with self.subTest(key=key), self.assertRaises(Invalid):
                project(self.features, changed, WEIGHTS_SHA)

    def test_heldout_duplicate_group_and_nonfinite_rejected(self):
        args = copy.deepcopy(self.args)
        args["captures"][0]["split"] = "confirmation"
        with self.assertRaises(Invalid):
            fit_projection(self.features, **args)
        args = copy.deepcopy(self.args)
        args["captures"][2] = args["captures"][0]
        with self.assertRaises(Invalid):
            fit_projection(self.features, **args)
        self.features[0, 0] = np.nan
        with self.assertRaises(Invalid):
            fit_projection(self.features, **self.args)


@unittest.skipUnless(
    os.environ.get("PERC_TEST_MOBILENET_WEIGHTS"),
    "explicit official checkpoint required",
)
class ProducerExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.weights = Path(os.environ["PERC_TEST_MOBILENET_WEIGHTS"])
        cls.worker = FrozenMobileNet(cls.weights, WEIGHTS_SHA)
        cls.regions = [
            {"evidence_id": "crop.0", "x": 0, "y": 0, "width": 16, "height": 16},
            {"evidence_id": "crop.1", "x": 16, "y": 16, "width": 16, "height": 16},
        ]
        features, captures, groups = [], [], []
        for index in range(4):
            values = np.fromfunction(
                lambda y, x, c: (x * (index + 1) + y * (index + 3) + c * 37) % 256,
                (32, 32, 3),
            ).astype(np.uint8)
            buf = io.BytesIO()
            Image.fromarray(values).save(buf, format="PNG")
            raw = buf.getvalue()
            (cls.root / (str(index) + ".png")).write_bytes(raw)
            _, actual, _ = cls.worker.features(raw, cls.regions)
            features.extend(actual)
            captures.extend([{"sha256": sha(raw), "split": "train"}] * 2)
            groups.extend(["source-" + str(index)] * 2)
        cls.projection = fit_projection(
            features,
            captures=captures,
            groups=groups,
            backbone_sha256=WEIGHTS_SHA,
            dimension=3,
        )
        cls.request = {
            "schema": "perc1.producer-request.v1",
            "operation_id": "producer-execution-test",
            "capture_path": str(cls.root / "0.png"),
            "capture_sha256": sha((cls.root / "0.png").read_bytes()),
            "source_id": "image.0",
            "observed_at_micros": 123,
            "regions": cls.regions,
            "representation": "dense",
            "scope_digest": sha(b"scope"),
            "source_frontier": sha(b"frontier"),
            "exact_text": None,
        }

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_actual_worker_recompute_and_original_pixels(self):
        before = self.worker.calls
        first = produce(self.worker, self.request, self.projection)
        replay = produce(self.worker, self.request, self.projection)
        self.assertEqual(self.worker.calls, before + 2)
        self.assertEqual(first["observation"], replay["observation"])
        self.assertEqual(
            first["transform"]["features_f32le_sha256"],
            replay["transform"]["features_f32le_sha256"],
        )
        image = Image.open(self.request["capture_path"]).convert("RGB")
        self.assertEqual(
            first["observation"]["evidence"][0]["raw_bytes"],
            list(image.crop((0, 0, 16, 16)).tobytes()),
        )
        self.assertEqual(first["model"]["backbone_sha256"], WEIGHTS_SHA)
        self.assertEqual(first["worker"]["pid"], os.getpid())
        self.assertEqual(
            first["receipt_sha256"],
            sha({k: v for k, v in first.items() if k != "receipt_sha256"}),
        )
        self.assertEqual(first["scientific_status"], "HOLD")
        self.assertTrue(first["transform"]["inference_ns"] > 0)

    def test_global_dense_have_same_lossless_evidence(self):
        dense = produce(self.worker, self.request, self.projection)
        global_result = produce(
            self.worker, dict(self.request, representation="global"), self.projection
        )
        self.assertEqual(
            dense["observation"]["evidence"], global_result["observation"]["evidence"]
        )
        self.assertEqual(len(global_result["observation"]["latents"]), 1)
        self.assertEqual(len(dense["observation"]["latents"]), 2)

    def test_exact_text_preserved_ocr_not_certified(self):
        raw = "日期=2026-11-09; 金额=0019.90; path=/a/b".encode()
        path = self.root / "exact.txt"
        path.write_bytes(raw)
        text = {
            "kind": "ocr",
            "path": str(path),
            "sha256": sha(raw),
            "capture_sha256": self.request["capture_sha256"],
            "engine": "controlled test transcription",
        }
        receipt = produce(
            self.worker, dict(self.request, exact_text=text), self.projection
        )
        self.assertEqual(base64.b64decode(receipt["exact_text"]["raw_base64"]), raw)
        self.assertEqual(receipt["exact_text"]["text"].encode(), raw)
        self.assertEqual(
            receipt["exact_text"]["fidelity"], "ocr_transcription_unverified"
        )
        with self.assertRaises(Invalid):
            produce(
                self.worker,
                dict(
                    self.request,
                    exact_text=dict(text, capture_sha256=sha(b"unrelated")),
                ),
                self.projection,
            )

    def test_invalid_capture_capacity_rejected_before_inference(self):
        before = self.worker.calls
        for request in (
            dict(self.request, capture_sha256=sha(b"wrong")),
            dict(self.request, regions=[dict(self.regions[0], width=64, height=64)]),
            dict(self.request, scope_digest="0" * 64),
        ):
            with self.subTest(request=request), self.assertRaises(Invalid):
                produce(self.worker, request, self.projection)
        self.assertEqual(self.worker.calls, before)
        with self.assertRaises(Invalid):
            FrozenMobileNet(self.weights, sha(b"wrong weight identity"))

    def test_actual_subprocess_recompute_and_exclusive_output(self):
        request_path, projection_path = (
            self.root / "request.json",
            self.root / "projection.json",
        )
        request_path.write_text(json.dumps(self.request))
        projection_path.write_text(json.dumps(self.projection))
        output = self.root / "receipt.json"
        command = [
            sys.executable,
            "-m",
            "perc1.producer",
            "--request",
            str(request_path),
            "--weights",
            str(self.weights),
            "--weights-sha256",
            WEIGHTS_SHA,
            "--projection",
            str(projection_path),
            "--projection-sha256",
            sha(projection_path.read_bytes()),
            "--output",
            str(output),
        ]
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent))
        result = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(output.read_text())
        local = produce(self.worker, self.request, self.projection)
        self.assertNotEqual(observed["worker"]["pid"], os.getpid())
        self.assertEqual(observed["observation"], local["observation"])
        original = output.read_bytes()
        repeated = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=60
        )
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(output.read_bytes(), original)
        wrong = command.copy()
        wrong[wrong.index("--projection-sha256") + 1] = "f" * 64
        wrong[-1] = str(self.root / "wrong-receipt.json")
        rejected = subprocess.run(
            wrong, env=env, capture_output=True, text=True, timeout=60
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("projection file digest mismatch", rejected.stderr)
        self.assertFalse(Path(wrong[-1]).exists())


if __name__ == "__main__":
    unittest.main()
