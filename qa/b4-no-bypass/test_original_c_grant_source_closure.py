"""Keep C signing on one admitted Root slot and the original issuer tokens."""

from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
STORE = A + "authority_host_publication_grant_store.rs"
CONTEXT = A + "authority_host_publication_grant_context.rs"
GRANT = A + "authority_host_publication_grant.rs"
ISSUER = A + "deployment_publication.rs"
TRANSPORT = A + "authority_host_generation_publication_transport.rs"
REGISTRATION = A + "authority_host_publication_registration.rs"
CALLERS = {
    "root_c_grant_enroll": [
        "codex-rs/hepta-agentd/src/authority_host_publication_registration.rs"
    ],
    "root_c_grant_begin": [
        "codex-rs/hepta-agentd/src/authority_host_publication_grant.rs"
    ],
    "root_c_grant_finish": [
        "codex-rs/hepta-agentd/src/authority_host_publication_grant.rs"
    ],
    "root_c_grant_context": [
        "codex-rs/hepta-agentd/src/authority_host_publication_grant.rs"
    ],
    "root_c_grant_dispatch": [
        "codex-rs/hepta-agentd/src/authority_host_generation_publication_transport.rs"
    ],
    "root_c_grant_issuer_admission": [
        "codex-rs/hepta-agentd/src/authority_host_publication_grant.rs"
    ],
    "root_c_grant_sealed_parts": [
        "codex-rs/hepta-agentd/src/deployment_publication.rs"
    ],
    "root_c_grant_registered_issuer": [
        "codex-rs/hepta-agentd/src/deployment_calculator.rs",
        "codex-rs/hepta-agentd/src/deployment_notes.rs",
        "codex-rs/hepta-agentd/src/deployment_publication.rs"
    ],
    "root_c_grant_joint_tokens": [
        "codex-rs/hepta-agentd/src/deployment_desktop.rs",
        "codex-rs/hepta-agentd/src/authority_host_publication_grant_context.rs"
    ],
    "root_c_grant_client": [
        "codex-rs/hepta-agentd/src/neuron_generation_current_store.rs"
    ],
    "root_c_grant_store_dispatch": [
        "codex-rs/hepta-agentd/src/neuron_generation_current_root.rs"
    ],
    "root_c_grant_current_owner": [
        "codex-rs/hepta-agentd/src/neuron_generation_update.rs"
    ],
    "root_c_grant_prepared_owner": [
        "codex-rs/hepta-agentd/src/cell_q24_publication_successor_grant.rs"
    ],
    "q24_successor_original_root_sign": [
        "codex-rs/hepta-agentd/src/circuit_q24_successor_worker.rs"
    ],
    "q24_successor_root_signed_finish": [
        "codex-rs/hepta-agentd/src/production_post_a_continuation.rs"
    ]
}


def span(code, marker):
    matches = list(re.finditer(route.token_pattern(marker), code))
    if len(matches) != 1:
        raise PROOF.VerificationFailure("one actual C grant closure required")
    start = code.index("{", matches[0].start())
    depth = 1
    for end in range(start + 1, len(code)):
        depth += (code[end] == "{") - (code[end] == "}")
        if depth == 0:
            return start, end + 1
    raise PROOF.VerificationFailure("C grant closure must have a real body")


def position(code, marker):
    found = list(re.finditer(route.token_pattern(marker), code))
    if len(found) != 1:
        raise PROOF.VerificationFailure("one actual C grant operation required")
    return found[0].start()


def top_level(code, marker):
    prefix = code[:position(code, marker)]
    if prefix.count("{") - prefix.count("}") != 1:
        raise PROOF.VerificationFailure("C grant postcheck cannot be conditional")


