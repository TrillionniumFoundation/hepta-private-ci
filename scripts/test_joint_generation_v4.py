"""Synthetic wiring and native/PyTorch parity; no semantic capability result.

Run with ``JOINT_V4_NATIVE_BINARY=/absolute/hepta-joint-propose`` to require
native execution and standard media decoding in addition to gradient checks.
"""

from dataclasses import replace
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave

import torch

from scripts.joint_generation_v4_io import (
    DeliveryObservation,
    framed_media,
    read_packet,
    read_response,
    request_bytes,
)
from scripts.joint_generation_v4_model import JointGeneratorV4, public_packet


def public_input(text="Hepta 世界"):
    data = {
        name: torch.zeros(shape, dtype=torch.float64)
        for name, shape in (
            ("image", (1, 3, 16, 16)),
            ("image_mask", (1, 3, 16, 16)),
            ("audio", (1, 1024)),
            ("audio_mask", (1, 1024)),
            ("video", (1, 4, 3, 16, 16)),
            ("video_mask", (1, 4, 3, 16, 16)),
        )
    }
    data["tokens"] = torch.tensor([list(text.encode("utf-8"))], dtype=torch.float64)
    return data


def model():
    with torch.random.fork_rng():
        torch.manual_seed(811)
        return JointGeneratorV4()


class TorchGeneratorTests(unittest.TestCase):
    def test_order_and_persistent_reset_have_causal_effects(self):
        generator = model()
        self.assertFalse(
            torch.equal(
                generator.encode(public_input("ab")).context,
                generator.encode(public_input("ba")).context,
            )
        )
        public = public_input()
        initial = generator.encode(public)
        once = generator.advance(initial, "shared", public)
        twice = generator.advance(once, "shared", public)
        generator.core_state_profile = "reset-each-action-v1"
        reset_once = generator.advance(generator.encode(public), "shared", public)
        reset_twice = generator.advance(reset_once, "shared", public)
        torch.testing.assert_close(once.shared, reset_once.shared, rtol=0, atol=0)
        self.assertFalse(torch.equal(twice.shared, reset_twice.shared))

    def test_text_gradient_reaches_encoder_and_continuous_core(self):
        generator, public = model(), public_input()

        def loss():
            state = generator.advance(generator.encode(public), "shared", public)
            state = generator.advance(state, "text", public)
            return generator.text_loss(state, "Hepta🙂")[0]

        value = loss()
        value.backward()
        for parameter in (
            generator.token_encoder.weight,
            generator.text_recurrent.weight,
            generator.encoder_fusion[0].weight,
            generator.core.layers[0].drift_bias,
        ):
            self.assertIsNotNone(parameter.grad)
            self.assertTrue(bool(torch.isfinite(parameter.grad).all()))
            self.assertGreater(float(parameter.grad.abs().max()), 1e-12)
        parameter = generator.text_recurrent.weight
        coordinate = divmod(int(parameter.grad.abs().argmax()), parameter.shape[1])
        analytic = float(parameter.grad[coordinate])
        original = float(parameter.detach()[coordinate])
        epsilon = 1e-6
        with torch.no_grad():
            parameter[coordinate] = original + epsilon
            plus = float(loss())
            parameter[coordinate] = original - epsilon
            minus = float(loss())
            parameter[coordinate] = original
        finite_difference = (plus - minus) / (2 * epsilon)
        self.assertAlmostEqual(analytic, finite_difference, delta=2e-7)

    def test_packet_export_and_owner_features_bind_actual_observation(self):
        generator = model()
        metadata, tensors = read_packet(generator.export_weights())
        self.assertEqual(metadata["kind"], "joint-generator-weights-v4")
        for name, value in generator.state_dict().items():
            torch.testing.assert_close(tensors[name], value.detach(), rtol=0, atol=0)
        a = DeliveryObservation(
            8, 1, 10000, 9000, bytes([3]) * 32, (0, 0, 0, 2), (b"", b"", b"", b"ab")
        )
        b = replace(a, committed=(b"", b"", b"", b"ba"))
        state = generator.encode(public_input())
        first, second = generator.inspect(state, a), generator.inspect(state, b)
        for name in ("actor.logits", "critic", "delivery_critic"):
            self.assertFalse(torch.equal(first[name], second[name]))
        self.assertEqual(first["policy.probabilities"][0, 2:4].tolist(), [0.0, 0.0])
        with self.assertRaises(ValueError):
            replace(a, budget_remaining=a.budget_total + 1)


