"""Exact original artifact checkpoint/CURRENT reads, never publication replay.

The native inventory separately exercises actual original artifact files and
signatures. These mutation controls are source closure, not deployed adoption.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "artifact_publication_readback_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
ARTIFACT = "codex-rs/hepta-learning-artifacts/src/"
HOST = ARTIFACT + "owner_host_readback.rs"
SERVICE = ARTIFACT + "owner_service_readback.rs"
EXPECTED = {
    "learning_artifact_original_publication_host_readback": (SERVICE,),
    "learning_artifact_original_publication_service_readback": (),
}


class ArtifactPublicationReadbackClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        at = source.index(marker, start, end + 1)
        self.rejects_source(path, source[:at] + source[at + len(marker):])

    def rejects_source(self, path, changed):
        source = (ROOT / path).read_text()
        rows = [
            row for row in self.manifest["protected_file"] if row["path"] == path
        ]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_service_is_the_only_host_caller_and_no_publication_cap_is_created(self):
        paths = {HOST, SERVICE}
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(
                    identifier,
                    self.manifest["privileged_inventory"]["required_boundary_ids"],
                )
                PROOF._verify_boundary(ROOT, row, sources, ())
                extra = dict(sources)
                extra[ARTIFACT + "unregistered_publication_reader.rs"] = (
                    f"fn unexpected(owner: &{row.receiver_type}) {{ "
                    "owner.read_original_publication_current(); }"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_exact_started_operation_and_scan_bound_are_not_optional(self):
        for marker in (
            "expected_intent_digest: Digest32",
            "expected_intent_digest.is_zero()",
            "let before = self.recover_publication(operation_id)?",
            "before.checkpoint.operation_id != *operation_id",
            "before.checkpoint.intent_digest != expected_intent_digest",
            "before.checkpoint.authority.grants_any()",
            "before.authority.grants_any()",
        ):
            with self.subTest(marker=marker):
                self.rejects(HOST, "fn read_original_publication_current(", marker)

    def test_original_checkpoint_and_current_are_physically_read_twice(self):
        for marker in (
            "let head_before = self.discover_current_head(started)?",
            "let current_before = self.current_registry_view_bounded(started)?",
            "let current_after = self.current_registry_view_bounded(started)?",
            "let head_after = self.discover_current_head(started)?",
            "let after = self.recover_publication(operation_id)?",
            "if before != after",
            "head_before != head_after",
            "current_before.receipt() != current_after.receipt()",
            "current_before.witness_digest() != current_after.witness_digest()",
            "current_before.trust_digest() != current_after.trust_digest()",
            "current_after.receipt().head_digest != head_after.signed.witness.head_digest",
            "current_after.receipt().binding != head_after.signed.binding",
            "current_after.witness_digest() != head_after.witness_digest",
            "current_after.trust_digest() != head_after.trust_digest",
        ):
            with self.subTest(marker=marker):
                self.rejects(HOST, "fn read_original_publication_current(", marker)

    def test_original_signature_window_is_checked_after_all_io(self):
        for marker in (
            "let started = now_unix_millis()?",
            "let fresh = now_unix_millis()?",
            "if fresh < started",
            "registry_id: self.verifier.trust.registry_id.clone()",
            "minimum_generation: head_after.signed.witness.generation",
            "expected_predecessor_head_digest: head_after.signed.witness.predecessor_head_digest",
            "minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch",
            "now: fresh",
            "let authenticated = self.verifier.verify_signed_head(",
            "&head_after.signed",
            "&requirement",
            "if authenticated != head_after",
            "checkpoint: after.checkpoint",
            "current: current_after",
            "observed_unix_millis: fresh",
        ):
            with self.subTest(marker=marker):
                self.rejects(HOST, "fn read_original_publication_current(", marker)
        self.rejects(HOST, "fn now_unix_millis(", "SystemTime::now().duration_since(UNIX_EPOCH)")
        self.rejects(HOST, "fn now_unix_millis(", "u64::try_from(elapsed.as_millis())")
        source = (ROOT / HOST).read_text()
        before = "let current_after = self.current_registry_view_bounded(started)?;"
        fresh = "let fresh = now_unix_millis()?;"
        self.rejects_source(HOST, source.replace(before, "__swap_current_read__").replace(fresh, before).replace("__swap_current_read__", fresh))

    def test_service_never_rebinds_original_storage_or_withdrawal_scope(self):
        for marker in (
            "LearningArtifactOwnerHost::read_original_publication_current(",
            "&self.host",
            "            operation_id,",
            "            expected_intent_digest,",
            "observed.current().receipt().binding != self.storage_binding",
            "Some(observed.checkpoint().withdrawal_scope_digest)",
            "self.withdrawal_registry.scope_digest()",
            "OriginalArtifactPublicationReadbackErrorV1::InvalidExpectation",
            "Ok(observed)",
        ):
            with self.subTest(marker=marker):
                self.rejects(SERVICE, "fn read_original_publication_current(", marker)

    def test_readback_cannot_resume_write_repair_or_gain_authority(self):
        for path, marker in (
            (HOST, "self.publish("),
            (HOST, "resume_publication"),
            (HOST, "persist_checkpoint"),
            (HOST, "fs::write"),
            (HOST, "SignedFinalUseGrant"),
            (HOST, "SigningKey"),
            (HOST, "impl Clone for OriginalArtifactPublicationReadbackV1"),
            (HOST, "Deserialize"),
            (SERVICE, "self.publish("),
            (SERVICE, "self.recovery_required ="),
            (SERVICE, "self.registry ="),
            (SERVICE, "self.withdrawal_registry ="),
            (SERVICE, "now: u64"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects_source(path, (ROOT / path).read_text() + "\n" + marker)
        self.rejects(HOST, "fn authority(", "AuthorityPosture::DENY_ALL")


    def test_each_actual_receipt_scan_is_bounded_before_metadata_and_decode(self):
        for marker in (
            'fs::read_dir(self.root.join("transactions"))',
            ".take(MAX_READBACK_TRANSACTION_RECORDS + 1)",
            ".enumerate()",
            "if index >= MAX_READBACK_TRANSACTION_RECORDS",
            "return Err(ArtifactOwnerHostError::Capacity)",
            "fs::symlink_metadata(entry.path())?",
            "metadata.file_type().is_symlink() || !metadata.is_file()",
            "let checkpoint = decode_checkpoint(",
            "&read_small_record(&entry.path(), MAX_SMALL_RECORD_BYTES)?",
            "registry_receipt.head_digest != current.signed.witness.head_digest",
            "registry_receipt.binding != current.signed.binding",
            "witness_receipt.witness_digest != current.witness_digest",
            "witness_receipt.binding != current.signed.binding",
            "Some(existing) if existing != registry_receipt",
            "matched.ok_or(ArtifactOwnerHostError::CheckpointMissing)",
        ):
            with self.subTest(marker=marker):
                self.rejects(HOST, "fn current_registry_receipt_bounded(", marker)
        for marker in (
            "let current = self.discover_current_head(at)?",
            "let receipt = self.current_registry_receipt_bounded(&current)?",
            "let registry = read_registry_snapshot(",
            "File::open(self.registry_snapshot_path(receipt))?",
            "if registry.snapshot().head_digest != current.signed.witness.head_digest",
            "receipt, registry, current.witness_digest, current.trust_digest",
        ):
            with self.subTest(marker=marker):
                self.rejects(HOST, "fn current_registry_view_bounded(", marker)
        self.rejects_source(
            HOST, (ROOT / HOST).read_text() + "\nself.current_registry_view("
        )

    def test_seven_real_artifact_cases_are_package_qualified(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import hepta_c_observer_coverage as coverage

        selected = [
            (package, names)
            for group, package, names in coverage.OWNER_GROUPS
            if group == "original_artifact_publication_readback"
        ]
        self.assertEqual(len(selected), 1)
        package, names = selected[0]
        self.assertEqual(package, "codex-hepta-learning-artifacts")
        self.assertEqual(len(names), 7)
        self.assertEqual(len(set(names)), 7)
        tests = (ROOT / ARTIFACT / "owner_service_readback_tests.rs").read_text()
        for name in names:
            self.assertIn(
                "fn " + name.rsplit("::", 1)[-1] + "(", tests
            )
            self.assertIn((package, name), coverage.EXPECTED_CASES)
        self.assertIn(
            '#[path = "owner_service_readback_tests.rs"]',
            (ROOT / ARTIFACT / "owner_service.rs").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
