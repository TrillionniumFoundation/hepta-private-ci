use std::collections::BTreeSet;

use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone, Debug)]
struct FixtureAdmissionSnapshot {
    snapshot_digest: Digest32,
    revocation_frontier_digest: Digest32,
    admission_salt: &'static str,
    revoked: BTreeSet<StableId>,
}

impl FixtureAdmissionSnapshot {
    fn initial() -> Self {
        Self {
            snapshot_digest: digest("admission-snapshot:initial"),
            revocation_frontier_digest: digest("revocation-frontier:initial"),
            admission_salt: "stable-admission",
            revoked: BTreeSet::new(),
        }
    }

    fn advanced() -> Self {
        Self {
            snapshot_digest: digest("admission-snapshot:advanced"),
            revocation_frontier_digest: digest("revocation-frontier:advanced"),
            admission_salt: "stable-admission",
            revoked: BTreeSet::new(),
        }
    }

    fn incompatible() -> Self {
        Self {
            snapshot_digest: digest("admission-snapshot:other"),
            revocation_frontier_digest: digest("revocation-frontier:other"),
            admission_salt: "different-admission",
            revoked: BTreeSet::new(),
        }
    }

    fn with_revoked(item_id: &str) -> Self {
        let mut snapshot = Self::advanced();
        snapshot.revoked.insert(id(item_id));
        snapshot
    }

    fn admission_digest(&self, claim: &ContextAdmissionClaimV2) -> Digest32 {
        let mut bytes = self.admission_salt.as_bytes().to_vec();
        bytes.extend_from_slice(claim.item_id.as_str().as_bytes());
        bytes.push(match claim.role {
            ContextRoleV2::TrustedInstruction => 0,
            ContextRoleV2::Schema => 1,
            ContextRoleV2::UntrustedEvidence => 2,
        });
        bytes.extend_from_slice(claim.content_digest.as_array());
        bytes.extend_from_slice(claim.source_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

impl ContextAdmissionSnapshotVerifierV2 for FixtureAdmissionSnapshot {
    fn verifier_digest(&self) -> Digest32 {
        digest("fixture-admission-verifier:v1")
    }

    fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    fn revocation_frontier_digest(&self) -> Digest32 {
        self.revocation_frontier_digest
    }

    fn verify_admitted(
        &self,
        claim: &ContextAdmissionClaimV2,
        at_unix_ms: u64,
    ) -> Result<ContextAdmissionDecisionV2, String> {
        if at_unix_ms == 0 {
            return Err("zero verification time".to_string());
        }
        if claim.contains_secret {
            return Err("secret material is not admitted".to_string());
        }
        if self.revoked.contains(&claim.item_id) {
            return Err("candidate is revoked".to_string());
        }
        Ok(ContextAdmissionDecisionV2 {
            source_admission_digest: self.admission_digest(claim),
            expires_at_unix_ms: 10_000,
        })
    }
}

#[derive(Clone, Copy, Debug)]
struct ByteTokenizer;

impl ExactContextTokenizerV2 for ByteTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("byte-tokenizer:v1")
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, String> {
        u64::try_from(bytes.len()).map_err(|_| "token count overflow".to_string())
    }
}

#[derive(Clone, Copy, Debug)]
struct PlainSerializer;

impl ContextSerializerV2 for PlainSerializer {
    fn serializer_digest(&self) -> Digest32 {
        digest("plain-serializer:v1")
    }

    fn template_digest(&self) -> Digest32 {
        digest("template:v1")
    }

    fn tool_schema_digest(&self) -> Digest32 {
        digest("tools:v1")
    }

    fn serialize(
        &self,
        _compiled: &CompiledContextV2,
        items: &[ContextMaterializedItemV2],
    ) -> Result<Vec<u8>, String> {
        let mut payload = Vec::new();
        for item in items {
            payload.extend_from_slice(&item.content);
        }
        Ok(payload)
    }
}

#[derive(Clone, Copy, Debug)]
struct FramingSerializer;

impl ContextSerializerV2 for FramingSerializer {
    fn serializer_digest(&self) -> Digest32 {
        digest("framing-serializer:v1")
    }

    fn template_digest(&self) -> Digest32 {
        digest("template:v1")
    }

    fn tool_schema_digest(&self) -> Digest32 {
        digest("tools:v1")
    }

    fn serialize(
        &self,
        _compiled: &CompiledContextV2,
        items: &[ContextMaterializedItemV2],
    ) -> Result<Vec<u8>, String> {
        let mut payload = b"<context>".to_vec();
        for item in items {
            payload.extend_from_slice(&item.content);
        }
        payload.extend_from_slice(b"</context>");
        Ok(payload)
    }
}

#[derive(Clone, Copy, Debug)]
struct FixtureDeliveryVerifier;

impl ContextProviderDeliveryVerifierV2 for FixtureDeliveryVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("provider-evidence-store:v1")
    }

