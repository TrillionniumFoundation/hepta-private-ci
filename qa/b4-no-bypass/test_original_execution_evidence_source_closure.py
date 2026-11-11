"""Keep the exact completed execution readback sealed, current and read-only."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_execution_evidence_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
EVIDENCE = "codex-rs/hepta-intelligence-eval/src/product_execution_evidence.rs"
CELL = "codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs"


class OriginalExecutionEvidenceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_existing_owner_authentication_precedes_private_evidence_and_final_time(self):
        for marker in (
            "self.execution_context(request)?",
            "executions.readback(&key)?",
            "return Err(ProductEvaluationExecutionErrorV1::Pending)",
            "self.authenticate_completed_execution(request, key.clone(), &bytes)?",
            "execution_codec::decode_envelope(&bytes)?",
            "payload: signing_payload(&key, body)",
            "record_digest: Digest32::of_bytes(&bytes)",
            "let now = (request.clock)().map_err(ProductEvaluationError::from)?",
            "original.revalidate(request.verifier, now)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(EVIDENCE, "fn readback_temporal_comparison_evidence(", marker)

    def test_original_signature_window_and_principal_are_reverified(self):
        for marker in (
            "&self.attestation,",
            "&self.payload,",
            "verified.principal() != &self.evaluator",
            "verified.objective_digest() != self.objective_digest",
        ):
            with self.subTest(marker=marker):
                self.rejects(EVIDENCE, "fn revalidate(", marker)

    def test_cell_adapter_keeps_actual_journals_and_exact_product_plan(self):
        for marker in (
            "plan.require_journals(journals)?",
            "if request.plan != &plan.product",
            ".readback_temporal_comparison_evidence(request, executions)",
            "original_execution_evaluator: Some(request.evaluator.clone())",
        ):
            with self.subTest(marker=marker):
                self.rejects(CELL, "fn readback_completed_evidence(", marker)

    def test_readback_cannot_acquire_execution_signing_or_mutation_capabilities(self):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == EVIDENCE]
        source = (ROOT / EVIDENCE).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / EVIDENCE
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            for mutation in (
                "SigningKey::from_bytes(value);",
                "owner.claim(value);",
                "owner.complete(value);",
                "owner.evaluate_temporal_comparison(value);",
                "owner.evaluate_or_readback_temporal_comparison(value);",
                "LearningEvidenceVerifierV1::new(value);",
                "File::open(value);",
            ):
                with self.subTest(mutation=mutation):
                    target.write_text(source + "\nfn extra() { " + mutation + " }\n")
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_only_actual_cell_adapter_calls_product_evidence_reader(self):
        row = next(row for row in self.manifest["boundary"]
                   if row["id"] == "product_original_completed_execution_evidence_readback")
        self.assertEqual(row["product_callers"], [CELL])


if __name__ == "__main__":
    unittest.main()
