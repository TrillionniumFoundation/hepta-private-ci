"""Small adversarial checks of independent audit boundaries; no fitting."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_skill_longrun_support import ProcessAudit, canonical, checkpoint, decoded_programs, execute, identity, sha


def fixture_checkpoint(root):
    arrays = {"A": np.zeros((4, 384), dtype="<f4"), "B": np.zeros((384, 4), dtype="<f4"),
              "head.weight": np.zeros((28, 384), dtype="<f4"), "head.bias": np.zeros(28, dtype="<f4")}
    for position, opcode in enumerate((1, 2, 3, 6)):
        arrays["head.bias"][position * 7 + opcode] = 5
    manifest = {"schema": "memory-adapter.checkpoint.v1", "dtype": "float32", "base_operator": "identity",
                "base_encoder_sha": "e" * 64, "head_trainable": True, "head_frozen": False,
                "source_ids": [], "parents": [], "training_history": [], "tensors": {},
                "config": {"cell_id": "invented-audit-fixture", "rank": 4, "input_dim": 384, "seed": 1,
                           "outputs": [{"name": f"op{i}", "kind": "multiclass", "size": 7, "weight": 1.0} for i in range(4)]}}
    digest = hashlib.sha256()
    for name, array in sorted(arrays.items()):
        file = root / (name + ".0000.npz")
        np.savez_compressed(file, values=array.reshape(-1))
        manifest["tensors"][name] = {"shape": list(array.shape), "parts": [{"file": file.name, **identity(file)}]}
        digest.update(canonical([name, list(array.shape), "float32"]))
        digest.update(array.tobytes())
    manifest["parameter_sha256"] = digest.hexdigest()
    (root / "manifest.json").write_bytes(canonical(manifest))
    return manifest


class AuditBoundaryTests(unittest.TestCase):
    def test_saved_parameter_replay_and_false_digest_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, checks = Path(temporary), {}
            manifest = fixture_checkpoint(root)
            _, arrays = checkpoint(root, "e" * 64, checks.__setitem__, "fixture")
            self.assertTrue(all(checks.values()))
            self.assertEqual(decoded_programs(arrays, np.zeros((8, 384), dtype="<f4"))["programs"], [[1, 2, 3, 6]] * 8)
            manifest["parameter_sha256"] = "0" * 64
            (root / "manifest.json").write_bytes(canonical(manifest))
            checkpoint(root, "e" * 64, checks.__setitem__, "tampered")
            self.assertFalse(checks["independent_parameter_digest:tampered"])

    def test_unregistered_checkpoint_payload_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, checks = Path(temporary), {}
            manifest = fixture_checkpoint(root)
            manifest["answer_catalog"] = [[1, 2, 3, 6]]
            (root / "manifest.json").write_bytes(canonical(manifest))
            (root / "unregistered-answer.json").write_text("[1,2,3,6]")
            checkpoint(root, "e" * 64, checks.__setitem__, "catalog")
            self.assertFalse(checks["checkpoint_manifest_fields:catalog"])
            self.assertFalse(checks["checkpoint_file_inventory:catalog"])

    def test_independent_interpreter_order_and_budget(self):
        expected = [{"op": "reserve_gap", "before": 7, "after": 2},
                    {"op": "pack", "before": 2, "after": 4},
                    {"op": "cap", "before": 4, "after": 4},
                    {"op": "stop", "before": 4, "after": 4}]
        self.assertEqual(execute([1, 2, 3, 6], 7, [9, 2, 15]),
                         {"status": "completed", "value": 4, "trace": expected})
        self.assertEqual(execute([1, 2, 3, 6], 7, [9, 2, 15], limit=2),
                         {"status": "budget_stop", "value": None, "trace": expected[:2]})
        self.assertEqual(execute([True], 7, [9, 2, 15]),
                         {"status": "invalid_program", "value": None, "trace": []})

    def test_request_file_must_equal_actual_stdin_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, checks = Path(temporary), {}
            stem = root / "child"
            raw = canonical({"artifact": "invented"}) + b"\n"
            stem.with_suffix(".request.json").write_bytes(raw)
            response = {"pid": 1234, "request_sha256": sha(raw), "process_body_wall_ns": 50,
                        "process_body_cpu_ns": 20, "peak_rss_kib": 100}
            stem.with_suffix(".stdout").write_bytes(canonical(response) + b"\n")
            stem.with_suffix(".stderr").write_bytes(b"")
            receipt = {"script": "owner_read.py", "pid": 1234, "exit_code": 0, "passed": True, "timed_out": False,
                       "started_ns": 1000, "exited_ns": 1100, "wall_ns": 100, "cpu_seconds": 0.00000005,
                       "request": identity(stem.with_suffix(".request.json")),
                       "stdout": identity(stem.with_suffix(".stdout")), "stderr": identity(stem.with_suffix(".stderr"))}
            stem.with_suffix(".process.json").write_bytes(canonical(receipt))
            ProcessAudit(root, checks.__setitem__).read(stem, "owner_read.py")
            self.assertTrue(all(checks.values()))
            stem.with_suffix(".request.json").write_bytes(raw.rstrip(b"\n"))
            ProcessAudit(root, checks.__setitem__).read(stem, "owner_read.py")
            self.assertFalse(checks["process_stream:child:request"])


if __name__ == "__main__":
    unittest.main()
