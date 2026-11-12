"""Original Selector kernels remain bound to actual Model observations."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "q24_root_local_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "cell_q24_local_decision_owner.rs"
SIGNING = AGENT + "cell_q24_local_decision_signing.rs"
ROOT_OWNER = AGENT + "cell_q24_local_decision_root.rs"
ROOT_MODEL = AGENT + "cell_q24_learning_model_root.rs"
DISPATCH = AGENT + "cell_q24_learning_model_dispatch.rs"
B_FRAME = AGENT + "cell_q24_learning_b_operation.rs"


class RootLocalDecisionSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in (OWNER, SIGNING, ROOT_OWNER, ROOT_MODEL, DISPATCH, B_FRAME, AGENT + "cell_q24_learning_historical_operation.rs", AGENT + "cell_q24_learning_historical_receipts.rs", AGENT + "cell_q24_learning_stage_owners.rs")
        }

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start : end + 1]
        self.assertEqual(body.count(marker), 1, marker)
        offset = start + body.index(marker)
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker) :])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_private_kernels_accept_only_actual_owner_callers(self):
        for suffix in ("sign", "prefix", "projection"):
            row = self.boundaries["q24_local_original_private_" + suffix]
            with self.subTest(boundary=row.identifier):
                expected = (OWNER, ROOT_OWNER) if suffix == "sign" else (ROOT_OWNER,)
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if suffix == "sign":
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(
                            ROOT, replace(row, product_callers=()), self.sources, ()
                        )
                extra = dict(self.sources)
                method = row.symbol.rsplit("::", 1)[-1]
                extra[AGENT + "unregistered_selector.rs"] = (
                    f"fn forged(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_remote_model_and_selector_have_only_real_aggregate_callers(self):
        expected = {
            "q24_local_root_attest": (ROOT_MODEL,),
            "q24_local_root_read": (ROOT_MODEL,),
            "q24_model_root_dispatch": (DISPATCH,),
            "q24_model_root_operation": (),
            "q24_original_b_borrowed_model": (B_FRAME,),
        }
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_root_decision_keeps_post_read_even_when_journal_fails(self):
        for function, marker in (
            ("fn attest_original_root_decision(", "let bytes = self.sign_original_proposal(&proposal, &saved);"),
            ("fn read_original_root_decision(", "let bytes = self.journal.read(&saved);"),
            ("fn original_root_proposal(", "self.proposal_prefix(factory, snapshot)?"),
            ("fn original_root_proposal(", "self.require_original_proposal(prefix, &original)"),
        ):
            with self.subTest(marker=marker):
                self.rejects(ROOT_OWNER, function, marker)

    def test_root_model_keeps_training_and_b_on_same_original_operation(self):
        for marker in (
            "OriginalQ24TrainingOperationV1::read_original_training_evidence(original)?",
            "!snapshot.receipts.starts_with(&evidence.snapshot().receipts)",
            "!before.same_original_observation(&after)",
        ):
            with self.subTest(marker=marker):
                self.rejects(ROOT_MODEL, "fn model_root_action_in_operation(", marker)

    def test_borrowed_model_keeps_exact_native_b_receipt(self):
        self.rejects(ROOT_MODEL, "fn model_root_action_from_original_b(",
                     "snapshot.receipts.get(evidence.snapshot().receipts.len()) != Some(observed.receipt())")

    def test_original_factory_and_exact_prefix_cannot_be_removed(self):
        for function, marker in (
            ("fn original_proposal<", "self.proposal_prefix(factory, snapshot)?"),
            ("fn original_proposal<", "self.require_original_proposal(prefix, &original)"),
            ("fn proposal_prefix(", "snapshot.request != self.config.initial.request"),
            ("fn proposal_prefix(", "snapshot.owners != self.config.initial.owners"),
            ("fn require_original_proposal(", "prefix.snapshot().receipts.last() != Some(original.learning_receipt())"),
            ("fn require_original_proposal(", "prefix.next_stage() != Some(LearningIterationStageV1::Selection)"),
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, function, marker)

    def test_signing_requires_claim_current_role_and_original_time_bounds(self):
        for marker in (
            "self.journal.read(saved)",
            "current >= config.initial.request.envelope.expiry_unix_seconds",
            "decision(config.policy, proposal, current)?",
            "self.journal.commit_once(saved,",
            "issued_at >= config.initial.request.envelope.expiry_unix_seconds",
            "checked_add(config.maximum_signature_lifetime_seconds)",
            ".min(config.signer.principal.expires_at)",
            "key.sign(&signed.signing_bytes())",
            "config.verifier.verify(",
            "Err(error) => return Err(error)",
        ):
            with self.subTest(marker=marker):
                self.rejects(SIGNING, "fn sign_original_proposal(", marker)


if __name__ == "__main__":
    unittest.main()
