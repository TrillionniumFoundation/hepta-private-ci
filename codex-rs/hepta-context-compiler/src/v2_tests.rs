use super::*;

use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTransport;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone, Copy)]
struct ByteTokenizer;

impl ExactTokenizerV2 for ByteTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("tokenizer")
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        Ok(u64::try_from(bytes.len()).unwrap_or(u64::MAX))
    }
}

#[derive(Clone, Copy)]
struct TestAdmissionVerifier {
    accept_record: bool,
    accept_snapshot: bool,
}

impl ContextAdmissionVerifierV2 for TestAdmissionVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("admission-verifier")
    }

    fn verify_record(&self, _record: &ContextAdmissionRecordV2) -> bool {
        self.accept_record
    }

    fn verify_snapshot(&self, _snapshot: &ContextAdmissionSnapshotV2) -> bool {
        self.accept_snapshot
    }
}

fn verifier() -> TestAdmissionVerifier {
    TestAdmissionVerifier {
        accept_record: true,
        accept_snapshot: true,
    }
}

struct FramingSerializer {
    overhead: usize,
}

impl ContextSerializerV2 for FramingSerializer {
    fn serializer_digest(&self) -> Digest32 {
        digest("serializer")
    }

    fn template_digest(&self) -> Digest32 {
        digest("template")
    }

    fn tool_schema_digest(&self) -> Digest32 {
        digest("tool-schema")
    }

    fn serialize(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<Vec<u8>, ContextCompilerV2Error> {
        let mut payload = vec![b'F'; self.overhead];
        for item in items {
            payload.extend_from_slice(&item.content);
        }
        Ok(payload)
    }
}

struct TestDeliveryVerifier {
    accept: bool,
    recorded_at_unix_ms: u64,
}

impl ContextProviderDeliveryVerifierV2 for TestDeliveryVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("delivery-verifier")
    }

    fn verify_delivery(
        &self,
        _receipt: &ProviderInvocationReceipt,
    ) -> Result<ContextProviderDeliveryDecisionV2, String> {
        if !self.accept {
            return Err("delivery evidence rejected".to_string());
        }
        Ok(ContextProviderDeliveryDecisionV2 {
            evidence_digest: digest("delivery-evidence"),
            recorded_at_unix_ms: self.recorded_at_unix_ms,
        })
    }
}

fn delivery_verifier() -> TestDeliveryVerifier {
    TestDeliveryVerifier {
        accept: true,
        recorded_at_unix_ms: 20,
    }
}

fn provider_receipt(
    serialization: &SerializedContextV2,
    preparation: &ContextDeliveryPreparationV2,
    provider_id: &str,
    provider_model: &str,
    input_override: Option<Sha256Digest>,
    witness_override: Option<Sha256Digest>,
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
        model: provider_model.to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
        logical_request_sha256: Sha256Digest::for_bytes(b"logical-request"),
        wire_semantic_sha256: Sha256Digest::for_bytes(b"wire-semantics"),
        ephemeral_input_sha256: Some(
            input_override.unwrap_or_else(|| Sha256Digest::for_bytes(serialization.payload())),
        ),
        ephemeral_input_witness_sha256: Some(witness_override.unwrap_or_else(|| {
            Sha256Digest::for_bytes(preparation.preparation_digest().as_array())
        })),
        previous_response_id_sha256: None,
        generate: true,
    };
    ProviderInvocationReceipt::new(
        ProviderInvocationIntent::for_host_attempt_id("host-attempt-1", binding),
        terminal,
    )
}

fn completed_terminal() -> ProviderTerminal {
    ProviderTerminal::Completed {
        response_id_sha256: Sha256Digest::for_bytes(b"response-id"),
        response_items_sha256: Sha256Digest::for_bytes(b"response-items"),
        token_usage_sha256: Sha256Digest::for_bytes(b"token-usage"),
        end_turn: Some(true),
    }
}

fn profile() -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        model_digest: digest("model-profile"),
        provider_id_digest: digest("provider"),
        provider_model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        serializer_digest: digest("serializer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        maximum_context_tokens: 1_000,
    }
}

