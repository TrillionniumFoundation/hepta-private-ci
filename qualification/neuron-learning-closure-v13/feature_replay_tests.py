"""Boundary fixtures and real OS child lifecycle; no MiniLM success is mocked."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

from closure_common import ClosureError, ClosureLimits, canonical, sha
from feature_replay import ReplayLimits, SCHEMA, readback_receipt, verify_feature_origin
from feature_worker import _dataset, _same_features


def request():
    return dict(
        checkpoint_path="missing-model.npz",
        source_snapshot="missing-source.json",
        encoder_manifest_path="missing-encoder.json",
        encoder_root="missing-encoder",
        dataset_npz_path="missing-data.npz",
        expected_data_id="fixture",
        inputs_root="missing-inputs",
    )


class FeatureBoundaryFixtures(unittest.TestCase):
    def test_feature_comparison_is_exact_after_declared_float64_canonicalization(self):
        values = np.array([[0.0, 0.25]], dtype=np.float32)
        _same_features(values, values.astype(np.float64))
        for changed in (
            np.array([[-0.0, 0.25]], dtype=np.float64),
            np.nextafter(values.astype(np.float64), np.inf),
            values.reshape(2, 1),
        ):
            with self.assertRaises(ClosureError):
                _same_features(values, changed)

    def test_raw_row_types_and_npz_shapes_are_rejected_before_encoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = {"text": "fixture only", "split": "train", "id": "1" * 64, "label": 0}
            rows_path = root / "train_rows.json"
            rows_path.write_bytes(canonical([row]))
            np.savez(
                root / "train_features.npz",
                X=np.zeros((1, 384), dtype=np.float32),
                y=np.array([0]),
            )
            _dataset(root, "train", ReplayLimits(), ClosureLimits())
            for changed in (
                {**row, "label": False},
                {**row, "text": 1},
                {**row, "split": "test"},
            ):
                rows_path.write_bytes(canonical([changed]))
                with self.assertRaises(ClosureError):
                    _dataset(root, "train", ReplayLimits(), ClosureLimits())
            rows_path.write_bytes(canonical([row]))
            np.savez(
                root / "train_features.npz",
                X=np.zeros((1, 385), dtype=np.float32),
                y=np.array([0]),
            )
            with self.assertRaises(ClosureError):
                _dataset(root, "train", ReplayLimits(), ClosureLimits())

    def test_missing_material_is_hold_with_cost_and_no_synthetic_execution(self):
        result = verify_feature_origin(**request())
        self.assertEqual(
            (
                result["status"],
                result["attempts"],
                result["progress"]["encoder_calls_attempted"],
            ),
            ("HOLD", 1, 0),
        )
        self.assertGreater(result["cost"]["total_cpu_seconds"], 0)
        self.assertTrue(result["worker_output"]["stderr"]["complete"])
        self.assertIn("FileNotFoundError", result["worker_stderr"])

    def test_limits_cannot_enlarge_and_receipt_tampering_refuses(self):
        for changes in (
            {"wall_seconds": 121},
            {"cpu_seconds": True},
            {"input_bytes": 0},
        ):
            with self.assertRaises(ClosureError):
                ReplayLimits(**changes)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            raw = canonical(
                {"schema": SCHEMA, "status": "REJECTED", "authority": "DENY_ALL"}
            )
            path.write_bytes(raw)
            self.assertEqual(
                readback_receipt(path, sha(raw))["retained_receipt"]["status"],
                "REJECTED",
            )
            path.write_bytes(raw + b" ")
            with self.assertRaises(ClosureError):
                readback_receipt(path, sha(raw))

    def test_fresh_process_readback_forbids_compute_network_process_and_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            raw = canonical(
                {"schema": SCHEMA, "status": "REJECTED", "authority": "DENY_ALL"}
            )
            path.write_bytes(raw)
            code = """
import os, sys
sys.path.insert(0, sys.argv[1])
def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {'numpy','onnxruntime','tokenizers','adapter','backend','tasks'}:
        raise RuntimeError('forbidden computation import')
    if event.startswith('socket.') or event == 'subprocess.Popen':
        raise RuntimeError('forbidden external operation')
    if event == 'open' and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        raise RuntimeError('forbidden write')
