"""Bounded engineering tests against the pinned real N8 parent; no fitting.

Requires explicit HEPTA_PROFILE_MANIFEST, HEPTA_PROFILE_SHA256 and
HEPTA_PROFILE_MATERIAL_ROOT. Missing materials fail, rather than skip as a pass.
Run this file in its own process; do not preload a live qualification package.
"""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

from numeric_runner import TASK_SCHEMA, validate_task
from profile_io import Refused, canonical, sha
from small_hcsn_profile import STATE_FIELDS, export_candidate, load_profile

PARENT_SHA256 = "0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f"
COORDINATE_SHA256 = "9ad4d74e13aef6822bf4a24de89f1bcd794d4907aa9fd2924b027ccf501f307b"


def numeric_input():
    # Label-free deterministic numeric stimulus, not an A/B corpus or accuracy test.
    return [[[0.20 if tick == 0 else 0.0, (-0.1 if batch else 0.15) if tick == 6 else 0.0,
              float(tick == 0), float(tick == 6), tick / 11, 0.01 * (batch - 0.5)]
             for batch in range(2)] for tick in range(12)]


class NativeProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest_path = os.environ["HEPTA_PROFILE_MANIFEST"]
        cls.manifest_sha256 = os.environ["HEPTA_PROFILE_SHA256"]
        cls.root = os.environ["HEPTA_PROFILE_MATERIAL_ROOT"]
        cls.profile = load_profile(cls.manifest_path, cls.manifest_sha256, cls.root)
        if cls.profile.candidate_sha256 != PARENT_SHA256:
            raise AssertionError("engineering registration requires the real sealed N8/S271901 parent")

    def task(self, x, initial):
        return {"schema": TASK_SCHEMA, "task_id": "numeric-engineering-only",
                "profile_sha256": self.manifest_sha256, "candidate_sha256": PARENT_SHA256,
                "x": x, "initial": initial}

    def invoke_cold(self, base, name, task, state_root):
        task_file = base / (name + ".json")
        task_file.write_bytes(canonical(task) + b"\n")
        output = base / name
        command = [sys.executable, "-B", str(Path(__file__).with_name("numeric_runner.py")),
                   "--profile", self.manifest_path, "--profile-sha256", self.manifest_sha256,
                   "--material-root", self.root, "--task", str(task_file),
                   "--task-sha256", sha(task_file.read_bytes()), "--state-root", str(state_root),
                   "--output", str(output)]
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True,
                                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            try:
                process.wait(timeout=55)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            self.assertLessEqual(stdout.tell(), 32768)
            self.assertLessEqual(stderr.tell(), 32768)
            stderr.seek(0)
            self.assertEqual(process.returncode, 0, stderr.read(32768).decode(errors="replace"))
            stdout.seek(0)
            pin = json.loads(stdout.read(32768))
        result_raw = (output / pin["path"]).read_bytes()
        self.assertEqual(sha(result_raw), pin["sha256"])
        self.assertEqual(len(result_raw), pin["bytes"])
        return output, json.loads(result_raw)

    def test_raw_complete_model_and_input_contract(self):
        profile = self.profile
        self.assertEqual(profile.constructor, "plain_linear")
        self.assertEqual(profile.manifest["origin"]["coordinate_candidate_sha256"], COORDINATE_SHA256)
        self.assertEqual(profile.current_state_sha256(), profile.model_state_sha256)
        self.assertIn("readout.weight", profile.model.state_dict())
        self.assertNotIn("readout.mean", profile.model.state_dict())
        task = self.task(numeric_input(), {"kind": "margin", "margin": [0.55, 0.72]})
        self.assertEqual(validate_task(task), 2)
        task["targets"] = [0, 1]
        with self.assertRaises(Refused):
            validate_task(task)

    def test_real_cold_continuation_at_odd_clock(self):
        profile, x = self.profile, numeric_input()
        torch = profile.torch
        margin = torch.tensor([[0.55], [0.72]], dtype=torch.float64)
        with torch.no_grad():
            logits, features, final = profile.forward(torch.tensor(x, dtype=torch.float64),
                                                       profile.initial_state(2, margin))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_dir, first = self.invoke_cold(
                base, "first", self.task(x[:5], {"kind": "margin", "margin": [0.55, 0.72]}), base)
            second_dir, second = self.invoke_cold(
                base, "second", self.task(x[5:], {"kind": "resume", "artifact": first["population"]}), first_dir)
            self.assertEqual((first["start_step"], first["end_step"],
                              second["start_step"], second["end_step"]), (0, 5, 5, 12))
            for result in (first, second):
                self.assertEqual(result["candidate_sha256"], PARENT_SHA256)
                self.assertEqual(result["model_state_sha256"], profile.model_state_sha256)
                self.assertEqual(result["source_binding_sha256"], profile.source_binding_sha256)
                self.assertEqual(result["diagnostics_scope"], "this_call_only")
                self.assertFalse(result["production_adoption"])
                self.assertFalse(result["real_cross_user_acceptance"])
            for key, expected in (("logits", logits), ("features", features)):
                resumed = torch.tensor(first[key] + second[key], dtype=torch.float64)
                torch.testing.assert_close(resumed, expected, rtol=1e-11, atol=1e-12)
            restored = profile.load_state(second["population"], second_dir)
            self.assertEqual(restored.step, final.step)
            self.assertEqual(restored.config, final.config)
            for field in STATE_FIELDS:
                torch.testing.assert_close(getattr(restored, field), getattr(final, field),
                                           rtol=1e-11, atol=1e-12)
            # Per-call diagnostics are not a cumulative physical state.

    def test_state_rejects_wrong_identity_and_missing_tensor(self):
        profile = self.profile
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            initial = profile.initial_state(2, profile.torch.tensor([[0.55], [0.72]], dtype=profile.torch.float64))
            pin = profile.save_state(initial, base / "state.pt")
            payload = profile.torch.load(base / pin["path"], map_location="cpu", weights_only=True)
            for name in ("candidate", "message"):
                damaged = copy.deepcopy(payload)
                if name == "candidate":
                    damaged["candidate_sha256"] = "1" * 64
                else:
                    del damaged["tensors"]["message"]
                path = base / (name + ".pt")
                profile.torch.save(damaged, path)
                raw = path.read_bytes()
                with self.assertRaises(Refused):
                    profile.load_state({"path": path.name, "bytes": len(raw), "sha256": sha(raw)}, base)

    def test_export_refuses_unregistered_or_frozen_changes(self):
        profile = self.profile
        state = {name: value.detach().clone() for name, value in profile.model.state_dict().items()}
        coordinate = {"name": "readout.weight", "flat_index": 0, "scale": 1.0}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "never-written.pt"
            with self.assertRaises(Refused):
                export_candidate(profile, state, "1" * 64, output, coordinates=[coordinate])
            state["fixed_boundary"][0] += 1e-4
            with self.assertRaises(Refused):
                export_candidate(profile, state, "1" * 64, output, coordinates=[coordinate])
            with self.assertRaises(Refused):
                export_candidate(profile, state, "1" * 64, output,
                                 coordinates=[{**coordinate, "scale": -1.0}])
            with self.assertRaises(Refused):
                export_candidate(profile, state, "1" * 64, output,
                                 coordinates=[{"name": "raw_boundary", "flat_index": 0, "scale": 1.0}])
            self.assertFalse(output.exists())
        profile.require_frozen()


if __name__ == "__main__":
    unittest.main()
