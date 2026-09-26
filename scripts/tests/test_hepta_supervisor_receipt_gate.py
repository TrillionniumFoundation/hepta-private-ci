from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hepta-supervisor-receipt-gate.py"
SOURCE = "1" * 40


def latency(value: float = 10.0) -> dict[str, float | int]:
    return {
        "samples": 8,
        "p50": value,
        "p95": value,
        "p99": value,
        "max": value,
    }


def receipt(platform: str) -> dict:
    checks: list[dict] = [
        {
            "kind": "physical_crash_wave",
            "percent": percent,
            "all_replaced": True,
            "unrelated_pids_unchanged": True,
            "snapshot_latency_ms": latency(),
        }
        for percent in (10, 50, 100)
    ]
    checks.extend(
        [
            {"kind": "fourth_crash_exhausted"},
            {"kind": "supervisord_sigkill_adoption"},
            {"kind": "filesystem_permission_failure"},
            {
                "kind": "malformed_drain_ignores_sigterm",
                "terminated": True,
                "peer_snapshot_latency_during_drain_ms": latency(),
            },
            {
                "kind": "trickled_drain_ignores_sigterm",
                "terminated": True,
                "peer_snapshot_latency_during_drain_ms": latency(),
            },
        ]
    )
    unmeasured = ["hardware power loss"]
    if platform == "linux":
        checks.extend(
            [
                {
                    "kind": "fsync_eio",
                    "trigger_observed": True,
                    "no_unwitnessed_replacement": True,
                },
                {
                    "kind": "write_enospc",
                    "trigger_observed": True,
                    "no_unwitnessed_replacement": True,
                },
            ]
        )
    else:
        unmeasured.extend(["fsync EIO", "ENOSPC"])
    instances = 256 if platform == "linux" else 64
    return {
        "schema_version": 1,
        "backend": "native_agentd_protocol_fixture",
        "source_commit": SOURCE,
        "source_dirty": False,
        "status": "passed",
        "error": None,
        "instances": instances,
        "peak_observed_live_instances": instances,
        "supervisord_sha256": "a" * 64,
        "deployment_qualified": False,
        "independent_acceptance": False,
        "warm_snapshot_latency_ms": latency(),
        "checks": checks,
        "unmeasured_faults": unmeasured,
    }


class SupervisorReceiptGateTests(unittest.TestCase):
    def run_gate(
        self,
        value: dict,
        *,
        platform: str,
        instances: int,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / "receipt.json"
            output_path = root / "policy.json"
            receipt_path.write_text(json.dumps(value), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--receipt",
                    str(receipt_path),
                    "--out",
                    str(output_path),
                    "--expected-sha",
                    SOURCE,
                    "--platform",
                    platform,
                    "--instances",
                    str(instances),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode == 0:
                self.assertTrue(output_path.is_file())
                policy = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(policy["status"], "passed")
                self.assertFalse(policy["deployment_qualified"])
                self.assertFalse(policy["independent_acceptance"])
            return completed

    def test_linux_receipt_passes_only_with_fault_injection_and_256_instances(self) -> None:
        completed = self.run_gate(receipt("linux"), platform="linux", instances=256)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_darwin_receipt_passes_with_explicit_unmeasured_linux_faults(self) -> None:
        completed = self.run_gate(receipt("darwin"), platform="darwin", instances=64)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_slow_snapshot_fails_closed(self) -> None:
        value = receipt("linux")
        value["warm_snapshot_latency_ms"] = latency(1001.0)
        completed = self.run_gate(value, platform="linux", instances=256)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("exceeds", completed.stderr)

    def test_missing_linux_fsync_cut_fails_closed(self) -> None:
        value = receipt("linux")
        value["checks"] = [
            check for check in value["checks"] if check.get("kind") != "fsync_eio"
        ]
        completed = self.run_gate(value, platform="linux", instances=256)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("fsync_eio", completed.stderr)

    def test_repository_receipt_cannot_self_assert_acceptance(self) -> None:
        value = copy.deepcopy(receipt("darwin"))
        value["independent_acceptance"] = True
        completed = self.run_gate(value, platform="darwin", instances=64)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must not self-assert", completed.stderr)

    def test_crash_wave_must_preserve_unrelated_processes(self) -> None:
        value = receipt("linux")
        for check in value["checks"]:
            if check.get("kind") == "physical_crash_wave" and check.get("percent") == 50:
                check["unrelated_pids_unchanged"] = False
        completed = self.run_gate(value, platform="linux", instances=256)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unrelated pid", completed.stderr)


if __name__ == "__main__":
    unittest.main()