fn verified_snapshot(
    snapshot_id: &str,
    observed_unix_ms: u64,
    revocation_epoch: u64,
    revoked: Vec<StableId>,
) -> VerifiedAdmissionSnapshotV2 {
    let raw = ContextAdmissionSnapshotV2::new(
        id(snapshot_id),
        observed_unix_ms,
        revocation_epoch,
        revoked,
    )
    .unwrap_or_else(|error| panic!("valid snapshot: {error}"));
    verify_admission_snapshot_v2(raw, &verifier())
        .unwrap_or_else(|error| panic!("verified snapshot: {error}"))
}

fn content_bytes(item_id: &str, token_count: u64) -> Vec<u8> {
    let len = usize::try_from(token_count).unwrap_or(usize::MAX);
    let source = item_id.as_bytes();
    let mut content = vec![b'x'; len];
    if !source.is_empty() {
        for (index, byte) in content.iter_mut().enumerate() {
            *byte = source[index % source.len()];
        }
    }
    content
}

fn candidate(
    item_id: &str,
    role: ContextRoleV2,
    token_count: u64,
    expected_value: FixedQ32,
    snapshot: &VerifiedAdmissionSnapshotV2,
) -> (ContextCandidateV2, ContextRealizedItemV2) {
    let content = content_bytes(item_id, token_count);
    let tokenizer = ByteTokenizer;
    let tokenization = TokenizationReceiptV2::from_exact_bytes(id(item_id), &content, &tokenizer)
        .unwrap_or_else(|error| panic!("valid tokenization: {error}"));
    let source_digest = digest(&format!("source:{item_id}"));
    let record = ContextAdmissionRecordV2::new(
        id(&format!("admission:{item_id}")),
        ContextAdmissionBindingV2 {
            item_id: id(item_id),
            role: role,
            content_digest: tokenization.content_digest(),
            source_digest: source_digest,
            generation_vector_digest: digest("generation-vector"),
            scope_digest: digest("scope"),
            contains_secret: false,
        },
        1,
        1_000,
    )
    .unwrap_or_else(|error| panic!("valid admission record: {error}"));
    let admission = verify_admission_v2(record, snapshot, &verifier())
        .unwrap_or_else(|error| panic!("valid admission: {error}"));
    (
        ContextCandidateV2 {
            item_id: id(item_id),
            role,
            content_digest: tokenization.content_digest(),
            source_digest,
            generation_vector_digest: digest("generation-vector"),
            tokenization,
            expected_value,
            admission,
        },
        ContextRealizedItemV2 {
            item_id: id(item_id),
            role,
            content,
        },
    )
}

fn request(candidates: Vec<ContextCandidateV2>, token_budget: u64) -> ContextCompilationRequestV2 {
    ContextCompilationRequestV2 {
        compilation_id: id("compilation:1"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation-vector"),
        scope_digest: digest("scope"),
        admission_verifier_digest: digest("admission-verifier"),
        model_profile: profile(),
        token_budget,
        truncation_policy_digest: digest("truncation-policy"),
        candidates,
        mandatory_groups: Vec::new(),
    }
}

#[test]
fn deterministic_value_per_token_preserves_mandatory_floors() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (trusted, _) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        40,
        FixedQ32::ONE,
        &snapshot,
    );
    let (schema, _) = candidate(
        "item:schema",
        ContextRoleV2::Schema,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let (high_ratio, _) = candidate(
        "item:high-ratio",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::from_raw(1_i64 << 31),
        &snapshot,
    );
    let (low_ratio, _) = candidate(
        "item:low-ratio",
        ContextRoleV2::UntrustedEvidence,
        40,
        FixedQ32::from_raw(1_i64 << 31),
        &snapshot,
    );
    let candidates = vec![
        low_ratio.clone(),
        trusted.clone(),
        high_ratio.clone(),
        schema.clone(),
    ];
    let mut reversed = candidates.clone();
    reversed.reverse();

    let left = compile_v2(request(candidates, 80))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let right = compile_v2(request(reversed, 80))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));

    assert_eq!(left, right);
    assert_eq!(left.receipt().used_tokens(), 80);
    assert_eq!(
        left.receipt().selected_item_ids(),
        &[trusted.item_id, schema.item_id, high_ratio.item_id]
    );
    assert_eq!(left.receipt().omitted_item_ids(), &[low_ratio.item_id]);
}

