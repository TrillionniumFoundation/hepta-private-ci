"""Guard original evaluator identity, signature persistence and read-only recovery."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("original_learning_owner_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "neuron_cell_evaluation_owner.rs"
JOURNAL = AGENT + "learning_owner_journal.rs"

class OriginalLearningOwnerClosureTests(unittest.TestCase):
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
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_original_sealed_request_cannot_be_replaced_by_caller_bytes(self):
        for marker in ("request.key() != &self.execution", "executed.product_plan != self.config.plan", "request.signing_payload()", "self.journal.commit_once(saved_key", "if saved_payload != payload"):
            with self.subTest(marker=marker): self.rejects(OWNER, "fn attest(", marker)

    def test_claim_and_witness_must_precede_signing_and_saved_readback(self):
        for marker in ("self.journal.claim(key)", "return Err(Error::Pending)", "self.anchor_append(before)?", "let bytes = build()?", "self.journal.complete(key, &bytes)", "self.read(key)?", "if saved != bytes"):
            with self.subTest(marker=marker): self.rejects(JOURNAL, "fn commit_once(", marker)

    def test_recovered_evidence_must_match_original_key_actor_and_identity(self):
        for marker in ("self.config.verifier.verify(", "verified.principal() != &self.config.signer.principal", "verified.controller_id() != &self.config.signer.controller_id", "signed.evidence_id != evidence_id(self.saved.binding_digest)?"):
            with self.subTest(marker=marker): self.rejects(OWNER, "fn decode(", marker)

    def test_constructor_checks_registered_signer_without_probe_signature(self):
        for marker in ("key.verifying_key().to_bytes() != config.signer.verifying_key", "product_evaluation_execution_key_v1(", "config.verifier.require_signer_binding("):
            with self.subTest(marker=marker): self.rejects(OWNER, "fn validate_config(", marker)

    def test_registered_controller_revocation_and_role_are_required(self):
        path = "codex-rs/hepta-learning-ledger/src/signed_evidence.rs"
        for marker in ("if enrolled != &canonical", "enrolled.principal.validate(now)?", "enrolled.revoked_at.is_some_and", "enrolled.roles.contains(&expected_role)"):
            with self.subTest(marker=marker): self.rejects(path, "fn require_signer_binding(", marker)

if __name__ == "__main__":
    unittest.main()
