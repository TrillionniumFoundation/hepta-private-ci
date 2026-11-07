"""CPU fallback boundaries with fixtures and a short child; no model execution."""

import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import local_cpu_pilot as cpu
from .cloud_evidence import artifact_manifest, sha, write


def kaggle_fixture(root, mutate=None):
    root.mkdir()
    result = {
        "provider": "kaggle-batch",
        "request_id": "current-kaggle",
        "source_sha": "a" * 40,
        "experiment_status": "Failed",
    }
    probe = {
        "request_id": "current-kaggle",
        "source_sha": "a" * 40,
        "torch": {
            "version": "2.11.0+cpu",
            "cuda_version": None,
            "is_available": False,
            "device_count": 0,
        },
        "nvidia_smi": {"available": False, "path": None, "return_code": None},
        "device_files": {"/dev/nvidia0": False, "/dev/nvidiactl": False},
    }
    if mutate:
        mutate(result, probe)
    write(root / "BOOTSTRAP_RESULT.json", result)
    (root / "ACTUAL_PREINSTALLED_DEVICE.json").write_bytes(
        b" \n" + json.dumps(probe, separators=(",", ":")).encode() + b"\n\n"
    )
    artifact_manifest(root, "current-kaggle")
    return root / "artifact-manifest.json"


