use super::*;

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

struct TestTransport {
    transmitted_override: Option<Digest32>,
    terminal_observed: bool,
    disposition: ContextDeliveryDispositionV2,
    acknowledgement: bool,
}

impl ContextTransportV2 for TestTransport {
    fn transport_digest(&self) -> Digest32 {
        digest("transport-adapter")
    }

    fn send(
        &self,
        payload: &[u8],
        _model_profile_digest: Digest32,
    ) -> Result<ContextTransportEvidenceV2, ContextCompilerV2Error> {
        Ok(ContextTransportEvidenceV2 {
            provider_request_id: id("provider:request:1"),
            transmitted_payload_digest: self
                .transmitted_override
                .unwrap_or_else(|| Digest32::of_bytes(payload)),
            acknowledgement_digest: if self.acknowledgement {
                digest("provider-ack")
            } else {
                Digest32::ZERO
            },
            terminal_observed: self.terminal_observed,
            disposition: self.disposition,
            observed_unix_ms: 10,
        })
    }
}

fn profile() -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
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
    let tokenization = TokenizationReceiptV2::from_exact_bytes(
        id(item_id),
        &content,
        &tokenizer,
    )
    .unwrap_or_else(|error| panic!("valid tokenization: {error}"));
    let source_digest = digest(&format!("source:{item_id}"));
    let record = ContextAdmissionRecordV2::new(
        id(&format!("admission:{item_id}")),
        id(item_id),
        role,
        tokenization.content_digest(),
        source_digest,
        digest("generation-vector"),
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
            contains_secret: false,
        },
        ContextRealizedItemV2 {
            item_id: id(item_id),
            role,
            content,
        },
    )
}

fn request(
    candidates: Vec<ContextCandidateV2>,
    token_budget: u64,
) -> ContextCompilationRequestV2 {
    ContextCompilationRequestV2 {
        compilation_id: id("compilation:1"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation-vector"),
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
    assert_eq!(left.receipt.used_tokens, 80);
    assert_eq!(
        left.receipt.selected_item_ids,
        vec![trusted.item_id, schema.item_id, high_ratio.item_id]
    );
    assert_eq!(left.receipt.omitted_item_ids, vec![low_ratio.item_id]);
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
        ungrouped.receipt.selected_item_ids,
        grouped.receipt.selected_item_ids
    );
    assert_ne!(
        ungrouped.receipt.mandatory_groups_digest,
        grouped.receipt.mandatory_groups_digest
    );
    assert_ne!(ungrouped.receipt.receipt_digest, grouped.receipt.receipt_digest);
}

#[test]
fn well_formed_admission_digest_is_not_enough_without_verifier_acceptance() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let content = content_bytes("item:trusted", 20);
    let record = ContextAdmissionRecordV2::new(
        id("admission:item:trusted"),
        id("item:trusted"),
        ContextRoleV2::TrustedInstruction,
        Digest32::of_bytes(&content),
        digest("source:item:trusted"),
        digest("generation-vector"),
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
    let revoked_snapshot =
        verified_snapshot("snapshot:2", 20, 2, vec![admission_id.clone()]);

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

    assert_eq!(compiled.receipt.used_tokens, 20);
    assert_eq!(serialization.receipt.serialized_token_count, 27);
    assert_eq!(
        serialization.receipt.payload_digest,
        Digest32::of_bytes(&serialization.payload)
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
fn delivery_receipt_is_created_only_from_transport_invoked_with_exact_payload() {
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
    let transport = TestTransport {
        transmitted_override: None,
        terminal_observed: true,
        disposition: ContextDeliveryDispositionV2::Delivered,
        acknowledgement: true,
    };

    let delivery = deliver_context_v2(
        &compiled,
        &serialization,
        &attachment,
        &profile(),
        &snapshot,
        id("delivery:1"),
        &transport,
    )
    .unwrap_or_else(|error| panic!("valid delivery: {error}"));

    assert_eq!(delivery.disposition, ContextDeliveryDispositionV2::Delivered);
    assert_eq!(
        delivery.payload_digest,
        Digest32::of_bytes(&serialization.payload)
    );
    assert!(!delivery.acknowledgement_digest.is_zero());
    assert_eq!(delivery.authority, AuthorityPosture::DENY_ALL);
    delivery
        .validate_for(&attachment, &serialization)
        .unwrap_or_else(|error| panic!("valid delivery receipt: {error}"));
}

#[test]
fn transport_cannot_claim_delivery_of_different_payload() {
    let snapshot = verified_snapshot("snapshot:1", 10, 1, Vec::new());
    let (evidence, realized) = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::ONE,
        &snapshot,
    );
    let compiled = compile_v2(request(vec![evidence], 100))
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
    let transport = TestTransport {
        transmitted_override: Some(digest("different-payload")),
        terminal_observed: true,
        disposition: ContextDeliveryDispositionV2::Delivered,
        acknowledgement: true,
    };

    assert_eq!(
        deliver_context_v2(
            &compiled,
            &serialization,
            &attachment,
            &profile(),
            &snapshot,
            id("delivery:1"),
            &transport,
        ),
        Err(ContextCompilerV2Error::DeliveryMismatch)
    );
}

#[test]
fn delivery_revalidates_again_and_rejects_revocation_after_attachment() {
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
    let revoked_snapshot =
        verified_snapshot("snapshot:2", 20, 2, vec![admission_id.clone()]);
    let transport = TestTransport {
        transmitted_override: None,
        terminal_observed: true,
        disposition: ContextDeliveryDispositionV2::Delivered,
        acknowledgement: true,
    };

    assert_eq!(
        deliver_context_v2(
            &compiled,
            &serialization,
            &attachment,
            &profile(),
            &revoked_snapshot,
            id("delivery:1"),
            &transport,
        ),
        Err(ContextCompilerV2Error::AdmissionRevoked(
            admission_id.to_string()
        ))
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

    let (mut secret, _) = candidate(
        "item:secret",
        ContextRoleV2::UntrustedEvidence,
        10,
        FixedQ32::ONE,
        &snapshot,
    );
    secret.contains_secret = true;
    assert_eq!(
        compile_v2(request(vec![secret], 100)),
        Err(ContextCompilerV2Error::SecretRejected(
            "item:secret".to_string()
        ))
    );

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
