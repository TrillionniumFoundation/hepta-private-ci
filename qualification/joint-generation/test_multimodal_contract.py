import copy
import json
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from contracts import ContractError, RunSession, digest
from control import Controller
from model import JointModel
from multimodal_contract import (AudioPayload, MediaEnvelope, Modality, SCHEMA, UnknownModality,
                                 UnsupportedCapability, VideoPayload, dispatch, to_legacy_request)
from serve import infer


def stream(mode, payload, *, start=100, end=100000100):
    return {"stream_id": mode + "-1", "modality": mode,
            "timing": {"clock_id": "capture:1", "sync_group": "clip:1", "start_ns": start, "end_ns": end},
            "payload": payload}


def envelope(streams):
    return {"schema": SCHEMA, "objective_id": "scene-transform-v1", "run_id": "media:1",
            "artifact_sha256": "a" * 64,
            "budget": {"compute_units": 5000, "input_bytes": 65536, "output_bytes": 4096},
            "deadline_ns": 10**18, "decoding": {"mode": "sample", "seed": 42},
            "outputs": ["text", "image"], "streams": streams, "sync_tolerance_ns": 0}


def text_image():
    return envelope([stream("text", {"encoding": "utf-8", "text": "blue cross right"}),
                     stream("image", {"dtype": "float32", "color_space": "RGB", "pixels": np.zeros((8, 8, 3))})])


def audio_video():
    return envelope([stream("audio", {"dtype": "float32", "sample_rate_hz": 16000, "channels": 1,
                                      "samples": np.zeros((1600, 1))}),
                     stream("video", {"dtype": "float32", "color_space": "RGB", "fps_num": 30, "fps_den": 1,
                                      "timestamps_ns": [100, 33333433, 66666766], "frames": np.zeros((3, 2, 2, 3))})])


