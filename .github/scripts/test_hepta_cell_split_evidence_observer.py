"""Synthetic, non-authorizing adversarial tests for offline raw-byte custody."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hepta_cell_split_evidence_observer import (
    MAX_LOG_BYTES,
    _write_exclusive,
    InvalidEvidence,
    observe,
)
from hepta_cell_split_matrix_capture import MEASUREMENT_SCHEMA
from hepta_cell_split_perf_gate import TRACE_FIELD, analyze
from test_hepta_cell_split_matrix_capture import manifest as synthetic_manifest
from test_hepta_cell_split_perf_gate import synthetic_matrix


class IndependentByteCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        self.output = self.root / "observer-copy"
        self.manifest = synthetic_manifest()
        self.packet = synthetic_matrix()
        for name in ("source_sha", "hardware_id", "model_digest", "workload_digest"):
            self.packet[name] = self.manifest[name]
        self.publish()

    def publish(self):
        (self.capture / "manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        (self.capture / "measured-matrix.json").write_text(
            json.dumps(self.packet), encoding="utf-8"
        )
        (self.capture / "diagnostic-comparison.json").write_text(
            json.dumps(analyze(self.packet)), encoding="utf-8"
        )
        for run in self.packet["runs"]:
            scope, mode = run["scopes"], run["mode"]
            name = f"{scope}-{mode}"
            row = {
                "schema": MEASUREMENT_SCHEMA,
                **{
                    key: self.manifest[key]
                    for key in (
                        "source_sha",
                        "hardware_id",
                        "model_digest",
                        "workload_digest",
                    )
                },
                "measurement_source": "unit-test:process-counters",
                **run,
            }
            (self.capture / f"{name}.json").write_text(
                json.dumps(row), encoding="utf-8"
            )
            (self.capture / f"{name}.stdout.log").write_bytes(b"stdout test\n")
            (self.capture / f"{name}.stderr.log").write_bytes(b"stderr test\n")

    def inspect(self, *, destination=None, **overrides):
        pins = {
            "source_sha": self.manifest["source_sha"],
            "hardware_id": self.manifest["hardware_id"],
            "model_digest": self.manifest["model_digest"],
            "workload_digest": self.manifest["workload_digest"],
            "trace_sha256": "b" * 64,
        }
        pins.update(overrides)
        return observe(self.capture, destination or self.output, **pins)

    def test_retains_all_51_exact_raw_artifacts_and_is_never_authority(self):
        ledger = self.inspect()
        self.assertEqual(len(ledger["artifacts"]), 51)
        self.assertTrue(ledger["comparative_gate_passed"])
        for authority_field in (
            "production_evidence_verified",
            "production_activation_authorized",
            "independent_signature_verified",
            "target_host_attested",
        ):
            self.assertFalse(ledger[authority_field])
        raw = (self.capture / "4096-physical_split.json").read_bytes()
        self.assertEqual((self.output / "4096-physical_split.json").read_bytes(), raw)
        self.assertEqual(
            ledger["artifacts"]["4096-physical_split.json"]["sha256"],
            hashlib.sha256(raw).hexdigest(),
        )
        saved = (self.output / "custody-ledger.json").read_bytes()
        self.assertEqual(
            (self.output / "COMPLETE").read_text(),
            hashlib.sha256(saved).hexdigest() + "\n",
        )

    def test_producer_green_claim_cannot_override_independent_replay(self):
        path = self.capture / "diagnostic-comparison.json"
        packet = json.loads(path.read_text())
        packet["comparative_gate_passed"] = False
        path.write_text(json.dumps(packet))
        with self.assertRaisesRegex(InvalidEvidence, "differs from independent replay"):
            self.inspect()
        self.assertFalse(self.output.exists())

    def test_host_row_drift_cannot_be_hidden_in_aggregate(self):
        path = self.capture / "256-logical_split.json"
        packet = json.loads(path.read_text())
        packet["native_backend_calls"] += 1
        path.write_text(json.dumps(packet))
        with self.assertRaisesRegex(InvalidEvidence, "host row differs"):
            self.inspect()
        self.assertFalse(self.output.exists())

    def test_requires_all_original_logs(self):
        (self.capture / "64-no_split.stderr.log").unlink()
        with self.assertRaises(InvalidEvidence):
            self.inspect()
        self.assertFalse(self.output.exists())

    def test_rejects_oversized_log_before_custody(self):
        (self.capture / "64-no_split.stdout.log").write_bytes(
            b"x" * (MAX_LOG_BYTES + 1)
        )
        with self.assertRaisesRegex(InvalidEvidence, "oversized"):
            self.inspect()
        self.assertFalse(self.output.exists())

    def test_rejects_duplicate_json_keys_even_if_python_would_accept(self):
        path = self.capture / "64-no_split.json"
        original = path.read_text(encoding="utf-8")
        path.write_text(
            original.replace('"schema":', '"schema":"duplicate", "schema":', 1)
        )
        with self.assertRaisesRegex(InvalidEvidence, "duplicate JSON field schema"):
            self.inspect()

    @unittest.skipUnless(hasattr(os, "link"), "hardlink required")
    def test_rejects_hardlinked_raw_host_row_without_creating_custody(self):
        original = self.capture / "64-no_split.json"
        os.link(original, self.root / "external-write-alias.json")
        with self.assertRaisesRegex(InvalidEvidence, "hardlinked"):
            self.inspect()
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink required")
    def test_rejects_symlinked_host_row(self):
        path = self.capture / "64-no_split.json"
        real = self.root / "replacement.json"
        real.write_bytes(path.read_bytes())
        path.unlink()
        os.symlink(real, path)
        with self.assertRaises(InvalidEvidence):
            self.inspect()

    def test_independent_external_pins_cannot_be_rewritten_by_capture(self):
        with self.assertRaisesRegex(
            InvalidEvidence, "independently frozen model_digest"
        ):
            self.inspect(model_digest="changed-model")
        with self.assertRaisesRegex(
            InvalidEvidence, "independent frozen request trace"
        ):
            self.inspect(trace_sha256="c" * 64)

    def test_disallows_reuse_of_custody_output_or_capture_child(self):
        self.inspect()
        with self.assertRaisesRegex(InvalidEvidence, "new directory"):
            self.inspect()
        with self.assertRaisesRegex(InvalidEvidence, "outside capture"):
            self.inspect(destination=self.capture / "observer")

    def test_failed_comparison_is_retained_as_failure_not_promotion(self):
        physical = next(
            row for row in self.packet["runs"]
            if row["scopes"] == 4096 and row["mode"] == "physical_split"
        )
        physical["elapsed_seconds"] = 12
        self.publish()
        ledger = self.inspect()
        self.assertFalse(ledger["comparative_gate_passed"])
        self.assertFalse(ledger["production_activation_authorized"])

    def test_cli_negative_comparison_exits_nonzero_without_erasing_custody(self):
        from hepta_cell_split_evidence_observer import main

        physical = next(
            row
            for row in self.packet["runs"]
            if row["scopes"] == 4096 and row["mode"] == "physical_split"
        )
        physical["elapsed_seconds"] = 12
        self.publish()
        argv = [
            "hepta_cell_split_evidence_observer.py",
            "--capture",
            str(self.capture),
            "--output",
            str(self.output),
            "--source-sha",
            self.manifest["source_sha"],
            "--hardware-id",
            self.manifest["hardware_id"],
            "--model-digest",
            self.manifest["model_digest"],
            "--workload-digest",
            self.manifest["workload_digest"],
            "--trace-sha256",
            "b" * 64,
        ]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()) as stdout:
            self.assertEqual(main(), 1)
        self.assertFalse(json.loads(stdout.getvalue())["production_activation_authorized"])
        self.assertTrue((self.output / "COMPLETE").is_file())


    def test_mutating_earlier_raw_row_during_copy_cannot_seal_custody(self):
        original_write = _write_exclusive
        changed = False

        def write_and_tamper(fd, name, data):
            nonlocal changed
            original_write(fd, name, data)
            if not changed:
                changed = True
                path = self.capture / "64-no_split.json"
                path.write_bytes(path.read_bytes() + b"\n")

        with patch(
            "hepta_cell_split_evidence_observer._write_exclusive",
            side_effect=write_and_tamper,
        ):
            with self.assertRaisesRegex(InvalidEvidence, "changed during custody"):
                self.inspect()
        self.assertFalse((self.output / "COMPLETE").exists())

    def test_replaced_capture_directory_cannot_join_different_runs(self):
        original_write = _write_exclusive
        changed = False

        def write_and_replace(fd, name, data):
            nonlocal changed
            original_write(fd, name, data)
            if not changed:
                changed = True
                self.capture.rename(self.root / "old-capture")
                self.capture.mkdir()

        with patch(
            "hepta_cell_split_evidence_observer._write_exclusive",
            side_effect=write_and_replace,
        ):
            with self.assertRaisesRegex(InvalidEvidence, "pinned directory"):
                self.inspect()
        self.assertFalse((self.output / "COMPLETE").exists())

    def test_replaced_output_directory_cannot_receive_a_complete_marker(self):
        original_write = _write_exclusive
        changed = False

        def write_and_replace(fd, name, data):
            nonlocal changed
            original_write(fd, name, data)
            if not changed:
                changed = True
                self.output.rename(self.root / "orphaned-output")
                self.output.mkdir()

        with patch(
            "hepta_cell_split_evidence_observer._write_exclusive",
            side_effect=write_and_replace,
        ):
            with self.assertRaisesRegex(InvalidEvidence, "pinned directory"):
                self.inspect()
        self.assertFalse((self.output / "COMPLETE").exists())
        self.assertFalse((self.root / "orphaned-output" / "COMPLETE").exists())


if __name__ == "__main__":
    unittest.main()
