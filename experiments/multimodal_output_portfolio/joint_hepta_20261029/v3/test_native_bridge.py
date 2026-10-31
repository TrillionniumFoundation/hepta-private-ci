"""Independent Torch math, actual Rust codecs and crash/restart prefix tests."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave

import numpy as np
from PIL import Image
import torch

from ..mechanism_data import batch
from ..model import JointGenerator, supervised_loss
from .model import JointGenerator as GenerationV3
from .native_bridge import NativeSession, build_native, differential, export_model, pack, unpack


class NativeContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("HEPTA_NATIVE_RUSTC") or shutil.which("rustc")
        if not compiler:
            raise unittest.SkipTest("A verified local rustc is required for native execution")
        cls.workspace = tempfile.TemporaryDirectory(prefix="hepta-native-v3-tests-")
        cls.root = Path(cls.workspace.name)
        cls.binary, cls.build = build_native(cls.root / "native", rustc=compiler)
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def fixture(self, name, *, seed=31, sampler="mean", model=None):
        torch.manual_seed(seed)
        model = model or JointGenerator(width=8)
        public, target = batch([3])
        wp, ip, manifest = export_model(model, public, self.root / (name + "-export"))
        session = NativeSession(self.binary, wp, ip, self.root / name)
        session.create(seed=seed, sampler=sampler)
        return model, public, target, session, manifest

    def test_native_sha_and_packet_roundtrip(self):
        payload = self.root / "hash-input"
        payload.write_bytes(b"abc")
        result = subprocess.run([str(self.binary), "hash", str(payload)], capture_output=True,
                                text=True, check=True)
        self.assertEqual(result.stdout.strip(), hashlib.sha256(b"abc").hexdigest())
        original = {"x": np.array([[1.2, -4.0], [0.0, 5.0]])}
        metadata, tensors = unpack(pack({"source": "actual"}, original))
        self.assertEqual(metadata, {"source": "actual"})
        np.testing.assert_array_equal(tensors["x"], original["x"])

    def test_complete_forward_profiles_and_real_parameter_update(self):
        public, target = batch([3])
        for mode, boundary, depth in [("dual", "direct", 2), ("dual", "fixed", 1),
                                     ("ordinary", "direct", 2), ("single", "direct", 1),
                                     ("no_adaptation", "direct", 1)]:
            torch.manual_seed(91)
            model = JointGenerator(width=8, depth=depth, mode=mode, boundary=boundary)
            before = {k: v.detach().clone() for k, v in model.state_dict().items()}
            optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
            for _ in range(3):
                state = model.encode(public)
                state, _ = model.advance(state, "shared", public)
                loss = supervised_loss(model, state, target)
                optimizer.zero_grad(set_to_none=True); loss.backward(); optimizer.step()
            self.assertTrue(any(not torch.equal(before[k], v) for k, v in model.state_dict().items()))
            result = differential(model, public, self.root / f"diff-{mode}-{boundary}", self.binary)
            self.assertTrue(result["passed"], result)
            self.assertLess(result["maximum_fp64_absolute"], 1e-9)
            self.assertLess(result["maximum_fp32_absolute"], 5e-5)

    def test_native_actor_executes_selected_action_and_initial_stop(self):
        model, public, _, session, _ = self.fixture("actor")
        _, snapshot = session.inspect()
        selected = int(np.argmax(snapshot["policy.probabilities"]))
        expected = ("shared", "image", "audio", "video", "text", "verify", "stop")[selected]
        result = session.auto()
        self.assertEqual(result["argument"], expected)
        _, _, _, stop, _ = self.fixture("initial-stop")
        self.assertTrue(stop.step("stop")["stopped"])
        with self.assertRaisesRegex(RuntimeError, "illegal continuation"):
            stop.step("shared")

    def test_duplicate_verify_mask_tracks_content_revision(self):
        model = GenerationV3(width=8, verify_mode="deduplicate")
        _, public, _, session, _ = self.fixture("duplicate-verify", model=model)
        state = model.encode(public)
        session.step("verify"); state, _ = model.advance(state, "verify", public)
        metadata, actual = session.inspect()
        self.assertEqual(metadata["verified_revision"], str(state.verified_revision))
        self.assertEqual(actual["policy.probabilities"][5], 0)
        self.assertEqual(model.policy(state, 1.0)[0].exp()[0, 5].item(), 0)
        with self.assertRaisesRegex(RuntimeError, "redundant verification masked"):
            session.step("verify")
        session.commit("audio", 1)
        self.assertEqual(session.inspect()[1]["policy.probabilities"][5], 0)
        session.step("image"); state, _ = model.advance(state, "image", public)
        self.assertGreater(session.inspect()[1]["policy.probabilities"][5], 0)
        session.step("verify"); state, _ = model.advance(state, "verify", public)
        metadata, _ = session.inspect()
        self.assertEqual(metadata["content_revision"], str(state.content_revision))
        self.assertEqual(metadata["verified_revision"], str(state.verified_revision))

    def test_streaming_commit_survives_content_changes_and_new_processes(self):
        _, _, _, session, _ = self.fixture("stream")
        session.step("shared")
        _, initial = session.inspect()
        for modality, count in [("image", 5), ("audio", 128), ("video", 1), ("text", 1)]:
            session.commit(modality, count)
        _, committed = session.inspect()
        image = np.rint(1 / (1 + np.exp(-initial["output.image"])) * 255).astype("u1")
        image = image.reshape(3, 16, 16).transpose(1, 2, 0).tobytes()
        self.assertEqual(committed["prefix.image"].astype("u1").tobytes(), image[:5*48])
        session.step("image"); session.step("verify")
        reopened = NativeSession(session.binary, session.weights, session.public, session.directory)
        reopened.refresh()
        _, restored = reopened.inspect()
        for modality in ("image", "audio", "video", "text"):
            np.testing.assert_array_equal(restored[f"prefix.{modality}"], committed[f"prefix.{modality}"])
        for modality, count in [("image", 11), ("audio", 896), ("video", 3), ("text", 1)]:
            reopened.commit(modality, count)
        reopened.step("stop")
        _, terminal = reopened.inspect()
        output = self.root / "stream-output"
        manifest = reopened.export(output)
        for name, expected in manifest["files"].items():
            self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), expected)
        with Image.open(output / "image.png") as picture:
            self.assertEqual(picture.convert("RGB").tobytes(), terminal["prefix.image"].astype("u1").tobytes())
        with wave.open(str(output / "audio.wav")) as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 2048))
            self.assertEqual(audio.readframes(1024), terminal["prefix.audio"].astype("u1").tobytes())
        with Image.open(output / "video.gif") as video:
            frames = []
            for index in range(video.n_frames):
                video.seek(index); frames.append(video.convert("RGB").tobytes())
                self.assertEqual(video.info["duration"], 120)
            self.assertEqual(b"".join(frames), terminal["prefix.video"].astype("u1").tobytes())
        self.assertEqual((output / "text.txt").read_bytes(), terminal["prefix.text"].astype("u1").tobytes())

    def test_commit_faults_and_stale_predecessor(self):
        _, _, _, session, _ = self.fixture("crash")
        original = session.refresh()
        failed = session.commit("audio", 64, fault="after_chunk")
        self.assertEqual(failed.returncode, 75)
        self.assertEqual(session.refresh(), original)
        session.commit("audio", 64)
        previous = session.head
        failed = session.commit("audio", 64, fault="after_event")
        self.assertEqual(failed.returncode, 76)
        status = session.refresh()
        self.assertEqual(status["cursors"]["audio"], 128)
        self.assertNotEqual(previous, status["head"])
        rejected = session.command("commit", previous, "audio", 1, check=False)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("stale expected predecessor", rejected.stderr)
        self.assertEqual(session.refresh(), status)

    def test_model_drift_chunk_corruption_and_live_writer_reject(self):
        _, _, _, session, _ = self.fixture("integrity")
        with (session.directory / "writer.lock").open("rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            attempt = session.command("step", session.head, "shared", check=False)
            self.assertEqual(attempt.returncode, 2)
            self.assertIn("concurrent native writer", attempt.stderr)
        session.commit("image", 1)
        weight_bytes = session.weights.read_bytes()
        metadata, tensors = unpack(weight_bytes)
        tensors["emissions.text.bias"][0] += 0.1
        session.weights.write_bytes(pack(metadata, tensors))
        with self.assertRaisesRegex(RuntimeError, "identity drift"):
            session.refresh()
        session.weights.write_bytes(weight_bytes)
        chunk = next((session.directory / "chunks").glob("*.bin"))
        chunk.write_bytes(chunk.read_bytes()[:-1] + b"x")
        with self.assertRaisesRegex(RuntimeError, "chunk missing or changed"):
            session.refresh()

    def test_native_sampler_is_chunk_partition_invariant(self):
        _, _, _, full, _ = self.fixture("sample-full", seed=89, sampler="splitmix-normal-v1")
        _, _, _, split, _ = self.fixture("sample-split", seed=89, sampler="splitmix-normal-v1")
        for session in (full, split):
            session.step("shared")
        for modality, count in [("image", 16), ("audio", 1024), ("video", 4), ("text", 2)]:
            full.commit(modality, count)
            split.commit(modality, count // 2); split.commit(modality, count - count // 2)
        _, one = full.inspect(); _, two = split.inspect()
        for modality in ("image", "audio", "video", "text"):
            np.testing.assert_array_equal(one[f"prefix.{modality}"], two[f"prefix.{modality}"])

    def test_external_head_detects_whole_suffix_loss(self):
        _, _, _, session, _ = self.fixture("suffix-loss")
        session.commit("audio", 64)
        retained_head = session.head
        session.refresh(expected_head=retained_head)
        (session.directory / "events" / "00000001.hps").unlink()
        with self.assertRaisesRegex(RuntimeError, "independent head witness mismatch"):
            session.refresh(expected_head=retained_head)


if __name__ == "__main__":
    unittest.main()
