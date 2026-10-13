"""Fail-closed source visibility guard for unsigned research batch entry points.

Native Rust compilation/test/Clippy remains mandatory. This static regression
only protects against accidental re-export of new, non-authorizing APIs.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "codex-rs" / "hepta-infer-worker-host" / "src"


class UnsignedWorkerBoundary(unittest.TestCase):
    def test_no_public_unsigned_batch_dispatch_or_reference_driver(self) -> None:
        owner = (HOST / "model_worker.rs").read_text(encoding="utf-8")
        batch = (HOST / "model_worker_batch.rs").read_text(encoding="utf-8")
        cpu = (HOST / "model_worker_gated.rs").read_text(encoding="utf-8")
        for export in (
            "batch::NeuronFeatureBatchDriver;",
            "batch::NeuronFeatureBatchItemObservationV2;",
            "gated_cpu::GatedHeadCandidateV2;",
            "gated_cpu::GatedHeadCpuDriverV2;",
        ):
            self.assertIn(f"pub(crate) use {export}", owner)
            self.assertNotIn(f"pub use {export}", owner)

        for signature in (
            "trait NeuronFeatureBatchDriver:",
            "struct NeuronFeatureBatchItemObservationV2 {",
            "fn run_neuron_features_batch(",
            "fn run_neuron_features_batch_receipts(",
        ):
            self.assertIn(f"pub(crate) {signature}", batch)
            self.assertNotIn(f"pub {signature}", batch)

        for signature in (
            "struct GatedHeadCpuDriverV2 {",
            "struct GatedHeadCandidateV2 {",
        ):
            self.assertIn(f"pub(crate) {signature}", cpu)
            self.assertNotIn(f"pub {signature}", cpu)

    def test_v2_physical_execution_is_private_and_v1_abi_unchanged(self) -> None:
        owner = (HOST / "model_worker.rs").read_text(encoding="utf-8")
        shared = (HOST / "model_worker_shared_v2.rs").read_text(encoding="utf-8")
        self.assertIn("pub(crate) fn run_shared_neuron_features_batch_v2(", shared)
        self.assertNotIn("pub fn run_shared_neuron_features_batch_v2(", shared)
        self.assertIn("pub fn run_neuron_features(", owner)
        self.assertIn("pub fn run_neuron_features_receipt(", owner)


if __name__ == "__main__":
    unittest.main()