#[test]
fn tiny_budget_refuses_instead_of_truncating_instruction_or_schema() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (trusted, _) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        40,
        FixedQ32::ONE,
        &snapshot,
    );
    let (schema, _) = candidate(
        "item:schema",
        ContextRoleV2::Schema,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    assert_eq!(
        compile_v2(request(vec![trusted, schema], 50)),
        Err(ContextCompilerV2Error::InsufficientMandatoryBudget {
            required_tokens: 60,
            token_budget: 50,
        })
    );
}

#[test]
fn mandatory_group_policy_is_bound_even_when_selected_set_is_identical() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (first, _) = candidate(
        "item:citation",
        ContextRoleV2::UntrustedEvidence,
        30,
        FixedQ32::ONE,
        &snapshot,
    );
    let (second, _) = candidate(
        "item:contradiction",
        ContextRoleV2::UntrustedEvidence,
        30,
        FixedQ32::ONE,
        &snapshot,
    );

    let ungrouped = compile_v2(request(vec![first.clone(), second.clone()], 60))
        .unwrap_or_else(|error| panic!("valid ungrouped compilation: {error}"));
    let mut grouped_request = request(vec![first, second], 60);
    grouped_request.mandatory_groups = vec![MandatoryContextGroupV2 {
        group_id: id("group:evidence"),
        item_ids: vec![id("item:citation"), id("item:contradiction")],
        reason_digest: digest("citation-contradiction-obligation"),
    }];
    let grouped = compile_v2(grouped_request)
        .unwrap_or_else(|error| panic!("valid grouped compilation: {error}"));

    assert_eq!(
        ungrouped.receipt().selected_item_ids(),
        grouped.receipt().selected_item_ids()
    );
    assert_ne!(
        ungrouped.receipt().mandatory_groups_digest(),
        grouped.receipt().mandatory_groups_digest()
    );
    assert_ne!(
        ungrouped.receipt().receipt_digest(),
        grouped.receipt().receipt_digest()
    );
}

#[test]
fn well_formed_admission_digest_is_not_enough_without_verifier_acceptance() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let content = content_bytes("item:trusted", 20);
    let record = ContextAdmissionRecordV2::new(
        id("admission:item:trusted"),
        ContextAdmissionBindingV2 {
            item_id: id("item:trusted"),
            role: ContextRoleV2::TrustedInstruction,
            content_digest: Digest32::of_bytes(&content),
            source_digest: digest("source:item:trusted"),
            generation_vector_digest: digest("generation-vector"),
            scope_digest: digest("scope"),
            contains_secret: false,
        },
        1,
        1_000,
    )
    .unwrap_or_else(|error| panic!("valid admission record: {error}"));
    let rejecting = TestAdmissionVerifier {
        accept_record: false,
        accept_snapshot: true,
    };

    assert_eq!(
        verify_admission_v2(record, &snapshot, &rejecting),
        Err(ContextCompilerV2Error::AdmissionRecordUnverified(
            "admission:item:trusted".to_string()
        ))
    );
}

#[test]
fn admission_role_binding_prevents_evidence_instruction_confusion() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (mut trusted, _) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    trusted.role = ContextRoleV2::UntrustedEvidence;

    assert_eq!(
        compile_v2(request(vec![trusted], 100)),
        Err(ContextCompilerV2Error::AdmissionBindingMismatch(
            "item:trusted".to_string()
        ))
    );
}

#[test]
fn admission_expires_at_the_exact_expiry_instant() {
    let snapshot = verified_snapshot("snapshot:expiry", 1_000, 1, Vec::new());
    let content = content_bytes("item:expiry", 20);
    let record = ContextAdmissionRecordV2::new(
        id("admission:item:expiry"),
        ContextAdmissionBindingV2 {
            item_id: id("item:expiry"),
            role: ContextRoleV2::TrustedInstruction,
            content_digest: Digest32::of_bytes(&content),
            source_digest: digest("source:item:expiry"),
            generation_vector_digest: digest("generation-vector"),
            scope_digest: digest("scope"),
            contains_secret: false,
        },
        1,
        1_000,
    )
    .unwrap_or_else(|error| panic!("valid admission record: {error}"));

    assert_eq!(
        verify_admission_v2(record, &snapshot, &verifier()),
        Err(ContextCompilerV2Error::AdmissionExpired(
            "admission:item:expiry".to_string()
        ))
    );
}

