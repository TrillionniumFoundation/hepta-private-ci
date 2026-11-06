"""Protocol/negative controls only; these tests do not qualify a trained model."""

import copy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "v13_tested_protocol", ROOT / "proposal_worker.py"
)
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


class ProposalProtocolTests(unittest.TestCase):
    def header(self, mode="verify"):
        now = time.clock_gettime_ns(time.CLOCK_BOOTTIME) // 1000
        return {
            "schema": "hepta.v13.process.v1",
            "mode": mode,
            "request_digest": "12" * 32,
            "binding": {
                "checkpoint_sha256": "21" * 32,
                "state_sha256": "22" * 32,
                "encoder_hash": "23" * 32,
                "source_version": "24" * 32,
                "data_id": "25" * 32,
                "learning": {name: "26" * 32 for name in WORKER.LEARNING_MEMBERS},
            },
            "task": None
            if mode == "verify"
            else {
                "schema": "hepta.v13.task-input.v1",
                "text": "Use this caller payload",
                "payload": [],
            },
            "limits": {"cpu_seconds": 1, "address_space_bytes": 512 * 1024 * 1024},
            "clock": {"admitted_at_micros": now, "deadline_micros": now + 5_000_000},
            "assets": [
                {"name": name, "bytes": 1, "sha256": "31" * 32}
                for name in WORKER.expected_files(mode)
            ],
        }

    def run_phase(self, header, body=b""):
        encoded = WORKER.canonical(header)
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(ROOT / "proposal_worker.py")],
            input=struct.pack("<I", len(encoded)) + encoded + body,
            env={"LC_ALL": "C", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stderr, b"")
        response = json.loads(result.stdout)
        self.assertEqual(response["authority"], "DENY_ALL")
        self.assertNotIn(response["status"], {"verified", "succeeded"})
        return response

    def test_new_task_preserves_payload_and_rejects_oracle_fields(self):
        task = {
            "schema": "hepta.v13.task-input.v1",
            "text": "Keep first occurrences",
            "payload": ["c", "a", "c"],
        }
        before = copy.deepcopy(task)
        WORKER.validate_task(task)
        self.assertEqual(task, before)
        for name in ("label", "expected", "skill", "row", "training_data"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                WORKER.validate_task({**task, name: 0})

    def test_utf8_and_total_wire_limits_apply_before_inference(self):
        task = {"schema": "hepta.v13.task-input.v1", "text": "é" * 2048, "payload": []}
        WORKER.validate_task(task)
        with self.assertRaises(ValueError):
            WORKER.validate_task({**task, "text": task["text"] + "é"})
        task = {"schema": "hepta.v13.task-input.v1", "text": "new", "payload": ""}
        task["payload"] = "a" * (8192 - len(WORKER.canonical(task)))
        self.assertEqual(len(WORKER.canonical(task)), 8192)
        WORKER.validate_task(task)
        with self.assertRaises(ValueError):
            WORKER.validate_task({**task, "payload": task["payload"] + "a"})

    def test_duplicate_json_and_nonfinite_numbers_are_not_normalized(self):
        for raw in (
            b'{"text":"one","text":"two"}',
            b'{"payload":NaN}',
            b'{"payload":Infinity}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                WORKER.strict_json(raw)

    def test_expired_native_deadline_rejects_before_staging_any_model(self):
        header = self.header()
        header["clock"]["admitted_at_micros"] -= 100_000
        header["clock"]["deadline_micros"] = header["clock"]["admitted_at_micros"] + 1
        response = self.run_phase(header)
        self.assertEqual(response["status"], "deadline")
        self.assertEqual(response["request_digest"], header["request_digest"])
        self.assertEqual(response["progress"], {"staged_bytes": 0})
        self.assertEqual(response["enforced_resources"]["cpu_seconds"], [1, 1])

    def test_foreign_future_epoch_cannot_enter_model_code(self):
        header = self.header()
        for key in header["clock"]:
            header["clock"][key] += 1_000_000_000
        response = self.run_phase(header)
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["progress"], {"staged_bytes": 0})

    def test_large_declared_model_is_refused_without_reading_its_body(self):
        header = self.header()
        first = next(item for item in header["assets"] if item["name"] == "model.npz")
        first["bytes"] = 64 * 1024 * 1024 + 1
        header["assets"].remove(first)
        header["assets"].insert(0, first)
        response = self.run_phase(header)
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["progress"], {"staged_bytes": 0})

    def test_inference_process_refuses_training_asset_transport(self):
        header = self.header("infer")
        header["assets"][0] = {"name": "training.npz", "bytes": 1, "sha256": "31" * 32}
        response = self.run_phase(header)
        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["progress"], {"staged_bytes": 0})

    def test_executable_reference_source_drift_is_refused_before_body(self):
        header = self.header()
        self.assertTrue(header["assets"][0]["name"].startswith("vendor/"))
        response = self.run_phase(header)
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["progress"], {"staged_bytes": 0})

    def test_duplicate_asset_never_replaces_first_staged_content(self):
        header = self.header("infer")
        name = "vendor/reference/adapter.py.source"
        content = (ROOT / name).read_bytes()
        first = {
            "name": name,
            "bytes": len(content),
            "sha256": WORKER.SOURCE_HASHES[name[7:]],
        }
        header["assets"][0:2] = [first, dict(first)]
        response = self.run_phase(header, content)
        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["progress"], {"staged_bytes": len(content)})


if __name__ == "__main__":
    unittest.main(verbosity=2)
