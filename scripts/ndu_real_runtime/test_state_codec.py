"""Synthetic mechanism tests: real Torch and cold actor processes, no adoption."""

import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from PIL import Image
import torch

from .actor import parameter_sha
from .controllers import ControlPlan
from .metering import canonical_sha, file_sha
from .neural import ReceiptPortfolioModel
from .objective import utility_profile
from .state_codec import (
    MAX_BYTES,
    checkpoint_binding,
    load_checkpoint,
    save_checkpoint,
    validate_continuation,
)


class StateCodecTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        torch.set_num_threads(1)
        torch.manual_seed(17)
        self.model = ReceiptPortfolioModel("ordinary").eval()
        self.plan = ControlPlan(memory_mode="persistent")
        self.control = {
            "control": asdict(self.plan),
            "seed": 19,
            "episode_wall_seconds": 10.0,
            "fixed_schedule": ["WRITE_TEXT", "WRITE_TEXT"],
        }
        self.args = SimpleNamespace(
            operation_id="codec-mechanism",
            expected_weights_sha256="a" * 64,
            core="ordinary",
            controller="tuned_fixed",
            training_exploration=False,
            tesseract=sys.executable,
            tessdata_dir=str(self.root / "ocr"),
            ocr_library_dir=str(self.root / "ocr-lib"),
        )
        (self.root / "ocr").mkdir()
        (self.root / "ocr" / "eng.traineddata").write_bytes(
            b"synthetic mocked OCR resource"
        )
        (self.root / "ocr-lib").mkdir()
        self.packet = {
            "schema": "ndu.real.public-case.v1",
            "case_id": "synthetic",
            "prompt": "Read the company",
            "public_text": "ACME",
            "overview": {},
            "source_size": {"width": 32, "height": 32},
            "initial_delivery": {"text": None, "image": None},
            "requirements": {"text": True, "image": False},
            "action_contract": {},
        }
        self.binding = checkpoint_binding(
            self.args,
            self.packet,
            self.model,
            self.control,
            None,
            parameter_sha(self.model),
        )
        self.state = {
            "schema": "ndu.real.actor-step.v1",
            "case_id": "synthetic",
            "step": 0,
            "remaining_seconds": 10.0,
            "prepared_roi": None,
            "observation": {
                "kind": "overview",
                "path": "overview.png",
                "sha256": "b" * 64,
                "bbox": [0, 0, 32, 32],
            },
            "delivery": {
                "schema": "ndu.real.delivery.v1",
                "case_id": "synthetic",
                "text": None,
                "image": None,
            },
            "text_committed": False,
            "forced_action": None,
        }
        self.action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "WRITE_TEXT",
            "arguments": {"text": "ACME"},
        }
        self.features = torch.arange(252, dtype=torch.float32).reshape(2, 126) / 252
        with torch.inference_mode():
            self.memory = self.model.public_state_step(self.features, [0.0] * 16)[3]
        self.path = self.root / "checkpoint.json"

    def save(self, *, action=None):
        return save_checkpoint(
            self.path, self.binding, self.memory, self.state, action or self.action, {}
        )["sha256"]

    def test_roundtrip_preserves_real_neural_continuation_and_rng(self):
        digest = self.save()
        expected_rng = torch.rand(7)
        with torch.inference_mode():
            expected = self.model.public_state_step(
                self.features, [0.0] * 16, memory=self.memory
            )
        _, restored = load_checkpoint(self.path, digest, self.binding, 1)
        self.assertTrue(torch.equal(torch.rand(7), expected_rng))
        with torch.inference_mode():
            actual = self.model.public_state_step(
                self.features, [0.0] * 16, memory=restored
            )
        for x, y in zip(expected[:3], actual[:3]):
            self.assertTrue(torch.equal(x, y))
        for x, y in zip(expected[3], actual[3]):
            for name in x:
                self.assertTrue(torch.equal(x[name], y[name]))

    def test_wrong_source_model_operation_case_and_step_are_rejected(self):
        digest = self.save()
        for name in (
            "operation_id",
            "case_sha256",
            "weights_sha256",
            "parameters_sha256",
            "sources",
            "runtime",
            "ocr",
        ):
            changed = copy.deepcopy(self.binding)
            changed[name] = "wrong"
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_checkpoint(self.path, digest, changed, 1)
        for sha, step in (("0" * 64, 1), (digest, 0), (digest, 2), (digest, True)):
            with self.subTest(step=step), self.assertRaises(ValueError):
                load_checkpoint(self.path, sha, self.binding, step)

    def test_malformed_tensor_rng_and_extra_or_duplicate_fields_are_rejected(self):
        digest = self.save()
        original = json.loads(self.path.read_text())
        for change in (
            lambda x: x.update(unbound=True),
            lambda x: x.update(torch_rng="AA=="),
            lambda x: x.update(memory=None),
            lambda x: x["memory"][0].update(content=[[float("nan")]]),
        ):
            value = copy.deepcopy(original)
            change(value)
            raw = json.dumps(value).encode()
            self.path.write_bytes(raw)
            with self.assertRaises((ValueError, RuntimeError)):
                load_checkpoint(
                    self.path, hashlib.sha256(raw).hexdigest(), self.binding, 1
                )
        raw = b'{"schema":"duplicate",' + json.dumps(original).encode()[1:]
        self.path.write_bytes(raw)
        with self.assertRaises(ValueError):
            load_checkpoint(self.path, hashlib.sha256(raw).hexdigest(), self.binding, 1)
        self.path.write_bytes(b" " * (MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            load_checkpoint(self.path, digest, self.binding, 1)

    def test_terminal_and_leaf_symlink_do_not_resume(self):
        digest = self.save(
            action={
                "schema": "ndu.real.actor-action.v1",
                "action": "STOP",
                "arguments": {},
            }
        )
        with self.assertRaises(ValueError):
            load_checkpoint(self.path, digest, self.binding, 1)
        link = self.root / "link.json"
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            load_checkpoint(link, digest, self.binding, 1)

    def test_continuation_requires_bound_delivery_and_no_budget_refill(self):
        checkpoint, _ = load_checkpoint(self.path, self.save(), self.binding, 1)
        state = copy.deepcopy(self.state)
        state.update(step=1, remaining_seconds=9.0)
        state["delivery"]["text"] = "ACME"
        validate_continuation(checkpoint, state, canonical_sha(state))
        for mutate in (
            lambda s: s.update(remaining_seconds=11),
            lambda s: s["delivery"].update(text=None),
            lambda s: s["delivery"].update(case_id="other"),
            lambda s: s["observation"].update(path="other.png"),
        ):
            changed = copy.deepcopy(state)
            mutate(changed)
            with self.assertRaises(ValueError):
                validate_continuation(checkpoint, changed, canonical_sha(changed))
        with self.assertRaises(ValueError):
            validate_continuation(checkpoint, state, "0" * 64)

    def test_cold_actor_matches_uninterrupted_and_missing_memory_still_fails(self):
        public = self.root / "public"
        public.mkdir()
        Image.new("RGB", (32, 32), "white").save(public / "overview.png")
        self.packet["overview"] = {"sha256": file_sha(public / "overview.png")}
        (public / "case.json").write_text(json.dumps(self.packet))
        weights = self.root / "weights.pt"
        torch.save(self.model.state_dict(), weights)
        (self.root / "control.json").write_text(json.dumps(self.control))
        deployment = {
            "schema": "ndu.real.deployment-profile.v1",
            "weights_sha256": file_sha(weights),
            "core": "ordinary",
            "memory_mode": "persistent",
            "rubric_sha256": "a" * 64,
            "utility_profile_sha256": canonical_sha(utility_profile(self.plan)),
            "control_profile_sha256": canonical_sha(asdict(self.plan)),
            "recursive_policy_trained": False,
        }
        (self.root / "deployment.json").write_text(json.dumps(deployment))
        first = copy.deepcopy(self.state)
        first["observation"]["sha256"] = self.packet["overview"]["sha256"]
        second = copy.deepcopy(first)
        second.update(step=1, remaining_seconds=9.0)
        second["delivery"]["text"] = "ACME"
        source = Path(__file__).resolve().parents[1]
        env = dict(
            os.environ,
            PYTHONPATH=os.pathsep.join(
                (str(source), str(source.parent), os.environ.get("PYTHONPATH", ""))
            ),
        )
        common = [
            "--public-dir",
            str(public),
            "--weights",
            str(weights),
            "--expected-weights-sha256",
            file_sha(weights),
            "--core",
            "ordinary",
            "--controller",
            "tuned_fixed",
            "--control-plan",
            str(self.root / "control.json"),
            "--deployment-profile",
            str(self.root / "deployment.json"),
            "--operation-id",
            "synthetic-actor",
            "--tesseract",
            sys.executable,
            "--tessdata-dir",
            self.args.tessdata_dir,
            "--ocr-library-dir",
            self.args.ocr_library_dir,
        ]
        # OCR is an explicit synthetic fixture; the actual neural and CLI paths execute.
        script = (
            "from ndu_real_runtime import actor\n"
            "calls = []\n"
            "def fixture_ocr(*args, **kwargs):\n"
            "    calls.append(1)\n"
            "    return [], {'calls': len(calls)}\n"
            "actor.extract_ocr = fixture_ocr\n"
            "actor.main()\n"
        )

        def run(name, states, flags=(), success=True):
            cwd = self.root / name
            cwd.mkdir()
            result = subprocess.run(
                [sys.executable, "-c", script, *common, *flags],
                input="".join(json.dumps(s) + "\n" for s in states),
                text=True,
                capture_output=True,
                cwd=cwd,
                env=env,
                timeout=45,
            )
            self.assertEqual(result.returncode == 0, success, result.stderr)
            return [json.loads(line) for line in result.stdout.splitlines()]

        full = run("full", [first, second], ["--max-decisions", "2"])[-1]
        checkpoints = self.root / "checkpoints"
        checkpoints.mkdir()
        prefix = run(
            "prefix",
            [first],
            ["--max-decisions", "1", "--checkpoint-dir", str(checkpoints)],
        )[-1]
        continuation = [
            "--start-step",
            "1",
            "--max-decisions",
            "1",
            "--resume-checkpoint",
            prefix["checkpoint"]["path"],
            "--expected-checkpoint-sha256",
            prefix["checkpoint"]["sha256"],
            "--expected-continuation-sha256",
            canonical_sha(second),
        ]
        resumed = run("resumed", [second], continuation)[-1]
        ignored = {"meter", "ocr", "checkpoint"}
        self.assertEqual(
            {k: v for k, v in full.items() if k not in ignored},
            {k: v for k, v in resumed.items() if k not in ignored},
        )
        self.assertGreater(resumed["meter"]["costs"]["encoder"], 0)
        run(
            "missing-memory",
            [second],
            ["--start-step", "1", "--max-decisions", "1"],
            success=False,
        )
        # Same pixels can be mapped to distinct source locations. The actor
        # should reuse raw OCR once, but re-encode the new source geometry.
        roi = copy.deepcopy(first)
        roi["observation"].update(kind="roi", bbox=[0, 0, 16, 32])
        roi["forced_action"] = "WRITE_TEXT"
        shifted = copy.deepcopy(second)
        shifted["observation"].update(kind="roi", bbox=[16, 0, 32, 32])
        shifted["forced_action"] = "WRITE_TEXT"
        observed = run(
            "cache-context",
            [roi, shifted],
            ["--max-decisions", "2", "--training-exploration"],
        )[1:]
        self.assertEqual(
            [row["candidate_metadata"][0]["bbox"] for row in observed],
            [[0, 0, 16, 32], [16, 0, 32, 32]],
        )
        self.assertEqual([row["ocr"]["calls"] for row in observed], [1, 1])


if __name__ == "__main__":
    unittest.main()