#[test]
fn verified_admission_cannot_be_reused_across_request_scope() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (candidate, _) = candidate(
        "item:scoped",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let mut scoped_request = request(vec![candidate], 100);
    scoped_request.scope_digest = digest("other-scope");

    assert_eq!(
        compile_v2(scoped_request),
        Err(ContextCompilerV2Error::AdmissionBindingMismatch(
            "item:scoped".to_string()
        ))
    );
}

#[test]
fn attachment_revalidation_rejects_compile_then_revoke_toc_tou() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (trusted, realized) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let admission_id = trusted.admission.admission_id().clone();
    let compiled = compile_v2(request(vec![trusted], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let revoked_snapshot = verified_snapshot("snapshot:2", 20, 2, vec![admission_id.clone()]);

    assert_eq!(
        build_attachment(
            &compiled,
            &serialization,
            &profile(),
            &revoked_snapshot,
            id("attachment:1"),
        ),
        Err(ContextCompilerV2Error::AdmissionRevoked(
            admission_id.to_string()
        ))
    );
}

#[test]
fn serialization_validates_real_bytes_and_tokenizes_final_payload() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (trusted, realized) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![trusted], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));

    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 7 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid exact serialization: {error}"));

    assert_eq!(compiled.receipt().used_tokens(), 20);
    assert_eq!(serialization.receipt().serialized_token_count(), 27);
    assert_eq!(
        serialization.receipt().payload_digest(),
        Digest32::of_bytes(serialization.payload())
    );
}

#[test]
fn serialization_rejects_payload_realization_that_does_not_match_selected_digest() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (trusted, mut realized) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![trusted], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    realized.content[0] ^= 1;

    assert_eq!(
        record_serialization(
            &compiled,
            &profile(),
            id("serialization:1"),
            vec![realized],
            &FramingSerializer { overhead: 0 },
            &ByteTokenizer,
        ),
        Err(ContextCompilerV2Error::RealizedContentMismatch(
            "item:trusted".to_string()
        ))
    );
}

#[test]
fn final_serialized_token_count_must_fit_budget_including_framing() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (trusted, realized) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![trusted], 20))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));

    assert_eq!(
        record_serialization(
            &compiled,
            &profile(),
            id("serialization:1"),
            vec![realized],
            &FramingSerializer { overhead: 1 },
            &ByteTokenizer,
        ),
        Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
            serialized_tokens: 21,
            token_budget: 20,
        })
    );
}

#[test]
fn provider_receipt_bound_to_exact_payload_and_pre_dispatch_witness_creates_delivery_receipt() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (trusted, realized) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![trusted], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        &serialization,
        &profile(),
        &snapshot,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let preparation = prepare_delivery_v2(
        &compiled,
        &serialization,
        &attachment,
        &profile(),
        &snapshot,
        id("preparation:1"),
    )
    .unwrap_or_else(|error| panic!("valid delivery preparation: {error}"));
    let provider = provider_receipt(
        &serialization,
        &preparation,
        "provider",
        "model",
        None,
        None,
        completed_terminal(),
    );

    let delivery = observe_delivery(
        &preparation,
        &attachment,
        &serialization,
        &profile(),
        id("delivery:1"),
        &provider,
        &delivery_verifier(),
        25,
    )
    .unwrap_or_else(|error| panic!("valid delivery evidence: {error}"));

    assert_eq!(
        delivery.disposition(),
        ContextDeliveryDispositionV2::Delivered
    );
    assert_eq!(
        delivery.payload_digest(),
        Digest32::of_bytes(serialization.payload())
    );
    assert_eq!(delivery.preparation_digest(), preparation.preparation_digest());
    assert_eq!(
        delivery.admission_snapshot_observed_unix_ms(),
        snapshot.observed_unix_ms()
    );
    assert_eq!(delivery.revocation_epoch(), snapshot.revocation_epoch());
    assert_eq!(
        delivery.admission_snapshot_digest(),
        snapshot.snapshot_digest()
    );
    assert_eq!(delivery.authority(), AuthorityPosture::DENY_ALL);
    delivery
        .validate_for(&preparation, &attachment, &serialization, &profile())
        .unwrap_or_else(|error| panic!("valid delivery receipt: {error}"));
}

