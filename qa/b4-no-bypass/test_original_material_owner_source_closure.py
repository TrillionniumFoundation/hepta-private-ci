"""Guard concrete material Observer custody and the closed completed-read path."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_material_owner_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "cell_q24_material_receipt_owner.rs"
BINDING = AGENT + "cell_q24_material_receipt_binding.rs"
READER = AGENT + "cell_q24_dataset.rs"


class OriginalMaterialOwnerClosureTests(unittest.TestCase):
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
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_both_original_custodies_and_full_freeze_signature_bind_before_open(self):
        for function in ("fn create(", "fn recover("):
            with self.subTest(function=function):
                self.rejects(OWNER, function, "binding::validate_config(")
        for marker in (
            "config.experience_signer.principal.principal_id != config.initial.owners.experience",
            "config.dataset_signer.principal.principal_id != config.initial.owners.dataset",
            "experience_key.verifying_key().to_bytes() != config.experience_signer.verifying_key",
            "dataset_key.verifying_key().to_bytes() != config.dataset_signer.verifying_key",
            "config.freeze_evidence.signing_bytes()",
            "freeze.extend_from_slice(&config.freeze_evidence.signature)",
            "config.scope.binding().as_array()",
        ):
            with self.subTest(marker=marker):
                self.rejects(BINDING, "fn validate_config(", marker)

    def test_actual_material_and_claim_precede_experience_signature(self):
        for marker in (
            "self.experience.read(&self.experience_saved)",
            "ProductEvaluationExecutionStoreErrorV1::Missing",
            "sources.snapshot != &self.config.initial",
            "binding::read_material(&self.config, &mut sources, false)?",
            "self.experience.commit_once(",
            "binding::new_work_time(",
            "binding::verify_freeze(",
            "binding::signed_bytes(",
            "binding::require_same_material(",
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, "fn attest_experience(", marker)

    def test_dataset_requires_original_experience_readback_and_exact_signature_bytes(self):
        for marker in (
            "self.read_experience(",
            "binding::dataset_saved(",
            "self.dataset.read(&saved)",
            "binding::experience_prefix(",
            "self.dataset.commit_once(",
            "binding::verify_original(",
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, "fn attest_dataset(", marker)
        for marker in (
            "experience.attestation.signing_bytes()",
            "signature.extend_from_slice(&experience.attestation.signature)",
            "Digest32::of_bytes(&signature).as_array()",
        ):
            with self.subTest(marker=marker):
                self.rejects(BINDING, "fn dataset_saved(", marker)

    def test_completed_readback_rechecks_physical_owners_and_original_windows(self):
        for function, markers in (
            ("fn authenticate_experience(", (
                "learning_owner_evidence::decode(bytes)?",
                "binding::read_material(&self.config, sources, true)?",
                "attestation.issued_at",
                "self.experience.read(&self.experience_saved)? != bytes",
                "binding::fresh_time(started_at)?",
                "binding::verify_freeze(",
                "binding::verify_original(",
            )),
            ("fn authenticate_dataset(", (
                "self.read_experience(",
                "experience.attestation != original_experience.attestation",
                "self.dataset.read(saved)? != bytes",
                "self.experience.read(&self.experience_saved)? != original_experience_bytes",
                "binding::fresh_time(started_at)?",
                "binding::verify_freeze(",
            )),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(OWNER, function, marker)
        for marker in (
            "signed.issued_at != receipt.observed_unix_seconds",
            "signed.expires_at != expires_at(config, signer, signed.issued_at)?",
            "verified.principal() != &signer.principal",
            "verified.controller_id() != &signer.controller_id",
        ):
            with self.subTest(marker=marker):
                self.rejects(BINDING, "fn verify_original(", marker)

    def test_completed_reader_has_one_explicit_product_caller_and_fixed_system_clock(self):
        rows = [row for row in self.manifest["boundary"]
                if row["id"] == "learning_original_material_completed_dataset_read"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product_callers"], [BINDING])
        for marker in ("self.read_current_at_clock(", "false,", "SystemTime::now()"):
            with self.subTest(marker=marker):
                self.rejects(READER, "fn read_current_for_original_receipt(", marker)
        for marker in ("self.read_current_at_clock(", "true, clock)"):
            with self.subTest(marker=marker):
                self.rejects(READER, "fn read_current_with_clock(", marker)
        for marker in ("if fresh < started_at",):
            self.rejects(BINDING, "fn fresh_time(", marker)
        self.rejects(BINDING, "fn new_work_time(",
                     "fresh >= config.initial.request.envelope.expiry_unix_seconds")

    def test_material_owner_cannot_acquire_ambient_trust_training_or_root_authority(self):
        mutations = (
            "SigningKey::from_bytes(value);",
            "SigningKey::generate(value);",
            "LearningEvidenceVerifierV1::new(value);",
            "File::open(value);",
            "UnixStream::connect(value);",
            "trainer.fit_or_readback(value);",
            "config.with_root_learning_stage_owners(value);",
        )
        for path in (OWNER, BINDING):
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            source = (ROOT / path).read_text()
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                for mutation in mutations:
                    with self.subTest(path=path, mutation=mutation):
                        target.write_text(source + "\nfn extra() { " + mutation + " }\n")
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
