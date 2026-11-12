"""Protect explicit original Material execution from its read-only producers.

These source mutation checks qualify ownership edges. Native mechanism cases
exercise actual original journals separately; neither deploys an external host.
"""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_material_command_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
PAIR = AGENT + "cell_q24_material_receipt_owner.rs"
READONLY = AGENT + "cell_q24_material_evidence_service.rs"
CLIENT = AGENT + "cell_q24_material_command.rs"
SERVICE = AGENT + "cell_q24_material_command_service.rs"
WIRE = AGENT + "cell_q24_material_command_wire.rs"
EXPECTED = {
    "learning_original_material_command_bootstrap": (),
    "learning_original_material_command_custody": ("codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",),
    "learning_original_material_command_serve_experience_commands": (),
    "learning_original_material_command_serve_dataset_commands": (),
    "learning_original_material_command_serve_experience_readback": (),
    "learning_original_material_command_serve_dataset_readback": (),
    "learning_original_material_command_serve_dataset_source": (),
    "learning_original_material_command_client_from_original_experience_stream": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs",),
    "learning_original_material_command_client_from_original_dataset_stream": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs",),
    "learning_original_material_command_client_recover_original_experience_stream": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs",),
    "learning_original_material_command_client_recover_original_dataset_stream": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs",),
    "learning_original_material_command_client_execute": ("codex-rs/hepta-agentd/src/cell_q24_no_update_stage_execute.rs",),
    "learning_original_material_command_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_material_dataset_readback.rs", "codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs",),
    "learning_original_material_command_client_receipt_attestation": (),
}


class OriginalMaterialCommandClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

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

    def require_retained_evidence_view(self, source):
        # A return type followed by its function body is not a struct literal.
        # Only this unique getter signature is exempt; its body is independently
        # protected by the exact function-order and top-level CALLERS guard.
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        signature = "pub fn attestation(&self) -> &SignedLearningEvidenceV1 {"
        if code.count(signature) != 1:
            raise PROOF.VerificationFailure("unique retained evidence getter required")
        code = code.replace(signature, " " * len(signature), 1)
        if re.search(r"\bSignedLearningEvidenceV1\s*\{", code):
            raise PROOF.VerificationFailure("new evidence construction is forbidden")

    def test_retained_evidence_getter_never_permits_new_struct_construction(self):
        source = (ROOT / CLIENT).read_text()
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows(CLIENT)})
        self.require_retained_evidence_view(source)
        self.require_retained_evidence_view(
            source + "\n// SignedLearningEvidenceV1 { is a comment, not code.\n"
        )
        original_view = "&self.evidence[self.evidence.len() - 1]"
        self.assertEqual(source.count(original_view), 1)
        for gap in (" ", "\n    ", " /* no construction authority */\n    "):
            literal = "SignedLearningEvidenceV1" + gap + "{ ..original }"
            with self.subTest(gap=gap, location="other function"):
                altered = source + (
                    "\nfn unauthorized_copy(original: SignedLearningEvidenceV1) { "
                    "let _ = &" + literal + "; }\n"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "construction"):
                    self.require_retained_evidence_view(altered)
            with self.subTest(gap=gap, location="getter body"):
                altered = source.replace(
                    original_view,
                    "let original = self.evidence[0].clone(); let _ = " + literal
                    + "; " + original_view,
                    1,
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "construction"):
                    self.require_retained_evidence_view(altered)
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unique retained"):
            self.require_retained_evidence_view(
                source.replace("pub fn attestation(&self)", "pub fn replacement(&self)", 1)
            )

    def test_only_original_pair_consumption_opens_custody_and_external_dispatch_stays_closed(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                extra = dict(sources)
                method = row.symbol.rsplit("::", 1)[-1]
                extra[AGENT + "unregistered_material_command.rs"] = (
                    f"fn unexpected(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_private_origin_shared_admission_and_recovery_cannot_be_rearmed(self):
        for function, marker in (
            ("fn create(", "command_origin: OriginalMaterialCommandOriginV1::FreshCreate"),
            ("fn recover(", "command_origin: OriginalMaterialCommandOriginV1::Recovered"),
            ("fn into_command_owner<", "self.command_origin"),
            ("fn into_command_owner<", "OriginalMaterialCommandOriginV1::FreshCreate"),
            ("fn into_command_owner<", "OriginalCellQ24MaterialCommandOwnerV1::from_original_pair("),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(PAIR, function, marker)
        self.rejects(SERVICE, "fn from_original_pair(",
                     "admitted: AtomicU8::new(if allow_new_commands { 0 } else { 3 })")
        self.rejects(SERVICE, "fn command_response(",
                     "self.admitted.fetch_or(bit, Ordering::AcqRel)")
        for function in ("fn recover_original_experience_stream(", "fn recover_original_dataset_stream("):
            self.rejects(CLIENT, function, "true,")
        source = (ROOT / READONLY).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / READONLY
            target.parent.mkdir(parents=True)
            for mutation in (
                "pub fn into_command_owner() {}",
                "pub fn serve_experience_commands() {}",
                "pub fn serve_dataset_commands() {}",
                "fn escape() { OriginalCellQ24MaterialCommandOwnerV1::from_original_pair(value); }",
            ):
                target.write_text(source + "\n" + mutation)
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {"protected_file": self.rows(READONLY)})

    def test_fixed_roles_exact_context_and_no_uploaded_signing_body(self):
        for function, marker in (
            ("fn serve_experience_commands(", "Role::Experience"),
            ("fn serve_dataset_commands(", "Role::Dataset"),
            ("fn serve_experience_readback(", "Role::Experience"),
            ("fn serve_dataset_readback(", "Role::Dataset"),
            ("fn serve_role_commands(", "original_owner_command_channel_v1("),
            ("fn command_response(", "request.require_context(config, role, self.binding, request_id)?"),
        ):
            self.rejects(SERVICE, function, marker)
        for marker in ("self.initial_head != config.initial.head_digest.to_string()",
                       "self.operation_id != config.initial.request.operation_id.as_str()",
                       "self.scope_binding != config.scope.binding().to_string()",
                       "self.actor_id != config.initial.owners.owner(role.stage()).as_str()",
                       "self.stage != role_name(role)"):
            self.rejects(WIRE, "fn require_context(", marker)
        source = (ROOT / WIRE).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / WIRE
            target.parent.mkdir(parents=True)
            for field in ("batch", "labels", "snapshot", "receipt", "signature", "observed", "now"):
                target.write_text(source.replace("struct Request {", f"struct Request {{\n    pub {field}: String,", 1))
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {"protected_file": self.rows(WIRE)})

    def test_actual_stage_sources_precede_signatures_and_dataset_never_creates_experience(self):
        for marker in (".owners.try_lock()", ".ledger.try_lock()",
                       "let initial = &config.initial",
                       "role == Role::Experience && action == wire::Action::Execute",
                       "original.attest_experience(", "original.readback_experience(",
                       "let prefix = coordinator.snapshot().clone()",
                       "original.attest_dataset(", "original.readback_dataset(",
                       "current.receipt != dataset.receipt",
                       "current.attestation != dataset.attestation",
                       "current.receipt != experience.receipt",
                       "current.attestation != experience.attestation",
                       "drop(ledger)", "drop(owners)"):
            self.rejects(SERVICE, "fn original_cut(", marker)
        self.rejects(SERVICE, "fn original_state(", "_ => wire::CommandResult::Uncertain")
        self.rejects(SERVICE, "fn command_response(",
                     "started_at >= config.initial.request.envelope.expiry_unix_seconds")
        source = (ROOT / SERVICE).read_text()
        start = source.index("fn original_cut(")
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        for denied in (".await", ".exchange(", ".request(", ".write("):
            self.assertNotIn(denied, source[start:end + 1])

    def test_live_readback_full_signatures_and_internal_clock_prevent_renewal(self):
        for marker in ("let started_at = now()?", "slot.take().ok_or(Error::Unavailable)?",
                       "channel.execution_requested = true", ".request(&encoded)",
                       "response.require_request(&request)?", "fresh_now < started_at",
                       "original != &completed", "channel.peer.check_peer_lifetime()?"):
            self.rejects(CLIENT, "fn exchange(", marker)
        # The async future owns this private Drop fence through the blocking
        # await; a queued task must inspect the same flag before sending Execute.
        for marker in (
            "let queued_execute_fence = QueuedExecuteFence {",
            "abandoned: Arc::clone(&abandoned)",
            "if action == wire::Action::Execute && abandoned.load(Ordering::Acquire)",
            "drop(queued_execute_fence)",
        ):
            with self.subTest(queued_cancel=marker):
                self.rejects(CLIENT, "fn exchange(", marker)
        self.rejects(CLIENT, "fn drop(", "self.abandoned.store(")
        self.rejects(CLIENT, "fn drop(", "true, Ordering::Release",
                     "false, Ordering::Release")
        self.rejects(CLIENT, "fn receipt_attestation(",
                     "OriginalCellQ24MaterialCommandClientV1::readback(self).await?")
        self.rejects(SERVICE, "fn command_response(", "fresh_now < started_at")
        for marker in ("config.freeze_evidence.signing_bytes()",
                       "original_freeze.extend_from_slice(&config.freeze_evidence.signature)",
                       "at < config.freeze_evidence.issued_at",
                       "at >= config.freeze_evidence.expires_at"):
            self.rejects(WIRE, "fn context_binding(", marker)
        for marker in ("receipt.observed_unix_seconds != signed.issued_at",
                       "signed.expires_at != expires_at",
                       "receipt.evidence_digest != completed.snapshot.receipts[0].evidence_digest",
                       "verified.principal() != &signer.principal",
                       "verified.controller_id() != &signer.controller_id"):
            self.rejects(WIRE, "fn authenticate_cut(", marker)

    def test_guards_cannot_move_into_comments_helpers_or_optional_branches(self):
        marker = "let started_at = now()?;"
        for replacement in ("// " + marker, "fn unrelated() { " + marker + " }",
                            "if optional_condition() { " + marker + " }"):
            self.rejects(SERVICE, "fn command_response(", marker, replacement)

    def test_peer_liveness_io_precedes_final_signature_clock(self):
        source = (ROOT / CLIENT).read_text()
        start = source.index("async fn exchange(")
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        body = source[start:end + 1]
        peer = "        channel.peer.check_peer_lifetime()?;\n"
        clock = "        let fresh_now = now()?;\n"
        self.assertEqual(body.count(peer), 1)
        self.assertEqual(body.count(clock), 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == CLIENT]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / CLIENT
            target.parent.mkdir(parents=True)
            target.write_text(source)
            data = {"protected_file": rows}
            PROOF._verify_protected_files(root, data)
            # Keeping both checks but moving pidfd I/O after the clock must fail.
            late = body.replace(peer, "", 1).replace(clock, clock + peer, 1)
            target.write_text(source[:start] + late + source[end + 1:])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, data)


if __name__ == "__main__":
    unittest.main()