    fn verify_delivery(
        &self,
        receipt: &ProviderInvocationReceipt,
    ) -> Result<ContextProviderDeliveryDecisionV2, String> {
        Ok(ContextProviderDeliveryDecisionV2 {
            evidence_digest: Digest32::of_bytes(&receipt.canonical_wire_bytes()?),
            recorded_at_unix_ms: 45,
        })
    }
}

#[derive(Clone, Copy, Debug)]
struct RejectDeliveryVerifier;

impl ContextProviderDeliveryVerifierV2 for RejectDeliveryVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("provider-evidence-store:v1")
    }

    fn verify_delivery(
        &self,
        _receipt: &ProviderInvocationReceipt,
    ) -> Result<ContextProviderDeliveryDecisionV2, String> {
        Err("provider receipt is absent from the independent evidence owner".to_string())
    }
}

fn profile(serializer_digest: Digest32) -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        model_digest: digest("model-artifact:v1"),
        provider_id_digest: digest("provider-1"),
        provider_model_digest: digest("model-1"),
        tokenizer_digest: ByteTokenizer.tokenizer_digest(),
        serializer_digest,
        template_digest: digest("template:v1"),
        tool_schema_digest: digest("tools:v1"),
        maximum_context_tokens: 1_000,
    }
}

fn draft(
    item_id: &str,
    role: ContextRoleV2,
    expected_value: FixedQ32,
) -> ContextCandidateDraftV2 {
    ContextCandidateDraftV2 {
        item_id: id(item_id),
        role,
        source_digest: digest(&format!("source:{item_id}")),
        generation_vector_digest: digest("generation-vector:v1"),
        expected_value,
        contains_secret: false,
    }
}

fn candidate(
    snapshot: &FixtureAdmissionSnapshot,
    item_id: &str,
    role: ContextRoleV2,
    content: &[u8],
    expected_value: FixedQ32,
) -> (ContextCandidateV2, ContextMaterializedItemV2) {
    let candidate = verify_context_candidate_v2(
        draft(item_id, role, expected_value),
        content,
        snapshot,
        &ByteTokenizer,
        10,
    )
    .unwrap_or_else(|error| panic!("valid admitted candidate: {error}"));
    let materialized = ContextMaterializedItemV2 {
        item_id: id(item_id),
        content: content.to_vec(),
    };
    (candidate, materialized)
}

fn request(
    snapshot: &FixtureAdmissionSnapshot,
    serializer_digest: Digest32,
    candidates: Vec<ContextCandidateV2>,
    token_budget: u64,
) -> ContextCompilationRequestV2 {
    ContextCompilationRequestV2 {
        compilation_id: id("compilation:1"),
        objective_digest: digest("objective:v1"),
        prompt_portfolio_digest: digest("portfolio:v1"),
        generation_vector_digest: digest("generation-vector:v1"),
        admission_verifier_digest: snapshot.verifier_digest(),
        admission_snapshot_digest: snapshot.snapshot_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(),
        model_profile: profile(serializer_digest),
        token_budget,
        truncation_policy_digest: digest("truncation-policy:v1"),
        compiled_at_unix_ms: 20,
        candidates,
        mandatory_groups: Vec::new(),
    }
}

fn compile_plain(
    snapshot: &FixtureAdmissionSnapshot,
    candidates: Vec<ContextCandidateV2>,
    token_budget: u64,
) -> CompiledContextV2 {
    compile_v2(request(
        snapshot,
        PlainSerializer.serializer_digest(),
        candidates,
        token_budget,
    ))
    .unwrap_or_else(|error| panic!("valid compilation: {error}"))
}