#[test]
fn provider_payload_binding_must_match_exact_serialized_payload() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (candidate, realized) = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![candidate], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        &serialization,
        &profile(),
        &snapshot,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let preparation = prepare_delivery_v2(
        &compiled,
        &serialization,
        &attachment,
        &profile(),
        &snapshot,
        id("preparation:1"),
    )
    .unwrap_or_else(|error| panic!("valid preparation: {error}"));
    let provider = provider_receipt(
        &serialization,
        &preparation,
        "provider",
        "model",
        Some(Sha256Digest::for_bytes(b"different-payload")),
        None,
        completed_terminal(),
    );

    assert_eq!(
        observe_delivery(
            &preparation,
            &attachment,
            &serialization,
            &profile(),
            id("delivery:1"),
            &provider,
            &delivery_verifier(),
            25,
        ),
        Err(ContextCompilerV2Error::DeliveryMismatch)
    );
}

#[test]
fn provider_input_witness_must_bind_current_pre_dispatch_revalidation() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (candidate, realized) = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![candidate], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        &serialization,
        &profile(),
        &snapshot,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let preparation = prepare_delivery_v2(
        &compiled,
        &serialization,
        &attachment,
        &profile(),
        &snapshot,
        id("preparation:1"),
    )
    .unwrap_or_else(|error| panic!("valid preparation: {error}"));
    let provider = provider_receipt(
        &serialization,
        &preparation,
        "provider",
        "model",
        None,
        Some(Sha256Digest::for_bytes(b"stale-preparation")),
        completed_terminal(),
    );

    assert_eq!(
        observe_delivery(
            &preparation,
            &attachment,
            &serialization,
            &profile(),
            id("delivery:1"),
            &provider,
            &delivery_verifier(),
            25,
        ),
        Err(ContextCompilerV2Error::DeliveryMismatch)
    );
}

#[test]
fn provider_and_model_identity_must_match_exact_model_profile() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (candidate, realized) = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![candidate], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        &serialization,
        &profile(),
        &snapshot,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let preparation = prepare_delivery_v2(
        &compiled,
        &serialization,
        &attachment,
        &profile(),
        &snapshot,
        id("preparation:1"),
    )
    .unwrap_or_else(|error| panic!("valid preparation: {error}"));
    let provider = provider_receipt(
        &serialization,
        &preparation,
        "different-provider",
        "model",
        None,
        None,
        completed_terminal(),
    );

    assert_eq!(
        observe_delivery(
            &preparation,
            &attachment,
            &serialization,
            &profile(),
            id("delivery:1"),
            &provider,
            &delivery_verifier(),
            25,
        ),
        Err(ContextCompilerV2Error::ProviderModelProfileMismatch)
    );
}

#[test]
fn independent_provider_evidence_verifier_is_required() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (candidate, realized) = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![candidate], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        &serialization,
        &profile(),
        &snapshot,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let preparation = prepare_delivery_v2(
        &compiled,
        &serialization,
        &attachment,
        &profile(),
        &snapshot,
        id("preparation:1"),
    )
    .unwrap_or_else(|error| panic!("valid preparation: {error}"));
    let provider = provider_receipt(
        &serialization,
        &preparation,
        "provider",
        "model",
        None,
        None,
        completed_terminal(),
    );
    let rejecting = TestDeliveryVerifier {
        accept: false,
        recorded_at_unix_ms: 20,
    };

    assert!(matches!(
        observe_delivery(
            &preparation,
            &attachment,
            &serialization,
            &profile(),
            id("delivery:1"),
            &provider,
            &rejecting,
            25,
        ),
        Err(ContextCompilerV2Error::ProviderEvidenceInvalid(_))
    ));
}

