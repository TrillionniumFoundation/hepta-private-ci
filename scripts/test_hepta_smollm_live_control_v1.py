"""Finite live-child and original-error controls; no model efficacy evidence."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_live_control_v1 as live
import hepta_smollm_metadata_artifact_v1 as metadata


class LiveControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.chain = self.root / "chain"
        (self.chain / "scripts").mkdir(parents=True)
        self.runtime_path = self.chain / "scripts/llm_runtime_pilot.py"
        self.runtime_path.write_text("# finite fixture, never a pretrained model\n")
        runtime_sha = live.sha(self.runtime_path)
        self.plan = self.root / "original-plan.json"
        self.plan.write_text(
            json.dumps(
                dict(
                    training_steps=10,
                    runtime_source=runtime_sha,
                    training_budget=dict(wall_seconds=1800, rss_bytes=16 * 1024**3),
                    inference_budget=dict(wall_seconds=600, rss_bytes=8 * 1024**3),
                )
            )
        )
        for args in (
            ("init", "-q"),
            ("add", "."),
            (
                "-c",
                "user.name=Finite Control",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ),
        ):
            subprocess.run(
                ["git", "-C", str(self.chain), *args], check=True, capture_output=True
            )
        commit = subprocess.check_output(
            ["git", "-C", str(self.chain), "rev-parse", "HEAD"], text=True
        ).strip()
        for name, value in (
            # This fixture deliberately exercises the historical tiny checkout.
            ("EXECUTION_SOURCE_PROFILE", None),
            ("RUNTIME_SHA", runtime_sha),
            ("PLAN_SHA", live.sha(self.plan)),
            ("CHAIN_COMMIT", commit),
        ):
            patcher = patch.object(live, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.output = self.root / "output"
        self.output.mkdir()
        self.entry = live.manifest(self.chain, self.plan)
        self.value = live.request(
            self.entry,
            "train",
            "fresh-budget-matched-lora",
            self.root / "materials",
            self.output,
        )
        self.calls = []
        self.failure = None

        def original_child(args):
            self.calls.append(vars(args))
            actual = dict(
                schema="llm-runtime-actual-child-v1",
                phase=args.phase,
                role=args.role,
                experiment=self.entry["plan"]["identity"],
                runtime_source=runtime_sha,
                outcome="failed" if self.failure else "success",
                process_cpu_ns=100,
            )
            (self.output / "actual-receipt.json").write_text(json.dumps(actual))
            if self.failure:
                raise self.failure

        runtime = SimpleNamespace(__file__=str(self.runtime_path), child=original_child)
        importer = patch.object(live.importlib, "import_module", return_value=runtime)
        importer.start()
        self.addCleanup(importer.stop)
        self.supervisor = dict(
            outcome="success",
            exit_code=0,
            stop_reason=None,
            waited_child_reaped=True,
            owned_child_reap_resolved=True,
            owned_child_echild_observed=False,
            waited_child_observation_error=None,
            budget=self.entry["training_budget"],
            exit_observation_profile=dict(
                profile="linux-owned-exit-worker-pidfd-v4", maximum_drain_ns=100000000
            ),
            terminal_reconciliation_profile="explicit-linux-owned-exit-worker-pidfd-v4",
        )

    def read(self):
        return json.loads((self.output / live.RECEIPT).read_bytes())

    def test_original_child_returns_before_same_process_release(self):
        input_path = self.root / "live-input.json"
        live.save(input_path, self.value)
        previous_umask = os.umask(0o022)
        try:
            with patch.object(
                live.sys,
                "argv",
                [
                    str(Path(live.__file__)),
                    "--input",
                    str(input_path),
                    "--input-sha256",
                    live.sha(input_path),
                ],
            ):
                live.main()
        finally:
            os.umask(previous_umask)
        self.assertEqual(
            (self.output / "actual-receipt.json").stat().st_mode & 0o777, 0o600
        )
        self.assertEqual((self.output / live.RECEIPT).stat().st_mode & 0o777, 0o600)
        pin = live.verify(self.value, self.supervisor)
        receipt = self.read()
        self.assertEqual(
            self.calls,
            [
                dict(
                    materials=str(self.root / "materials"),
                    plan=str(self.plan),
                    output=str(self.output),
                    phase="train",
                    role="fresh-budget-matched-lora",
                    artifact=None,
                )
            ],
        )
        self.assertEqual(receipt["process_before"], receipt["process_after"])
        self.assertEqual(
            receipt["original_actual_before_sha256"],
            receipt["original_actual_after_sha256"],
        )
        self.assertEqual(pin["sha256"], live.sha(self.output / live.RECEIPT))
        self.assertGreater(receipt["release_wall_ns"], 0)
        self.assertGreater(receipt["process_peak_rss_bytes"], 0)

    def test_unselected_namespace_or_candidate_training_refused(self):
        for key, value in (
            ("schema", "legacy"),
            ("profile", "optional"),
            ("role", "candidate"),
            ("production_qualification", True),
            ("artifact", "/unexpected"),
        ):
            changed = deepcopy(self.value)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                live.execute(changed)
        changed = deepcopy(self.value)
        changed["allow_legacy"] = True
        with self.assertRaises(ValueError):
            live.execute(changed)
        self.assertEqual(self.calls, [])

    def test_source_or_model_plan_drift_refused_before_child(self):
        original = self.runtime_path.read_bytes()
        self.runtime_path.write_bytes(original + b"# changed\n")
        with self.assertRaises(subprocess.CalledProcessError):
            live.execute(self.value)
        self.runtime_path.write_bytes(original)
        self.plan.write_bytes(self.plan.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            live.execute(self.value)
        self.assertEqual(self.calls, [])

    def test_primary_child_error_retained_when_release_fails(self):
        self.failure = LookupError("original training failure")
        with patch.object(
            live, "release", side_effect=OSError("allocator unavailable")
        ):
            with self.assertRaises(LookupError) as caught:
                live.execute(self.value)
        self.assertIs(caught.exception, self.failure)
        self.assertTrue(any("OSError" in note for note in self.failure.__notes__))
        self.assertEqual(self.read()["outcome"], "failed")

    def test_release_failure_after_success_remains_failure(self):
        with patch.object(
            live, "release", side_effect=OSError("allocator unavailable")
        ):
            with self.assertRaises(OSError):
                live.execute(self.value)
        self.assertEqual(self.read()["outcome"], "failed")

    def test_real_sidecar_write_failure_preserves_primary_or_fails(self):
        marker = self.output / live.RECEIPT
        marker.write_bytes(b"retain existing evidence")
        self.failure = LookupError("original training failure")
        with self.assertRaises(LookupError) as caught:
            live.execute(self.value)
        self.assertIs(caught.exception, self.failure)
        self.assertTrue(
            any("FileExistsError" in note for note in self.failure.__notes__)
        )
        self.failure = None
        with self.assertRaises(FileExistsError):
            live.execute(self.value)
        self.assertEqual(marker.read_bytes(), b"retain existing evidence")

    def test_final_identity_failure_cannot_mask_primary(self):
        self.failure = LookupError("original training failure")
        with patch.object(
            live,
            "process_identity",
            side_effect=[dict(pid=123, birth_ticks=456), OSError("proc unavailable")],
        ):
            with self.assertRaises(LookupError) as caught:
                live.execute(self.value)
        self.assertIs(caught.exception, self.failure)
        self.assertTrue(
            any("proc unavailable" in note for note in self.failure.__notes__)
        )
        self.assertEqual(self.read()["outcome"], "failed")

    def test_release_receipt_never_overrides_original_terminal_failure(self):
        live.execute(self.value)
        for key, value in (
            ("outcome", "failed"),
            ("exit_code", 1),
            ("waited_child_reaped", False),
            ("owned_child_reap_resolved", False),
            ("owned_child_echild_observed", True),
        ):
            changed = deepcopy(self.supervisor)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                live.verify(self.value, changed)
        changed = deepcopy(self.supervisor)
        changed["exit_observation_profile"]["maximum_drain_ns"] += 1
        with self.assertRaises(ValueError):
            live.verify(self.value, changed)
        actual = self.output / "actual-receipt.json"
        actual.write_bytes(actual.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            live.verify(self.value, self.supervisor)

    def test_metadata_retains_bounded_entry_input_and_release_only(self):
        for path in (
            "n/p/round-1/control-execution-entry-v1.json",
            "n/p/round-2/train-fresh-budget-matched-lora-live-input.json",
            "n/p/round-3/evaluate-candidate/live-control-release-v1.json",
        ):
            self.assertTrue(metadata.allowed(path), path)
        for path in (
            "n/p/round-1/train-candidate/artifact.safetensors",
            "secrets/live-control-release-v1.json",
            "n/p/round-3/evaluate-candidate/.private.json",
        ):
            self.assertFalse(metadata.allowed(path), path)


if __name__ == "__main__":
    unittest.main()