fn serialize_plain(
    compiled: &CompiledContextV2,
    items: Vec<ContextMaterializedItemV2>,
) -> SerializedContextV2 {
    serialize_context_exact(
        compiled,
        id("serialization:1"),
        items,
        &PlainSerializer,
        &ByteTokenizer,
        30,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"))
}

fn attach(
    compiled: &CompiledContextV2,
    serialized: &SerializedContextV2,
    snapshot: &FixtureAdmissionSnapshot,
) -> ContextAttachmentV2 {
    build_attachment(
        compiled,
        serialized,
        id("attachment:1"),
        snapshot,
        &ByteTokenizer,
        40,
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"))
}

fn provider_receipt(
    attachment: &ContextAttachmentV2,
    provider_id: &str,
    model: &str,
    terminal: ProviderTerminal,
) -> ProviderInvocationReceipt {
    provider_receipt_with_input(
        attachment,
        provider_id,
        model,
        Sha256Digest::for_bytes(attachment.payload()),
        terminal,
    )
}

fn provider_receipt_with_input(
    _attachment: &ContextAttachmentV2,
    provider_id: &str,
    model: &str,
    input_digest: Sha256Digest,
    terminal: ProviderTerminal,
) -> ProviderInvocationReceipt {
    let binding = ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-request-1"),
        request_kind: ProviderRequestKind::Turn,
        provider_id: provider_id.to_string(),
        provider_config_sha256: Sha256Digest::for_bytes(b"provider-config"),
        model: model.to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
        logical_request_sha256: Sha256Digest::for_bytes(b"logical-request"),
        wire_semantic_sha256: Sha256Digest::for_bytes(b"wire-semantics"),
        ephemeral_input_sha256: Some(input_digest),
        ephemeral_input_witness_sha256: Some(Sha256Digest::for_bytes(b"host-send-witness")),
        previous_response_id_sha256: None,
        generate: true,
    };
    let intent = ProviderInvocationIntent::for_host_attempt_id("host-attempt-1", binding);
    ProviderInvocationReceipt::new(intent, terminal)
}

fn completed_terminal() -> ProviderTerminal {
    ProviderTerminal::Completed {
        response_id_sha256: Sha256Digest::for_bytes(b"response-id"),
        response_items_sha256: Sha256Digest::for_bytes(b"response-items"),
        token_usage_sha256: Sha256Digest::for_bytes(b"token-usage"),
        end_turn: Some(true),
    }
}

#[test]
fn deterministic_value_per_token_preserves_admitted_mandatory_floors() {
    let snapshot = FixtureAdmissionSnapshot::initial();
    let (trusted, _) = candidate(
        &snapshot,
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        FixedQ32::ONE,
    );
    let (schema, _) = candidate(
        &snapshot,
        "item:schema",
        ContextRoleV2::Schema,
        b"bbbbbbbbbbbbbbbbbbbb",
        FixedQ32::ONE,
    );
    let (high_ratio, _) = candidate(
        &snapshot,
        "item:high-ratio",
        ContextRoleV2::UntrustedEvidence,
        b"cccccccccccccccccccc",
        FixedQ32::from_raw(1_i64 << 31),
    );
    let (low_ratio, _) = candidate(
        &snapshot,
        "item:low-ratio",
        ContextRoleV2::UntrustedEvidence,
        b"dddddddddddddddddddddddddddddddddddddddd",
        FixedQ32::from_raw(1_i64 << 31),
    );
    let candidates = vec![
        low_ratio.clone(),
        trusted.clone(),
        high_ratio.clone(),
        schema.clone(),
    ];
    let mut reversed = candidates.clone();
    reversed.reverse();

    let left = compile_plain(&snapshot, candidates, 80);
    let right = compile_plain(&snapshot, reversed, 80);

    assert_eq!(left, right);
    assert_eq!(left.receipt().used_tokens, 80);
    assert_eq!(
        left.receipt().selected_item_ids,
        vec![
            trusted.item_id().clone(),
            schema.item_id().clone(),
            high_ratio.item_id().clone()
        ]
    );
    assert_eq!(
        left.receipt().omitted_item_ids,
        vec![low_ratio.item_id().clone()]
    );
}

#[test]
fn candidate_creation_requires_current_admission_and_exact_tokenizer() {
    let revoked = FixtureAdmissionSnapshot::with_revoked("item:revoked");
    assert!(matches!(
        verify_context_candidate_v2(
            draft(
                "item:revoked",
                ContextRoleV2::TrustedInstruction,
                FixedQ32::ONE,
            ),
            b"trusted",
            &revoked,
            &ByteTokenizer,
            10,
        ),
        Err(ContextCompilerV2Error::AdmissionVerifierFailed { .. })
    ));

    let snapshot = FixtureAdmissionSnapshot::initial();
    let (verified, _) = candidate(
        &snapshot,
        "item:verified",
        ContextRoleV2::TrustedInstruction,
        b"exact-bytes",
        FixedQ32::ONE,
    );
    assert_eq!(verified.token_count(), 11);
    assert_eq!(
        verified.admission_receipt().snapshot_digest(),
        snapshot.snapshot_digest()
    );
}

#[test]
fn compile_rejects_candidate_from_another_admission_snapshot() {
    let initial = FixtureAdmissionSnapshot::initial();
    let other = FixtureAdmissionSnapshot::incompatible();
    let (candidate, _) = candidate(
        &other,
        "item:other-snapshot",
        ContextRoleV2::UntrustedEvidence,
        b"evidence",
        FixedQ32::ONE,
    );

    assert_eq!(
        compile_v2(request(
            &initial,
            PlainSerializer.serializer_digest(),
            vec![candidate],
            100,
        )),
        Err(ContextCompilerV2Error::AdmissionSnapshotMismatch(
            "item:other-snapshot".to_string()
        ))
    );
}

#[test]
fn tiny_budget_refuses_instead_of_truncating_instruction_or_schema() {
    let snapshot = FixtureAdmissionSnapshot::initial();
    let (trusted, _) = candidate(
        &snapshot,
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        FixedQ32::ONE,
    );
    let (schema, _) = candidate(
        &snapshot,
        "item:schema",
        ContextRoleV2::Schema,
        b"bbbbbbbbbbbbbbbbbbbb",
        FixedQ32::ONE,
    );

    assert_eq!(
        compile_v2(request(
            &snapshot,
            PlainSerializer.serializer_digest(),
            vec![trusted, schema],
            50,
        )),
        Err(ContextCompilerV2Error::InsufficientMandatoryBudget {
            required_tokens: 60,
            token_budget: 50,
        })
    );
}

#[test]
fn mandatory_group_policy_is_bound_even_when_selection_is_unchanged() {
    let snapshot = FixtureAdmissionSnapshot::initial();
    let (first, _) = candidate(
        &snapshot,
        "item:citation",
        ContextRoleV2::UntrustedEvidence,
        b"citation",
        FixedQ32::ZERO,
    );
    let (second, _) = candidate(
        &snapshot,
        "item:contradiction",
        ContextRoleV2::UntrustedEvidence,
        b"contradiction",
        FixedQ32::ZERO,
    );
    let candidates = vec![first.clone(), second.clone()];

    let mut left_request = request(
        &snapshot,
        PlainSerializer.serializer_digest(),
        candidates.clone(),
        100,
    );
    left_request.mandatory_groups = vec![MandatoryContextGroupV2 {
        group_id: id("group:evidence"),
        item_ids: vec![first.item_id().clone(), second.item_id().clone()],
        reason_digest: digest("reason:a"),
    }];
    let mut right_request = request(
        &snapshot,
        PlainSerializer.serializer_digest(),
        candidates,
        100,
    );
    right_request.mandatory_groups = vec![MandatoryContextGroupV2 {
        group_id: id("group:evidence"),
        item_ids: vec![second.item_id().clone(), first.item_id().clone()],
        reason_digest: digest("reason:b"),
    }];

    let left =
        compile_v2(left_request).unwrap_or_else(|error| panic!("left compilation: {error}"));
    let right =
        compile_v2(right_request).unwrap_or_else(|error| panic!("right compilation: {error}"));

    assert_eq!(
        left.receipt().selected_item_ids,
        right.receipt().selected_item_ids
    );
    assert_ne!(
        left.receipt().mandatory_groups_digest,
        right.receipt().mandatory_groups_digest
    );
    assert_ne!(left.receipt().receipt_digest, right.receipt().receipt_digest);
}

#[test]
fn final_serialized_payload_is_retokenized_and_can_exceed_candidate_budget() {
    let snapshot = FixtureAdmissionSnapshot::initial();
    let (evidence, materialized) = candidate(
        &snapshot,
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        b"0123456789",
        FixedQ32::ONE,
    );
    let compiled = compile_v2(request(
        &snapshot,
        FramingSerializer.serializer_digest(),
        vec![evidence],
        15,
    ))
    .unwrap_or_else(|error| panic!("candidate compilation fits: {error}"));

    assert_eq!(compiled.receipt().used_tokens, 10);
    assert_eq!(
        serialize_context_exact(
            &compiled,
            id("serialization:framed"),
            vec![materialized],
            &FramingSerializer,
            &ByteTokenizer,
            30,
        ),
        Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
            serialized_tokens: 29,
            token_budget: 15,
        })
    );
}

