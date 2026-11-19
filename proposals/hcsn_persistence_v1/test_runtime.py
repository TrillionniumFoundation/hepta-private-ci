"""Torch integration on a materialized successor, using synthetic state only."""

import importlib
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

from .materialize import materialize


@unittest.skipUnless(importlib.util.find_spec("torch"), "requires a Torch test runtime")
class SuccessorRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hcsn-persistence-source-")
        cls.source = Path(cls.temporary.name) / "successor"
        materialize(Path(__file__).resolve().parents[2], cls.source)
        sys.path.insert(0, str(cls.source))
        cls.io = importlib.import_module("c2_io")
        cls.controller = importlib.import_module("c2_controller")
        cls.runner = importlib.import_module("c2_runner")
        cls.journal = importlib.import_module("hcsn_persistence_v1.journal")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(cls.source))
        cls.temporary.cleanup()

    def test_checkpoint_restores_tensor_optimizer_and_rng_before_publication(self):
        import torch

        torch.manual_seed(707)
        model = torch.nn.Linear(2, 1).double()
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
        model(torch.ones(3, 2, dtype=torch.float64)).sum().backward()
        optimizer.step()
        state = dict(
            model=model.state_dict(),
            optimizer=optimizer.state_dict(),
            torch_rng=torch.get_rng_state(),
            order_rng=random.Random(91).getstate(),
            epochs_completed=1,
            main_updates=1,
            data_manifest_sha256="synthetic-fixture",
        )
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "one.pt"
            digest = self.io.immutable_checkpoint(checkpoint, state)
            self.assertEqual(digest, self.io.identity(checkpoint))
            restored = torch.load(checkpoint, weights_only=True)
            self.assertTrue(self.io.state_equal(restored, state))
            with self.assertRaises(FileExistsError):
                self.io.immutable_checkpoint(checkpoint, state)
            self.assertEqual(digest, self.io.identity(checkpoint))

    def test_partial_torch_serialization_has_no_final_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "interrupted.pt"

            def fail_save(value, stream):
                stream.write(b"partial-checkpoint")
                raise OSError("synthetic serialization failure")

            with patch.object(self.io.torch, "save", side_effect=fail_save):
                with self.assertRaises(OSError):
                    self.io.immutable_checkpoint(checkpoint, {"epoch": 2})
            self.assertFalse(checkpoint.exists())

    def test_terminal_gate_rejects_unclosed_or_unbound_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            path = output / "result.json"
            path.write_text(
                json.dumps(
                    {
                        "persistence_schema": "hcsn-persistence-v1",
                        "status": "completed_development",
                    }
                )
            )
            writer = self.journal.ReceiptJournal(output / "events.jsonl")
            writer.append({"kind": "finished", "status": "completed_development"})
            before = dict(
                name="synthetic",
                returncode=0,
                child_cpu_seconds=1.0,
                process_started=True,
                child_terminal_unknown=False,
                pid=os.getpid(),
                process_identity=self.journal.process_identity(),
            )
            rejected = self.controller.terminal_result_gate(before, path, {}, {})
            self.assertEqual(rejected["status"], "failed_terminal_evidence")
            self.assertFalse(rejected["terminal_evidence_complete"])
            self.assertEqual(rejected["child_cpu_seconds"], 1.0)
            writer.close()
            rejected = self.controller.terminal_result_gate(before, path, {}, {})
            self.assertIn(
                "terminal journal index differs", rejected["terminal_evidence_error"]
            )
            self.assertFalse(rejected["terminal_evidence_complete"])

    def test_manifest_omission_of_runtime_dependency_is_rejected(self):
        path = self.source / "PROGRAM-MANIFEST.json"
        original = path.read_bytes()
        try:
            manifest = json.loads(original)
            del manifest["files"]["hcsn_persistence_v1/journal.py"]
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "lacks execution inputs"):
                self.runner.bind_program(path)
        finally:
            path.write_bytes(original)
        self.runner.bind_program(path)


if __name__ == "__main__":
    unittest.main()
