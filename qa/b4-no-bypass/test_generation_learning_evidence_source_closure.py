"""Keep generation evidence reads on original actors and frozen operations."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "generation_learning_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
READER = AGENT + "learning_iteration_generation_evidence.rs"
DELIVERY = AGENT + "learning_iteration_delivery_runtime.rs"
CALLERS = {
    "generation_learning_original_stage_readback": (),
    "learning_evidence_original_owner_readback": (
        AGENT + "learning_iteration_evaluation_evidence.rs",
        READER,
        AGENT + "neuron_cell_evaluation_receipt_owner.rs",
        AGENT + "circuit_next_use_receipt_owner.rs",
        AGENT + "circuit_selection_receipt_owner.rs",
        AGENT + "cell_q24_training_source.rs",
    ),
}


class GenerationLearningEvidenceSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        paths = {
            path
            for identifier in CALLERS
            for path in (
                cls.boundaries[identifier].definition_path,
                *cls.boundaries[identifier].product_callers,
            )
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }

    def rejects(self, path, function, marker, replacement=""):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows, path)
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start : end + 1]
        self.assertEqual(body.count(marker), 1, marker)
        offset = start + body.index(marker)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            manifest = {"protected_file": rows}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(
                source[:offset] + replacement + source[offset + len(marker) :]
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def test_original_evidence_and_new_reader_caller_sets_remain_closed(self):
        for identifier, expected in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(
                    identifier,
                    self.manifest["privileged_inventory"]["required_boundary_ids"],
                )
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if expected:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(
                            ROOT, replace(row, product_callers=()), self.sources, ()
                        )
                method = row.symbol.rsplit("::", 1)[-1]
                extra = (
                    f"fn extra(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                    if row.receiver_type
                    else f"fn extra() {{ {row.symbol}(); }}"
                )
                sources = dict(self.sources)
                sources[AGENT + "unregistered_generation_evidence.rs"] = extra
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())

    def test_predecessor_replay_cannot_skip_history_or_receipt_binding(self):
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?",
            ".position(|original| original == receipt)",
            "prefix.record(original.clone(), original.observed_unix_seconds)?",
            "checked.record(receipt.clone(), receipt.observed_unix_seconds)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(READER, "fn receipt_predecessor(", marker)

    def test_stage_read_keeps_original_observation_current_role_and_scope(self):
        for marker in (
            "request.snapshot.owners.evidence_trust_digest != request.verifier.trust_digest()",
            "request.snapshot.request.envelope.objective_digest != request.verifier.objective_digest()",
            "first != request.receipt.observation",
            ".verify(role, &attestation, &payload, now)",
            "verified.principal().principal_id != request.receipt.actor_id",
            ".owner(request.receipt.observation.stage())",
            "verified.trust_digest() != request.snapshot.owners.evidence_trust_digest",
            "verified.objective_digest() != request.snapshot.request.envelope.objective_digest",
            "request.receipt.observed_unix_seconds > now",
        ):
            with self.subTest(marker=marker):
                self.rejects(READER, "fn read_generation_learning_stage_v1(", marker)

    def test_post_attestation_actor_check_cannot_be_hidden_or_moved(self):
        guard = "if read_observation(&request, &prefix).await? != first"
        for replacement in (
            "if false",
            "/* " + guard + " */ if false",
            "if { fn unused() { " + guard + " {} } false }",
        ):
            with self.subTest(replacement=replacement):
                self.rejects(
                    READER, "fn read_generation_learning_stage_v1(", guard, replacement
                )

    def test_actor_profiles_cannot_substitute_a_different_read(self):
        for marker in (
            "read_learning_selection(prefix)",
            "read_learning_next_use(prefix, intent)",
            "read_learning_updated_selection(prefix, previous_manifest)",
            "read_learning_updated_next_use(prefix, previous_manifest, intent)",
        ):
            with self.subTest(marker=marker):
                self.rejects(READER, "fn read_observation(", marker, "unchecked()")

    def test_delivery_scope_check_precedes_enrollment_and_cannot_be_deferred(self):
        guard = "self.require_frozen_scope(request)"
        for replacement in (
            "unchecked()",
            "if false { " + guard + "; } unchecked()",
            "{ fn unused() { " + guard + "; } unchecked() }",
        ):
            with self.subTest(replacement=replacement):
                self.rejects(
                    DELIVERY, "fn with_circuit_learning_registry(", guard, replacement
                )


if __name__ == "__main__":
    unittest.main()