#[test]
fn serialization_refuses_materialized_byte_drift() {
    let snapshot = FixtureAdmissionSnapshot::initial();
    let (evidence, mut materialized) = candidate(
        &snapshot,
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        b"admitted-evidence",
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&snapshot, vec![evidence], 100);
    materialized.content = b"different-evidence".to_vec();

    assert_eq!(
        serialize_context_exact(
            &compiled,
            id("serialization:drift"),
            vec![materialized],
            &PlainSerializer,
            &ByteTokenizer,
            30,
        ),
        Err(ContextCompilerV2Error::MaterializedContentMismatch(
            "item:evidence".to_string()
        ))
    );
}

#[test]
fn attachment_revalidates_current_revocation_and_fails_closed() {
    let initial = FixtureAdmissionSnapshot::initial();
    let (evidence, materialized) = candidate(
        &initial,
        "item:revocable",
        ContextRoleV2::UntrustedEvidence,
        b"revocable",
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&initial, vec![evidence], 100);
    let serialized = serialize_plain(&compiled, vec![materialized]);
    let revoked = FixtureAdmissionSnapshot::with_revoked("item:revocable");

    assert!(matches!(
        build_attachment(
            &compiled,
            &serialized,
            id("attachment:revoked"),
            &revoked,
            &ByteTokenizer,
            40,
        ),
        Err(ContextCompilerV2Error::AdmissionRevalidationFailed { .. })
    ));
}