#[test]
fn delivery_preparation_rejects_snapshot_time_rollback_even_with_same_epoch() {
    let initial_snapshot = verified_snapshot("snapshot:initial", 10, 1, Vec::new());
    let (trusted, realized) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        20,
        FixedQ32::ONE,
        &initial_snapshot,
    );
    let compiled = compile_v2(request(vec![trusted], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment_snapshot = verified_snapshot("snapshot:attachment", 20, 2, Vec::new());
    let attachment = build_attachment(
        &compiled,
        &serialization,
        &profile(),
        &attachment_snapshot,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let rollback_snapshot = verified_snapshot("snapshot:rollback", 15, 2, Vec::new());

    assert_eq!(
        prepare_delivery_v2(
            &compiled,
            &serialization,
            &attachment,
            &profile(),
            &rollback_snapshot,
            id("preparation:1"),
        ),
        Err(ContextCompilerV2Error::StaleAdmissionSnapshot)
    );
}

#[test]
fn delivery_preparation_revalidates_and_rejects_revocation_after_attachment() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (trusted, realized) = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let admission_id = trusted.admission.admission_id().clone();
    let compiled = compile_v2(request(vec![trusted], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        &serialization,
        &profile(),
        &snapshot,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let revoked_snapshot = verified_snapshot("snapshot:2", 20, 2, vec![admission_id.clone()]);

    assert_eq!(
        prepare_delivery_v2(
            &compiled,
            &serialization,
            &attachment,
            &profile(),
            &revoked_snapshot,
            id("preparation:1"),
        ),
        Err(ContextCompilerV2Error::AdmissionRevoked(
            admission_id.to_string()
        ))
    );
}

#[test]
fn indeterminate_provider_terminal_remains_indeterminate() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (candidate, realized) = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![candidate], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        &profile(),
        id("serialization:1"),
        vec![realized],
        &FramingSerializer { overhead: 0 },
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        &serialization,
        &profile(),
        &snapshot,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let preparation = prepare_delivery_v2(
        &compiled,
        &serialization,
        &attachment,
        &profile(),
        &snapshot,
        id("preparation:1"),
    )
    .unwrap_or_else(|error| panic!("valid preparation: {error}"));
    let provider = provider_receipt(
        &serialization,
        &preparation,
        "provider",
        "model",
        None,
        None,
        ProviderTerminal::Indeterminate {
            reason_code: "lost_terminal_ack".to_string(),
            partial_response_sha256: None,
        },
    );

    let delivery = observe_delivery(
        &preparation,
        &attachment,
        &serialization,
        &profile(),
        id("delivery:1"),
        &provider,
        &delivery_verifier(),
        25,
    )
    .unwrap_or_else(|error| panic!("valid indeterminate evidence: {error}"));
    assert_eq!(
        delivery.disposition(),
        ContextDeliveryDispositionV2::Indeterminate
    );
}

#[test]
fn tokenizer_generation_secret_and_profile_drift_fail_closed() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());

    let (mut stale, _) = candidate(
        "item:stale",
        ContextRoleV2::UntrustedEvidence,
        10,
        FixedQ32::ONE,
        &snapshot,
    );
    stale.generation_vector_digest = digest("stale-vector");
    assert_eq!(
        compile_v2(request(vec![stale], 100)),
        Err(ContextCompilerV2Error::GenerationVectorMismatch(
            "item:stale".to_string()
        ))
    );

    let secret_content = content_bytes("item:secret", 10);
    let secret_record = ContextAdmissionRecordV2::new(
        id("admission:item:secret"),
        ContextAdmissionBindingV2 {
            item_id: id("item:secret"),
            role: ContextRoleV2::UntrustedEvidence,
            content_digest: Digest32::of_bytes(&secret_content),
            source_digest: digest("source:item:secret"),
            generation_vector_digest: digest("generation-vector"),
            scope_digest: digest("scope"),
            contains_secret: true,
        },
        1,
        1_000,
    )
    .unwrap_or_else(|_| panic!("secret fixture admission record should be valid"));
    assert!(matches!(
        verify_admission_v2(secret_record, &snapshot, &verifier()),
        Err(ContextCompilerV2Error::SecretRejected(_))
    ));

    let (candidate, realized) = candidate(
        "item:profile",
        ContextRoleV2::UntrustedEvidence,
        10,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![candidate], 100))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let mut wrong_profile = profile();
    wrong_profile.template_digest = digest("different-template");
    assert_eq!(
        record_serialization(
            &compiled,
            &wrong_profile,
            id("serialization:1"),
            vec![realized],
            &FramingSerializer { overhead: 0 },
            &ByteTokenizer,
        ),
        Err(ContextCompilerV2Error::ModelProfileMismatch)
    );
}