class DesktopCpuFallbackContracts(unittest.TestCase):
    def test_current_negative_gpu_observation_is_required_not_an_unknown_status(self):
        cases = [
            lambda result, probe: probe["torch"].update(
                is_available=True, device_count=1
            ),
            lambda result, probe: probe.update(torch={"verified": False}),
            lambda result, probe: probe["nvidia_smi"].update(
                available=True, path="/usr/bin/nvidia-smi"
            ),
            lambda result, probe: result.update(request_id="old-kaggle"),
            lambda result, probe: probe.update(source_sha="b" * 40),
            lambda result, probe: result.update(
                experiment_status="CompletedEngineeringPilot"
            ),
        ]
        for mutate in cases:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as folder:
                root = Path(folder) / "artifacts"
                manifest = kaggle_fixture(root, mutate)
                with self.assertRaises(ValueError):
                    cpu.fallback_evidence(
                        root,
                        manifest,
                        sha(manifest),
                        "current-kaggle",
                        "a" * 40,
                        "new-cpu",
                    )

    def test_kaggle_probe_and_result_share_one_pin_and_cpu_request_is_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "artifacts"
            manifest = kaggle_fixture(root)
            result = cpu.fallback_evidence(
                root, manifest, sha(manifest), "current-kaggle", "a" * 40, "new-cpu"
            )
            self.assertIn("delivered_runtime_only", result["scope"])
            for request in ("current-kaggle", ""):
                with self.assertRaisesRegex(ValueError, "Distinct"):
                    cpu.fallback_evidence(
                        root,
                        manifest,
                        sha(manifest),
                        "current-kaggle",
                        "a" * 40,
                        request,
                    )
            (root / "ACTUAL_PREINSTALLED_DEVICE.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "differs"):
                cpu.fallback_evidence(
                    root, manifest, sha(manifest), "current-kaggle", "a" * 40, "new-cpu"
                )

    def test_native_cgroup_limits_are_inherited_and_affinity_cannot_fake_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            mount = root / "cgroup"
            child = mount / "unit/child"
            child.mkdir(parents=True)
            proc = root / "proc-cgroup"
            proc.write_text("0::/unit/child\n")
            for path in (mount, mount / "unit", child):
                (path / "cpu.max").write_text("max 100000")
                (path / "memory.max").write_text("max")
            with self.assertRaisesRegex(ValueError, "aggregate"):
                cpu.resource_snapshot(proc, mount)
            (mount / "unit/cpu.max").write_text("200000 100000")
            (mount / "unit/memory.max").write_text(str(cpu.MEMORY))
            snapshot = cpu.resource_snapshot(proc, mount)
            self.assertEqual(
                (snapshot["cpu_quota_cores"], snapshot["memory_max_bytes"]),
                (2.0, cpu.MEMORY),
            )
            self.assertTrue(snapshot["do_not_sum_ancestor_counters"])
            (mount / "unit/memory.max").write_text(str(cpu.MEMORY + 1))
            with self.assertRaisesRegex(ValueError, "aggregate"):
                cpu.resource_snapshot(proc, mount)

    def test_cpu_profile_and_existing_gpu_wheel_are_not_silently_reinterpreted(self):
        correct = {"device": "cpu", "dtype": "bfloat16", "threads": 2}
        cpu.check_profile(correct)
        for field, value in (
            ("device", "cuda:0"),
            ("dtype", "float16"),
            ("threads", 4),
        ):
            with self.assertRaises(ValueError):
                cpu.check_profile({**correct, field: value})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preflight.json"
            with (
                patch.object(cpu, "resource_snapshot", return_value={"fixture": True}),
                patch.object(
                    cpu.importlib.metadata, "version", return_value="2.8.0+cu126"
                ),
            ):
                with self.assertRaisesRegex(ValueError, "venv version"):
                    cpu.cpu_preflight(path)
            result = json.loads(path.read_text())
            self.assertFalse(result["verified"])
            self.assertFalse(result["gpu_execution_verified"])
            self.assertFalse(result["pretrained_models_executed"])

    def test_failed_cpu_and_pack_keep_independent_raw_proofs_and_meter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "a.py").write_text("x=1\n")
            source_manifest = root / "SOURCE.json"
            write(
                source_manifest,
                {
                    "source_sha": "c" * 40,
                    "files": [
                        {"path": "a.py", "bytes": 4, "sha256": sha(source / "a.py")}
                    ],
                },
            )
            kaggle = root / "kaggle"
            manifest = kaggle_fixture(kaggle)
            profile = root / "PROFILE.json"
            write(profile, {"device": "cpu", "dtype": "bfloat16", "threads": 2})
            pool = root / "pool"
            pool.mkdir()
            (pool / "fixture.txt").write_text("fixture metadata; no real samples")
            args = SimpleNamespace(
                output=str(root / "output"),
                workspace=str(root / "work"),
                source_root=str(source),
                source_sha="c" * 40,
                source_manifest=str(source_manifest),
                source_manifest_sha256=sha(source_manifest),
                pool=str(pool),
                profile=str(profile),
                request_id="new-cpu",
                budget_seconds=60,
                python=sys.executable,
                kaggle_artifacts=str(kaggle),
                kaggle_manifest=str(manifest),
                kaggle_manifest_sha256=sha(manifest),
                kaggle_request_id="current-kaggle",
                kaggle_source_sha="a" * 40,
                kaggle_result_path="BOOTSTRAP_RESULT.json",
                kaggle_probe_path="ACTUAL_PREINSTALLED_DEVICE.json",
            )
            method = cpu.Commands.execute
            handlers = {
                s: signal.getsignal(s)
                for s in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)
            }

            def fail_first(instance, name, command):
                self.assertEqual(name, "cpu_preflight")
                return method(
                    instance, name, [sys.executable, "-c", "raise SystemExit(7)"]
                )

            with (
                patch.object(cpu.Commands, "execute", fail_first),
                patch.object(cpu, "resource_snapshot", return_value={"fixture": True}),
                patch.object(cpu.os, "sched_getaffinity", return_value={1, 2, 3}),
                patch.object(cpu.os, "sched_setaffinity") as affinity,
                patch.object(
                    cpu,
                    "pack_evidence",
                    side_effect=TimeoutError("explicit packing failure fixture"),
                ),
                patch.dict(os.environ),
            ):
                code = cpu.run(args)
            result = json.loads((root / "output/CPU_RESULT.json").read_text())
            self.assertEqual(
                (code, result["provider"], result["experiment_status"]),
                (1, "heptaruntime-desktop-cpu", "Failed"),
            )
            self.assertEqual(result["request_id"], "new-cpu")
            self.assertFalse(result["gpu_execution_verified"])
            self.assertFalse(result["scientific_acceptance"])
            self.assertFalse(result["artifact_complete"])
            self.assertEqual(result["stages"][0]["return_code"], 7)
            critical = root / "output/critical"
            meter = critical / "cpu_preflight.meter.json"
            self.assertEqual(sha(meter), result["stages"][0]["meter_sha256"])
            receipt = json.loads(meter.read_text())
            self.assertEqual(receipt["return_code"], 7)
            self.assertGreater(receipt["wall_seconds"], 0)
            self.assertGreaterEqual(receipt["child_cpu_seconds"], 0)
            for name in ("BOOTSTRAP_RESULT.json", "ACTUAL_PREINSTALLED_DEVICE.json"):
                self.assertEqual(
                    (critical / "kaggle-original" / name).read_bytes(),
                    (kaggle / name).read_bytes(),
                )
            self.assertTrue(
                all(row["status"] == "not_started" for row in result["stages"][1:])
            )
            self.assertEqual(affinity.call_args.args, (0, {1, 2, 3}))
            self.assertEqual({s: signal.getsignal(s) for s in handlers}, handlers)

    def test_invalid_budget_cannot_install_a_timer_or_start_a_child(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pool = root / "pool"
            pool.mkdir()
            args = SimpleNamespace(
                output=str(root / "output"),
                workspace=str(root / "work"),
                source_root=str(root / "source"),
                pool=str(pool),
                source_sha="c" * 40,
                request_id="invalid-budget-fixture",
                budget_seconds=float("nan"),
            )
            with (
                patch.object(cpu.signal, "setitimer") as timer,
                patch.object(cpu.Commands, "execute") as execute,
                patch.object(cpu.os, "sched_setaffinity"),
            ):
                code = cpu.run(args)
            self.assertEqual(code, 1)
            timer.assert_not_called()
            execute.assert_not_called()
            result = json.loads((root / "output/CPU_RESULT.json").read_text())
            self.assertIsNone(result["worker_budget_seconds"])
            self.assertEqual(result["error"]["type"], "ValueError")


if __name__ == "__main__":
    unittest.main()
