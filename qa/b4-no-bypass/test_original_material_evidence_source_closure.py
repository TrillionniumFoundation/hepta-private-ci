"""Close the original Material READBACK producer without granting host custody."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_material_evidence_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
SERVICE = AGENT + "cell_q24_material_evidence_service.rs"
OWNER = AGENT + "cell_q24_material_receipt_owner.rs"
WIRE = AGENT + "learning_iteration_evidence_wire.rs"


class OriginalMaterialEvidenceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def rows(self, path):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        return rows

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            data = {"protected_file": self.rows(path)}
            PROOF._verify_protected_files(root, data)
            target.write_text(source[:offset] + replacement + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, data)

    def test_consuming_custody_factory_and_uninstalled_service_stay_closed(self):
        expected = {
            "learning_original_material_readback_host": (),
            "learning_original_material_readback_custody": (OWNER,),
            "learning_original_material_evidence_serve": (),
        }
        for identifier, callers in expected.items():
            with self.subTest(identifier=identifier):
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(self.boundaries[identifier].product_callers, callers)
        for marker in (
            "self,",
            "source: CircuitTaskSourceReadbackV1<SW>",
            "ledger: std::sync::Arc<std::sync::Mutex<LedgerWriter>>",
            "let config = self.config.clone();",
            "OriginalCellQ24MaterialEvidenceOwnerV1::from_original_owners(",
            "self, config, source, identity, ledger, baseline,",
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, "fn into_evidence_readback_owner<", marker)
        for marker in (
            "initial.snapshot() != &config.initial",
            "config.scope.validate_snapshot(&config.initial)?",
            "owners: Mutex::new(owners)",
        ):
            self.rejects(SERVICE, "fn from_original_owners(", marker)

    def test_exact_readback_callers_reject_an_additional_product_consumer(self):
        source_index = {}
        for path in (OWNER, SERVICE):
            source_index[path] = PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
        for identifier, method in (
            ("learning_original_material_experience_readback", "readback_experience"),
            ("learning_original_material_dataset_readback", "readback_dataset"),
        ):
            boundary = self.boundaries[identifier]
            self.assertEqual(boundary.product_callers, (SERVICE,))
            PROOF._verify_boundary(ROOT, boundary, source_index, ("_tests.rs",))
            changed = dict(source_index)
            changed[AGENT + "unregistered_material_host.rs"] = (
                "fn escape(owner: &mut OriginalCellQ24MaterialReceiptOwnersV1<E, D>) { "
                "owner." + method + "(sources); }"
            )
            with self.subTest(method=method):
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, boundary, changed, ("_tests.rs",))
        for identifier in (
            "learning_original_material_create",
            "learning_original_material_recover",
            "learning_original_material_experience_attest",
            "learning_original_material_dataset_attest",
        ):
            self.assertEqual(self.boundaries[identifier].product_callers, ())

    def test_fixed_peer_limits_and_failed_exchange_cannot_be_bypassed(self):
        for marker in (
            "policy.peer.uid == unsafe { libc::getuid() }",
            "policy.peer.uid == unsafe { libc::geteuid() }",
            "policy.peer.pid == std::process::id()",
            "policy.timeout.is_zero()",
            "policy.timeout > Duration::from_millis(500)",
            "policy.lifetime.is_zero()",
            "policy.lifetime > Duration::from_secs(300)",
            "policy.request_bound = 16 * 1024",
            "policy.response_bound = 16 * 1024",
            "HostAuthorityPeerChannel::from_stream(stream, policy, original_consumer_pidfd)?",
            "channel.exchange(|bytes|",
            "failure = Some(error)",
            "None => Error::Transport(error)",
        ):
            with self.subTest(marker=marker):
                self.rejects(SERVICE, "fn serve_readback(", marker)

    def test_original_pair_derives_dataset_cut_with_no_network_under_ledger_lock(self):
        for marker in (
            "self.owners.try_lock()",
            "self.ledger.try_lock()",
            "original.readback_experience(",
            "snapshot: &self.config.initial",
            "source: &self.source",
            "identity: &self.identity",
            "ledger: &mut ledger",
            "baseline: &self.baseline",
            "experience.receipt.observed_unix_seconds",
            "original.readback_dataset(",
            "snapshot: &experience_prefix",
            "dataset.receipt.observed_unix_seconds",
            "requested_head == dataset_prefix.head_digest",
            "requested_head == experience_prefix.head_digest",
            "requested_head == self.config.initial.head_digest",
            "if !valid_head",
            "snapshot: &dataset_prefix",
            "current.receipt != experience.receipt",
            "current.attestation != experience.attestation",
            "drop(ledger)",
            "drop(owners)",
        ):
            with self.subTest(marker=marker):
                self.rejects(SERVICE, "fn read_original(", marker)
        source = (ROOT / SERVICE).read_text()
        start = source.index("fn read_original(")
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        body = source[start:end + 1]
        self.assertNotIn(".await", body)
        self.assertNotIn(".exchange(", body)
        self.assertNotIn(".write(", body)

    def test_each_request_correlation_and_monotonic_id_precede_original_response(self):
        for marker in (
            "request.schema != 1",
            "request.operation != wire::OPERATION",
            "request.request_id != *next_request_id",
            "request.binding != initial.head_digest.to_string()",
            "request.operation_id != initial.request.operation_id.as_str()",
            "request.actor_id != initial.owners.owner(role.stage()).as_str()",
            "(*next_request_id).checked_add(1).ok_or(Error::Request)?",
            "snapshot_head.to_string() != request.snapshot_head",
            "self.read_original(role, snapshot_head)?",
            "completion.receipt.observation.stage() != role.stage()",
            "request.predecessor != completion.receipt.predecessor.to_string()",
            "request.receipt_digest != Digest32::of_bytes(&payload).to_string()",
            "wire::Evidence::from_original(signed)",
            "encoded.is_empty() || encoded.len() > 16 * 1024",
            "*next_request_id = next",
        ):
            with self.subTest(marker=marker):
                self.rejects(SERVICE, "fn respond(", marker)
        wire = (ROOT / WIRE).read_text()
        self.assertEqual(wire.count("#[serde(deny_unknown_fields)]"), 3)

    def test_fresh_clock_and_registered_original_signer_follow_actual_reads(self):
        for marker in (
            "let started_at = now()?",
            "let fresh_now = now()?",
            "fresh_now < started_at",
            "fresh_now < self.config.freeze_evidence.issued_at",
            "fresh_now >= self.config.freeze_evidence.expires_at",
            "self.config.verifier.verify(",
            "LearningEvidenceRoleV1::Observer",
            "&payload,",
            "verified.principal() != &signer.principal",
            "verified.controller_id() != &signer.controller_id",
            "signed.principal_id != completion.receipt.actor_id",
            "signed.issued_at != completion.receipt.observed_unix_seconds",
        ):
            with self.subTest(marker=marker):
                self.rejects(SERVICE, "fn respond(", marker)
        self.rejects(SERVICE, "fn now(", "SystemTime::now()")

    def test_wire_retains_every_original_attestation_field_and_window(self):
        for marker in (
            "signed: &SignedLearningEvidenceV1",
            "evidence_id: signed.evidence_id.to_string()",
            "principal_id: signed.principal_id.to_string()",
            "role: match signed.role",
            "trust_digest: signed.trust_digest.to_string()",
            "scope_digest: signed.scope_digest.to_string()",
            "objective_digest: signed.objective_digest.to_string()",
            "authority_epoch: signed.authority_epoch",
            "issued_at: signed.issued_at",
            "expires_at: signed.expires_at",
            "payload_digest: signed.payload_digest.to_string()",
            "signature: STANDARD_NO_PAD.encode(signed.signature)",
        ):
            with self.subTest(marker=marker):
                self.rejects(WIRE, "fn from_original(", marker)

    def test_service_cannot_sign_execute_cache_or_acquire_replacement_capabilities(self):
        source = (ROOT / SERVICE).read_text()
        data = {"protected_file": self.rows(SERVICE)}
        mutations = (
            "SigningKey::generate(value);",
            "LearningEvidenceVerifierV1::new(value);",
            "File::open(value);",
            "UnixStream::connect(value);",
            "OriginalCellQ24MaterialReceiptOwnersV1::create(value);",
            "OriginalCellQ24MaterialReceiptOwnersV1::recover(value);",
            "owner.attest_experience(value);",
            "owner.attest_dataset(value);",
            "LedgerWriter::open(value);",
            "trainer.fit_or_readback(value);",
            "config.with_root_learning_stage_owners(value);",
            "key.sign(value);",
            "request.snapshot;",
            "request.observation;",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / SERVICE
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, data)
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    target.write_text(source + "\nfn escape() { " + mutation + " }\n")
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, data)

    def test_comments_nested_helpers_and_conditional_guards_cannot_supply_checks(self):
        marker = "let started_at = now()?;"
        self.rejects(SERVICE, "fn respond(", marker, "// " + marker)
        self.rejects(
            SERVICE, "fn respond(", marker,
            "fn unrelated() { " + marker + " }"
        )
        self.rejects(
            SERVICE, "fn respond(", marker,
            "if unrelated_condition() { " + marker + " }"
        )


if __name__ == "__main__":
    unittest.main()