class MultimodalContractTests(unittest.TestCase):
    def test_wire_json_is_bounded_and_uses_the_same_payload_validation(self):
        value = text_image()
        value["streams"][1]["payload"]["pixels"] = value["streams"][1]["payload"]["pixels"].tolist()
        media = MediaEnvelope.from_json(json.dumps(value).encode(), now_ns=1)
        self.assertEqual(media.streams[0].payload.text, "blue cross right")
        for raw in (b"not json", b"\xff", b" " * (16 * 2**20 + 1)):
            with self.subTest(length=len(raw)), self.assertRaises(ContractError):
                MediaEnvelope.from_json(raw, now_ns=1)

    def test_valid_av_payloads_admit_then_backend_rejects_without_dispatch(self):
        media = MediaEnvelope.parse(audio_video(), now_ns=1)
        self.assertIsInstance(media.streams[0].payload, AudioPayload)
        self.assertIsInstance(media.streams[1].payload, VideoPayload)
        self.assertEqual(media.streams[0].canonical_range(),
                         {"kind": "sample_range", "start": 0, "end": 1600, "sampleRateHz": 16000})
        self.assertEqual(media.streams[1].canonical_range(),
                         {"kind": "frame_range", "start": 0, "end": 3, "timebaseNum": 1, "timebaseDen": 30})
        calls = []
        with self.assertRaises(UnsupportedCapability):
            dispatch(media, calls.append, expected_artifact_sha256="a" * 64, now_ns=1)
        self.assertEqual(calls, [])

    def test_unknown_modality_differs_from_reserved_canonical_profile(self):
        value = text_image()
        value["streams"][0]["modality"] = "hologram"
        with self.assertRaises(UnknownModality):
            MediaEnvelope.parse(value, now_ns=1)
        value["streams"][0]["modality"] = "code_ast"
        with self.assertRaises(UnsupportedCapability) as caught:
            MediaEnvelope.parse(value, now_ns=1)
        self.assertNotIsInstance(caught.exception, UnknownModality)
        value = text_image()
        value["outputs"] = ["sensor"]
        media = MediaEnvelope.parse(value, now_ns=1)
        self.assertEqual(media.outputs, (Modality.SENSOR,))
        with self.assertRaises(UnsupportedCapability):
            to_legacy_request(media, expected_artifact_sha256="a" * 64, now_ns=1)

    def test_clock_identity_and_declared_sync_tolerance(self):
        value = audio_video()
        value["streams"][1]["timing"]["clock_id"] = "capture:2"
        with self.assertRaises(ContractError):
            MediaEnvelope.parse(value, now_ns=1)
        value["streams"][1]["timing"]["sync_group"] = "independent:2"
        MediaEnvelope.parse(value, now_ns=1)  # Explicitly independent groups need no implicit clock conversion.
        value = audio_video()
        timing = value["streams"][1]["timing"]
        timing["start_ns"] += 2; timing["end_ns"] += 2
        value["streams"][1]["payload"]["timestamps_ns"] = [102, 33333435, 66666768]
        with self.assertRaises(ContractError):
            MediaEnvelope.parse(value, now_ns=1)
        value["sync_tolerance_ns"] = 2
        MediaEnvelope.parse(value, now_ns=1)

    def test_sample_and_frame_clock_mismatches_reject(self):
        for field in ("sample_rate", "channels", "audio_end", "frame_order", "frame_count", "frame_rate"):
            value = audio_video()
            audio, video = value["streams"]
            if field == "sample_rate": audio["payload"]["sample_rate_hz"] = 8000
            elif field == "channels": audio["payload"]["channels"] = 2
            elif field == "audio_end": audio["timing"]["end_ns"] += 1
            elif field == "frame_order": video["payload"]["timestamps_ns"][1] = 100
            elif field == "frame_count": video["payload"]["timestamps_ns"].pop()
            else: video["payload"]["fps_num"] = 60
            with self.subTest(field=field), self.assertRaises(ContractError):
                MediaEnvelope.parse(value, now_ns=1)

    def test_tensor_dtype_shape_range_and_finite_bounds(self):
        invalid = [("audio", "samples", np.full((1600, 1), np.nan)),
                   ("audio", "samples", np.full((1600, 1), 1.1)),
                   ("video", "frames", np.zeros((65, 2, 2, 3))),
                   ("video", "frames", np.zeros((3, 2, 2, 2))),
                   ("video", "frames", np.full((3, 2, 2, 3), np.inf))]
        for mode, key, tensor in invalid:
            value = audio_video()
            target = next(s for s in value["streams"] if s["modality"] == mode)
            target["payload"][key] = tensor
            with self.subTest(mode=mode, key=key), self.assertRaises(ContractError):
                MediaEnvelope.parse(value, now_ns=1)
        value = audio_video(); value["streams"][0]["payload"]["dtype"] = "int16"
        with self.assertRaises(ContractError): MediaEnvelope.parse(value, now_ns=1)
        value = text_image(); value["streams"][1]["payload"]["pixels"] = [[[0., 0., 0.]], [[0., 0.]]]
        with self.assertRaises(ContractError): MediaEnvelope.parse(value, now_ns=1)

    def test_aggregate_input_and_common_run_budgets(self):
        value = audio_video(); value["budget"]["input_bytes"] = 6400  # Audio fits, combined clip does not.
        with self.assertRaises(ContractError): MediaEnvelope.parse(value, now_ns=1)
        for key, invalid in (("compute_units", True), ("output_bytes", 2**20 + 1), ("input_bytes", 0)):
            value = text_image(); value["budget"][key] = invalid
            with self.subTest(key=key), self.assertRaises(ContractError): MediaEnvelope.parse(value, now_ns=1)
        value = text_image(); value["deadline_ns"] = 1
        with self.assertRaises(ContractError): MediaEnvelope.parse(value, now_ns=1)

    def test_labels_unknown_fields_and_duplicate_streams_reject(self):
        for where in ("envelope", "stream", "payload", "timing"):
            value = text_image()
            target = value if where == "envelope" else value["streams"][0]
            if where in ("payload", "timing"): target = target[where]
            target["labels"] = [11]
            with self.subTest(where=where), self.assertRaises(ContractError): MediaEnvelope.parse(value, now_ns=1)
        value = text_image(); value["streams"].append(copy.deepcopy(value["streams"][0]))
        with self.assertRaises(ContractError): MediaEnvelope.parse(value, now_ns=1)
        value = text_image(); value["outputs"].append("text")
        with self.assertRaises(ContractError): MediaEnvelope.parse(value, now_ns=1)

    def test_payload_copy_and_backend_profile_artifact_binding(self):
        value = text_image(); original = value["streams"][1]["payload"]["pixels"]
        media = MediaEnvelope.parse(value, now_ns=1)
        original[:] = 1
        self.assertEqual(float(media.streams[1].payload.pixels.sum()), 0.)
        with self.assertRaises(ValueError): media.streams[1].payload.pixels[0, 0, 0] = 1
        with self.assertRaises(ContractError): to_legacy_request(media, expected_artifact_sha256="b" * 64, now_ns=1)
        with self.assertRaises(ContractError): to_legacy_request(media, expected_artifact_sha256="a" * 64, now_ns=media.deadline_ns)
        value = text_image(); value["streams"][1]["payload"]["pixels"] = np.zeros((16, 16, 3))
        with self.assertRaises(UnsupportedCapability):
            to_legacy_request(MediaEnvelope.parse(value, now_ns=1), expected_artifact_sha256="a" * 64, now_ns=1)

    def test_adapter_dispatches_actual_rgb8_backend_and_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); bundle = root / "bundle"; bundle.mkdir()
            model = JointModel(202, 12, 192, hidden=4)
            model.save(bundle / "model.npz")
            controller = Controller(12, np.zeros(31), np.ones(31), np.zeros(31), .2, np.array([.2, .2]))
            np.savez_compressed(bundle / "controller.npz", **controller.to_arrays())
            manifest = {"schema": "hepta.joint-generation.bundle.v1", "input_profile": "rgb8-instruction10-v1",
                        "model_digest": model.digest(), "utility_profile": {"rho": 1.5, "compute_price": .02,
                        "behavior_policy": "independent-categorical-v1"}}
            for name in ("model", "controller"): manifest[name + "_sha256"] = digest((bundle / (name + ".npz")).read_bytes())
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            artifact = digest(json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
            value = text_image(); value["artifact_sha256"] = artifact
            value["deadline_ns"] = time.monotonic_ns() + 60 * 10**9
            media = MediaEnvelope.parse(value, now_ns=time.monotonic_ns())
            request = to_legacy_request(media, expected_artifact_sha256=artifact, now_ns=time.monotonic_ns())
            self.assertNotIn("labels", request)
            output = dispatch(media, lambda req: infer(bundle, req, root / "output"),
                              expected_artifact_sha256=artifact, now_ns=time.monotonic_ns())
            self.assertEqual(output["bundle_digest"], artifact)
            self.assertLessEqual(sum(output["spent"][k] for k in ("controller", "generator")), media.budget.compute_units)
            checkpoint = json.loads((root / "output/checkpoint.json").read_text())
            restored = RunSession.restore(checkpoint, expected_artifact_sha256=artifact, now_ns=time.monotonic_ns())
            self.assertEqual(restored.prefix("text").decode(), output["caption"])
            self.assertEqual(digest(restored.prefix("image")), output["image_sha256"])


if __name__ == "__main__":
    unittest.main()