#[test]
fn attachment_binds_the_new_current_snapshot_when_admission_remains_valid() {
    let initial = FixtureAdmissionSnapshot::initial();
    let advanced = FixtureAdmissionSnapshot::advanced();
    let (evidence, materialized) = candidate(
        &initial,
        "item:stable",
        ContextRoleV2::UntrustedEvidence,
        b"stable-evidence",
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&initial, vec![evidence], 100);
    let serialized = serialize_plain(&compiled, vec![materialized]);
    let attachment = attach(&compiled, &serialized, &advanced);

    assert_eq!(
        attachment.admission_snapshot_digest(),
        advanced.snapshot_digest()
    );
    assert_eq!(
        attachment.revocation_frontier_digest(),
        advanced.revocation_frontier_digest()
    );
    assert_ne!(
        attachment.admission_snapshot_digest(),
        compiled.receipt().admission_snapshot_digest
    );
}

#[test]
fn exact_provider_receipt_and_independent_evidence_form_delivery_receipt() {
    let initial = FixtureAdmissionSnapshot::initial();
    let (trusted, materialized) = candidate(
        &initial,
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        b"trusted-context",
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&initial, vec![trusted], 100);
    let serialized = serialize_plain(&compiled, vec![materialized]);
    let attachment = attach(&compiled, &serialized, &initial);
    let provider = provider_receipt(&attachment, "provider-1", "model-1", completed_terminal());

    let observation = observe_delivery(
        &attachment,
        id("observation:1"),
        &provider,
        &FixtureDeliveryVerifier,
        50,
    )
    .unwrap_or_else(|error| panic!("valid delivery observation: {error}"));

    assert_eq!(
        observation.disposition(),
        ContextDeliveryDispositionV2::Delivered
    );
    assert_eq!(observation.authority(), AuthorityPosture::DENY_ALL);
    observation
        .validate_for(&attachment)
        .unwrap_or_else(|error| panic!("delivery receipt validates: {error}"));
}