def require_structure(path, source):
    if path == GRANT:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index("struct RootPreparedPublicationGrantV1")
        begin, end = span(code[start:], "struct RootPreparedPublicationGrantV1<'a> {")
        if re.search(r"\bpub\b", code[start + begin + 1:start + end - 1]):
            raise PROOF.VerificationFailure("raw data cannot construct a Root C admission")
        body, _ = route.function(source, "fn issue_generation_publication_grant(")
        lo, hi = span(body, "|initial, proof, writer, writer_proof, lease_expiry| {")
        for marker in (
            "RegisteredPublicationGrant::begin(grant)?",
            "RootPreparedPublicationGrantV1 {",
            "self.issuer.issue_original_publication_final_use(admitted)",
        ):
            if not lo < position(body, marker) < hi:
                raise PROOF.VerificationFailure("original signing stays in the joint token context")
        for marker in ("let signed = issued?", "RegisteredPublicationGrant::finish(grant, &signed)?"):
            if position(body, marker) <= hi:
                raise PROOF.VerificationFailure("retain signature only after complete context postchecks")
            top_level(body, marker)
    if path == CONTEXT:
        body, _ = route.function(source, "fn with_generation_grant_context<T>(")
        lo, hi = span(body, "|issuer_lease| {")
        for marker in (
            "let result = action(initial, proof, &writer.registration, &writer.proof, expiry)",
            "self.issuer.revocations()? != before",
        ):
            if not lo < position(body, marker) < hi:
                raise PROOF.VerificationFailure("action and error postchecks hold the same original tokens")
    if path == STORE:
        body, _ = route.function(source, "fn enroll(")
        lo, hi = span(body, "RootGenerationPublicationModeV1::Recover => {")
        if "initialize" in body[lo:hi] or "None =>" in body[lo:hi]:
            raise PROOF.VerificationFailure("cold recovery cannot initialize a missing issue slot")
    if path == TRANSPORT:
        body, _ = route.function(source, "fn serve_generation_publication_with_end(")
        lo, hi = span(body, "PublicationRefusal::inspect(&slot.refusal, &slot.reserved, end, || {")
        if not lo < position(body, "HostAuthorityService::issue_generation_publication_grant(") < hi:
            raise PROOF.VerificationFailure("same actual publication refusal encloses C signing")


class OriginalCGrantRootSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[name].definition_path for name in CALLERS}
        paths.update(path for values in CALLERS.values() for path in values)
        paths.update(A + name for name in (
            "authority_host_service.rs", "root_generation_current_client.rs",
            "authority_host_generation_publication.rs",
        ))
        cls.sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }

    def mutate(self, path, change):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, text)
            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_actual_registered_callers_and_legacy_empty_product_edge(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for name, expected in CALLERS.items():
            with self.subTest(boundary=name):
                row = self.boundaries[name]
                self.assertEqual(row.product_callers, tuple(expected))
                self.assertIn(name, inventory)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
        self.assertEqual(self.boundaries["q24_successor_original_signed_finish"].product_callers, ())

    def test_unregistered_and_removed_actual_callers_are_rejected(self):
        for name in CALLERS:
            with self.subTest(boundary=name):
                row = self.boundaries[name]
                method = row.symbol.rsplit("::", 1)[-1]
                sources = dict(self.sources)
                sources[A + "unregistered_original_c_grant.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_attempt_and_signature_are_retained_without_recovery_issue(self):
        self.check(STORE, "enroll", (
            "ReservedPublicationProfile::original_for_version(", "PublicationVersion::DurableV2",
            "profile.learning_operation.as_bytes()", "RootGenerationPublicationModeV1::Reserve",
            "RootGenerationPublicationModeV1::Recover", "HostAuthorityFrontierStore::open(",
            "retained.require_exact()?",
        ))
        self.check(STORE, "begin", (
            "self.mode != RootGenerationPublicationModeV1::Reserve",
            "self.attempted.swap(true, Ordering::AcqRel)", "let before = self.load_original()?",
            "before.state != (GrantPhase::Available {})", "attempted.state = GrantPhase::Attempted {}",
            "compare_and_set(&self.owner, &before, &attempted)", "self.load_original()? != attempted",
        ))
        self.check(STORE, "finish", (
            "self.mode != RootGenerationPublicationModeV1::Reserve",
            "!self.attempted.load(Ordering::Acquire)", "self.require_binding(signed)?",
            "before.state != (GrantPhase::Attempted {})", "signed: signed.clone()",
            "compare_and_set(&self.owner, &before, &issued)", "self.load_original()? != issued",
        ))
        self.reject(STORE, "require_exact", "GrantPhase::Attempted {} => Err(")
        self.reject(STORE, "load_original", "record.original != self.original")

    def test_slot_current_decision_selection_and_exact_cut_are_required(self):
        self.check(GRANT, "require_grant_cut", (
            "PublicationVersion::DurableV2", "self.profile.intent.supersedes.is_some()",
            "NeuronGenerationPredecessorCompletionV1::OwnerDrained",
            "NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel",
            "self.require_profile()?", "self.require_history(learning, scope)?",
            "self.require_previous()?", "self.require_genesis()?", "self.require_selection(now)?",
            "original_broker_head()", "head.current != self.profile.intent.previous",
            "head.prepared.as_ref() != Some(&self.profile.intent)",
        ))

    def test_whole_joint_context_precedes_durable_signature_and_response(self):
        self.check(GRANT, "issue_generation_publication_grant", (
            "Command::IssueFinalUse { expected, intent }", "request.schema != version.schema()",
            "request.purpose != version.purpose()", "request.profile != slot.profile.binding",
            "request.request_id != *sequence", "sequence.checked_add(1)", "slot.grant.as_ref()",
            "self.with_generation_grant_context(", "slot.profile.writer != proof",
            "slot.profile.identity", "neuron_generation_process_identity_digest_v1(&self.identity)",
            "*expected != head_digest(&head)?", "slot.profile.intent.digest()", "min(lease_expiry)",
            "RegisteredPublicationGrant::begin(grant)?", "binding: slot.profile.intent.binding()",
            "self.issuer.issue_original_publication_final_use(admitted)",
            "before.as_ref() != Some(&after)", "let signed = issued?", "raw.len() > 16 * 1024",
            "RegisteredPublicationGrant::finish(grant, &signed)?",
            "slot.require_grant_cut(learning, &scope, final_time)? != after",
            "final_time >= signed.grant.expires_at_unix_ms",
        ))
        self.reject(GRANT, "issue_generation_publication_grant", "refusal::require_end(end)?", 2)
        self.reject(GRANT, "issue_generation_publication_grant", "refusal::require_end(end)?", 3)

    def test_joint_writer_issuer_and_error_postchecks_cannot_be_skipped(self):
        self.check(CONTEXT, "with_generation_grant_context<T>", (
            "config.required_bind.verify()?", "config.schema_version != 1",
            "registration.registered_identity.identity()? != self.identity",
            "config.writer.as_ref() != Some(&writer.registration)",
            "with_live_issuer_and_writer(&writer.registration, |issuer_lease| {",
            "learning.profile.require_binding(&self.identity, &proof)?",
            "validate_observation_lease(issuer_lease, &before, now)?",
            "let result = action(initial, proof, &writer.registration, &writer.proof, expiry)",
            "self.issuer.revocations()? != before",
            "validate_observation_lease(issuer_lease, &before, after)?",
        ))
        for marker in ("self.check_logind_lifetime()?", "verify_pinned_process(",
                       "retained_writer_authorization(&writer.registration)?"):
            self.reject(CONTEXT, "with_generation_grant_context<T>", marker, 1)
        self.check(ISSUER, "issue_original_publication_final_use", (
            "admitted: RootPreparedPublicationGrantV1<'_>", "admitted.into_original_parts()",
            "self.issue_registered_final_use(&binding, registration, proof, expiry)",
        ))

    def test_private_admission_and_same_physical_refusal_have_no_raw_constructor(self):
        self.mutate(GRANT, lambda source: source.replace(
            "    binding: FinalUseBinding,", "    pub(crate) binding: FinalUseBinding,", 1))
        self.reject(TRANSPORT, "serve_generation_publication_with_end",
                    "PublicationRefusal::inspect(&slot.refusal, &slot.reserved, end, || {")
        self.reject(TRANSPORT, "serve_generation_publication_with_end", "let _ = RegisteredGenerationPublication::refuse(slot);")
        self.reject(REGISTRATION, "enroll_generation_publication",
                    "if version == PublicationVersion::DurableV2")
        self.reject(REGISTRATION, "enroll_generation_publication",
                    "enrolled.grant = Some(RegisteredPublicationGrant::enroll(")


if __name__ == "__main__":
    unittest.main()