sys.addaudithook(audit)
from feature_replay import readback_receipt
import json
print(json.dumps(readback_receipt(sys.argv[2], sys.argv[3])))
"""
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    code,
                    str(Path(__file__).parent),
                    str(path),
                    sha(raw),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual((completed.returncode, completed.stderr), (0, ""))
            result = json.loads(completed.stdout)
            self.assertEqual(
                result["fresh_execution"],
                {
                    "encoder_calls": 0,
                    "adapter_calls": 0,
                    "executor_calls": 0,
                    "external_operations": 0,
                },
            )


@unittest.skipUnless(
    sys.platform in ("linux", "darwin"), "POSIX controller qualification"
)
class RealChildLifecycleFixtures(unittest.TestCase):
    """The command alone is substituted; Popen, signals and wait4 are real."""

    def spawn_fixture(self, code, children):
        actual = subprocess.Popen

        def start(_command, **kwargs):
            child = actual([sys.executable, "-I", "-B", "-c", code], **kwargs)
            children.append(child)
            return child

        return mock.patch("feature_replay.subprocess.Popen", side_effect=start)

    def assert_reaped(self, child):
        with self.assertRaises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)
        self.assertIsNotNone(child.returncode)

    def test_real_wall_limit_and_output_limit_kill_and_reap_owned_child(self):
        for code, limits, reason in (
            ("import time; time.sleep(30)", ReplayLimits(wall_seconds=1), "wall_limit"),
            (
                "import os,time; os.write(1,b'x'*4096); time.sleep(30)",
                ReplayLimits(output_bytes=64),
                "output_limit",
            ),
        ):
            with self.subTest(reason=reason):
                children = []
                with self.spawn_fixture(code, children):
                    result = verify_feature_origin(**request(), limits=limits)
                self.assertEqual(
                    (
                        result["status"],
                        result["worker_termination"],
                        result["attempts"],
                    ),
                    ("HOLD", reason, 1),
                )
                self.assertGreater(result["cost"]["child_peak_rss_bytes"], 0)
                self.assert_reaped(children[0])
                if reason == "output_limit":
                    self.assertEqual(result["worker_output"]["stdout"]["bytes"], 4096)
                    self.assertFalse(result["worker_output"]["stdout"]["complete"])

    def test_catchable_parent_interrupt_preserves_error_and_reaps_real_child(self):
        children, calls = [], 0
        actual_wait4 = os.wait4

        def interrupt(pid, flags):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise KeyboardInterrupt("retained parent interruption")
            return actual_wait4(pid, flags)

        with self.spawn_fixture("import time; time.sleep(30)", children):
            with mock.patch("feature_replay.os.wait4", side_effect=interrupt):
                with self.assertRaisesRegex(
                    KeyboardInterrupt, "retained parent interruption"
                ):
                    verify_feature_origin(**request())
        self.assert_reaped(children[0])

    def test_wait_failure_reaps_real_child_and_returns_hold_with_measured_cost(self):
        children, calls = [], 0
        actual_wait4 = os.wait4

        def fail(pid, flags):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("retained wait failure")
            return actual_wait4(pid, flags)

        with self.spawn_fixture("import time; time.sleep(30)", children):
            with mock.patch("feature_replay.os.wait4", side_effect=fail):
                result = verify_feature_origin(**request())
        self.assertEqual(result["status"], "HOLD")
        self.assertIn("retained wait failure", result["reason"])
        self.assertIsNotNone(result["cost"]["child_user_seconds"])
        self.assert_reaped(children[0])

    def test_spawn_failure_has_unknown_child_cost_instead_of_fake_zero(self):
        with mock.patch(
            "feature_replay.subprocess.Popen",
            side_effect=FileNotFoundError("fixture executable absent"),
        ):
            result = verify_feature_origin(**request())
        self.assertEqual(
            (result["status"], result["attempts"], result["worker_exit"]),
            ("HOLD", 1, None),
        )
        self.assertIsNone(result["cost"]["child_user_seconds"])
        self.assertIsNone(result["cost"]["total_cpu_seconds"])
        self.assertGreaterEqual(result["cost"]["parent_cpu_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