#[test]
fn provider_payload_mismatch_cannot_be_recorded_as_delivery() {
    let initial = FixtureAdmissionSnapshot::initial();
    let (evidence, materialized) = candidate(
        &initial,
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        b"expected-payload",
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&initial, vec![evidence], 100);
    let serialized = serialize_plain(&compiled, vec![materialized]);
    let attachment = attach(&compiled, &serialized, &initial);
    let provider = provider_receipt_with_input(
        &attachment,
        "provider-1",
        "model-1",
        Sha256Digest::for_bytes(b"different-payload"),
        completed_terminal(),
    );

    assert_eq!(
        observe_delivery(
            &attachment,
            id("observation:mismatch"),
            &provider,
            &FixtureDeliveryVerifier,
            50,
        ),
        Err(ContextCompilerV2Error::DeliveryMismatch)
    );
}

#[test]
fn provider_model_drift_is_rejected_even_with_matching_payload() {
    let initial = FixtureAdmissionSnapshot::initial();
    let (evidence, materialized) = candidate(
        &initial,
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        b"payload",
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&initial, vec![evidence], 100);
    let serialized = serialize_plain(&compiled, vec![materialized]);
    let attachment = attach(&compiled, &serialized, &initial);
    let provider = provider_receipt(&attachment, "provider-1", "model-2", completed_terminal());

    assert_eq!(
        observe_delivery(
            &attachment,
            id("observation:model-drift"),
            &provider,
            &FixtureDeliveryVerifier,
            50,
        ),
        Err(ContextCompilerV2Error::ProviderModelProfileMismatch)
    );
}

#[test]
fn independent_delivery_evidence_is_mandatory() {
    let initial = FixtureAdmissionSnapshot::initial();
    let (evidence, materialized) = candidate(
        &initial,
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        b"payload",
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&initial, vec![evidence], 100);
    let serialized = serialize_plain(&compiled, vec![materialized]);
    let attachment = attach(&compiled, &serialized, &initial);
    let provider = provider_receipt(&attachment, "provider-1", "model-1", completed_terminal());

    assert!(matches!(
        observe_delivery(
            &attachment,
            id("observation:no-evidence"),
            &provider,
            &RejectDeliveryVerifier,
            50,
        ),
        Err(ContextCompilerV2Error::ProviderEvidenceInvalid(_))
    ));
}

#[test]
fn provider_indeterminate_terminal_never_becomes_delivered() {
    let initial = FixtureAdmissionSnapshot::initial();
    let (evidence, materialized) = candidate(
        &initial,
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        b"payload",
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&initial, vec![evidence], 100);
    let serialized = serialize_plain(&compiled, vec![materialized]);
    let attachment = attach(&compiled, &serialized, &initial);
    let provider = provider_receipt(
        &attachment,
        "provider-1",
        "model-1",
        ProviderTerminal::Indeterminate {
            reason_code: "transport_unknown".to_string(),
            partial_response_sha256: None,
        },
    );

    let observation = observe_delivery(
        &attachment,
        id("observation:indeterminate"),
        &provider,
        &FixtureDeliveryVerifier,
        50,
    )
    .unwrap_or_else(|error| panic!("valid indeterminate observation: {error}"));

    assert_eq!(
        observation.disposition(),
        ContextDeliveryDispositionV2::Indeterminate
    );
}

#[test]
fn debug_output_does_not_expose_materialized_or_serialized_payload_bytes() {
    let initial = FixtureAdmissionSnapshot::initial();
    let raw = b"do-not-log-this-context-body";
    let (evidence, materialized) = candidate(
        &initial,
        "item:redacted",
        ContextRoleV2::UntrustedEvidence,
        raw,
        FixedQ32::ONE,
    );
    let compiled = compile_plain(&initial, vec![evidence], 100);
    let serialized = serialize_plain(&compiled, vec![materialized]);

    let serialized_debug = format!("{serialized:?}");
    assert!(!serialized_debug.contains("do-not-log-this-context-body"));
    assert!(serialized_debug.contains("payload_digest"));
}
