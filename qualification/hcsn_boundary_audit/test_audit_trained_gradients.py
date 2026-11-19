import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from qualification.hcsn_boundary_audit.audit_trained_gradients import (
    TASKS, FactorialModel, admit, audit_episode, load_model, source_identity, tensor_digest,
)


class TrainedBoundaryAuditTests(unittest.TestCase):
    def test_same_count_wrong_roster_or_model_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            pilot, plan = Path(temporary), {"seeds": [11]}
            data = json.dumps({"development": [{"task": task, "id": task} for task in TASKS]}).encode()
            (pilot / "DATA.json").write_bytes(data)
            (pilot / "PLAN.json").write_text(json.dumps(plan))
            sources = source_identity()
            for wrong_roster in (True, False):
                seed = 23 if wrong_roster else 11
                runs = [dict(seed=seed, arm=arm, status="completed",
                             model_configuration=dict(seed=23, arm=arm))
                        for arm in ("c0_b1", "c1_b1")]
                summary = dict(schema="hcsn-boundary-factorial-pilot-v1",
                    configuration=plan, source_before=sources, source_after=sources,
                    data_sha256=hashlib.sha256(data).hexdigest(), runs=runs)
                raw = json.dumps(summary).encode()
                (pilot / "SUMMARY.json").write_bytes(raw)
                with self.assertRaisesRegex(ValueError, "roster|run seed/arm identity"):
                    admit(pilot, hashlib.sha256(raw).hexdigest(), {})

    def test_changed_checkpoint_is_rejected_before_weights_loader(self):
        with tempfile.TemporaryDirectory() as temporary:
            pilot = Path(temporary)
            directory = pilot / "seed11-c0_b1"
            directory.mkdir()
            run = dict(seed=11, arm="c0_b1", checkpoint_sha256="0" * 64)
            (directory / "result.json").write_text(json.dumps(run))
            (directory / "checkpoint.pt").write_bytes(b"changed checkpoint bytes")
            with mock.patch("torch.load") as loader:
                with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                    load_model(pilot, run, "unused", {})
                loader.assert_not_called()

    def test_failed_real_fd_forward_restores_exact_boundary_and_model(self):
        model = FactorialModel(11, "c0_b1")
        before = tensor_digest(model.state_dict())
        episode = dict(id="fault-injection", task="fault-injection",
                       x=[[0.] * 21, [0.] * 21], dt=[.04, .02], y=[-1, 0])
        original_forward, calls = model.forward, []

        def fail_after_ad(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("injected FD forward failure")
            return original_forward(*args, **kwargs)

        with mock.patch.object(model, "forward", side_effect=fail_after_ad):
            result = audit_episode(model, episode)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_message"], "injected FD forward failure")
        self.assertEqual(result["forward_attempts"], 2)
        self.assertEqual(result["forward_completed"], 1)
        self.assertEqual(result["backward_completed"], 1)
        self.assertTrue(result["model_unchanged"])
        self.assertEqual(tensor_digest(model.state_dict()), before)