@unittest.skipUnless(
    os.environ.get("JOINT_V4_NATIVE_BINARY"), "native binary not selected"
)
class NativeGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.generator = model()
        self.public = public_input()
        self.weights = self.generator.export_weights()
        self.public_bytes = public_packet(self.public)
        self.owner = DeliveryObservation(15, 0, 1_000_000, 1_000_000, bytes([9]) * 32)
        self.binary = str(
            Path(os.environ["JOINT_V4_NATIVE_BINARY"]).resolve(strict=True)
        )

    def invoke(self, state, prefix, command):
        data = request_bytes(
            self.weights, self.public_bytes, state, prefix, command, self.owner
        )
        process = subprocess.run(
            [self.binary], input=data, capture_output=True, timeout=30, check=False
        )
        self.assertEqual(
            process.returncode, 0, process.stderr.decode("utf-8", errors="replace")
        )
        self.owner = replace(
            self.owner, budget_remaining=self.owner.budget_remaining - 1000
        )
        return read_response(process.stdout)

    def assert_state(self, encoded, state):
        _, actual = read_packet(encoded)
        expected = {
            "context": state.context,
            "shared": state.shared,
            "slots": state.slots,
            "feedback": state.feedback,
            "text.hidden": state.text_hidden,
        }
        for index, layer in enumerate(state.core):
            expected.update(
                {f"core.{index}.{name}": tensor for name, tensor in layer.items()}
            )
        for name, value in expected.items():
            torch.testing.assert_close(
                actual[name],
                value.detach().flatten(),
                rtol=2e-10,
                atol=5e-12,
                msg=lambda message: f"{name}: {message}",
            )

    def test_native_initialization_recurrence_and_resumed_text_match_python(self):
        initial = self.invoke(b"", b"", b"\x00" + struct.pack("<Q", 17) + b"\x00")
        state = self.generator.encode(self.public)
        self.assert_state(initial["state"], state)
        for action, index in (("shared", 0), ("text", 4)):
            initial = self.invoke(initial["state"], b"", bytes([1, index]))
            state = self.generator.advance(state, action, self.public)
            self.assert_state(initial["state"], state)
        partial = self.invoke(initial["state"], b"", b"\x03\x03" + struct.pack("<I", 7))
        cursors, files = framed_media(partial["delta"])
        self.assertEqual(cursors, (0, 0, 0, 7))
        for byte in files[3]:
            state = self.generator.consume_byte(state, byte)
        self.assert_state(partial["state"], state)
        resumed = self.invoke(
            partial["state"], partial["delta"], b"\x03\x03" + struct.pack("<I", 3)
        )
        _, complete = framed_media(partial["delta"] + resumed["delta"])
        for byte in complete[3][len(files[3]) :]:
            state = self.generator.consume_byte(state, byte)
        self.assert_state(resumed["state"], state)

    def test_native_outputs_open_as_standard_image_audio_and_video(self):
        from PIL import Image

        initial = self.invoke(b"", b"", b"\x00" + struct.pack("<Q", 17) + b"\x00")
        advanced = self.invoke(initial["state"], b"", b"\x01\x00")
        stopped = self.invoke(advanced["state"], b"", b"\x01\x06")
        self.assertTrue(stopped["stopped"])
        cursors, files = framed_media(stopped["delta"])
        self.assertEqual(cursors, (16, 1024, 4, 128))
        with Image.open(io.BytesIO(files[0])) as image:
            image.load()
            self.assertEqual(
                (image.format, image.size, image.mode), ("PPM", (16, 16), "RGB")
            )
        with wave.open(io.BytesIO(files[1]), "rb") as audio:
            self.assertEqual(
                (
                    audio.getnchannels(),
                    audio.getframerate(),
                    audio.getnframes(),
                    audio.getsampwidth(),
                ),
                (1, 16000, 1024, 2),
            )
            self.assertEqual(len(audio.readframes(1024)), 2048)
        self.assertEqual(len(files[3].decode("utf-8")), 128)
        probe = shutil.which("ffprobe")
        self.assertIsNotNone(probe, "ffprobe is required for independent Y4M decoding")
        with tempfile.TemporaryDirectory(prefix="joint-v4-media-") as directory:
            video = Path(directory) / "generated.y4m"
            video.write_bytes(files[2])
            process = subprocess.run(
                [
                    probe,
                    "-v",
                    "error",
                    "-count_frames",
                    "-show_streams",
                    "-of",
                    "json",
                    str(video),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            stream = json.loads(process.stdout)["streams"][0]
            self.assertEqual(
                (
                    stream["width"],
                    stream["height"],
                    stream["pix_fmt"],
                    stream["nb_read_frames"],
                ),
                (16, 16, "yuv444p", "4"),
            )


if __name__ == "__main__":
    unittest.main()
