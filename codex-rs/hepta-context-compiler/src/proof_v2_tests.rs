use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone)]
struct TestAdmissionVerifier {
    accept: bool,
}

impl ContextAdmissionVerifierV2 for TestAdmissionVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("admission-verifier")
    }

    fn verify_snapshot(
        &self,
        evidence: &ContextAdmissionSnapshotEvidenceV2,
    ) -> Result<Digest32, String> {
        if !self.accept {
            return Err("untrusted snapshot".to_string());
        }
        let mut bytes = Vec::new();
        bytes.extend_from_slice(evidence.issuer_digest.as_array());
        bytes.extend_from_slice(evidence.witness_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

struct ByteTokenizer {
    identity: Digest32,
}

impl ExactContextTokenizerV2 for ByteTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        self.identity
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, String> {
        u64::try_from(bytes.len()).map_err(|error| error.to_string())
    }
}

struct FramingSerializer {
    identity: Digest32,
}

impl ContextSerializerV2 for FramingSerializer {
    fn serializer_digest(&self) -> Digest32 {
        self.identity
    }

    fn serialize(
        &self,
        _profile: &ContextModelProfileV2,
        ordered_items: &[ContextPayloadItemV2],
    ) -> Result<ContextSerializedPayloadV2, String> {
        let mut payload = b"<ctx>".to_vec();
        let mut placements = Vec::new();
        for item in ordered_items {
            let start = payload.len();
            payload.extend_from_slice(item.content());
            let end = payload.len();
            placements.push(ContextPayloadPlacementV2::new(
                item.item_id().clone(),
                start,
                end,
            ));
        }
        payload.extend_from_slice(b"</ctx>");
        Ok(ContextSerializedPayloadV2::new(payload, placements))
    }
}

struct DroppingSerializer {
    identity: Digest32,
}

impl ContextSerializerV2 for DroppingSerializer {
    fn serializer_digest(&self) -> Digest32 {
        self.identity
    }

    fn serialize(
        &self,
        _profile: &ContextModelProfileV2,
        _ordered_items: &[ContextPayloadItemV2],
    ) -> Result<ContextSerializedPayloadV2, String> {
        Ok(ContextSerializedPayloadV2::new(
            b"<ctx></ctx>".to_vec(),
            Vec::new(),
        ))
    }
}

#[derive(Clone)]
struct TestDeliveryAdapter {
    identity: Digest32,
    payload_override: Option<Digest32>,
    ack: bool,
    disposition: ContextDeliveryDispositionV2,
    terminal: bool,
}

impl ContextDeliveryAdapterV2 for TestDeliveryAdapter {
    fn adapter_digest(&self) -> Digest32 {
        self.identity
    }

    fn deliver(
        &self,
        _attachment: &ContextAttachmentV2,
        payload: &[u8],
    ) -> Result<ContextTransportEvidenceV2, String> {
        Ok(ContextTransportEvidenceV2 {
            attempt_id: id("attempt:1"),
            payload_digest: self
                .payload_override
                .unwrap_or_else(|| Digest32::of_bytes(payload)),
            provider_request_id: self.ack.then(|| id("provider-request:1")),
            provider_ack_digest: self.ack.then(|| digest("provider-ack")),
            terminal_observed: self.terminal,
            disposition: self.disposition,
            observed_unix_ms: 20,
        })
    }
}

fn tokenizer() -> ByteTokenizer {
    ByteTokenizer {
        identity: digest("tokenizer"),
    }
}

fn profile(maximum_context_tokens: u64) -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        serializer_digest: digest("serializer"),
        maximum_context_tokens,
    }
}

fn admission_record(
    item_id: &str,
    role: ContextRoleV2,
    content: &[u8],
    source_digest: Digest32,
) -> ContextAdmissionRecordV2 {
    ContextAdmissionRecordV2 {
        item_id: id(item_id),
        role,
        content_digest: Digest32::of_bytes(content),
        source_digest,
        admission_digest: digest(&format!("admission:{item_id}")),
        admitted_at_unix_ms: 1,
        expires_at_unix_ms: None,
        revoked_at_unix_ms: None,
        revocation_digest: None,
    }
}

fn snapshot(
    records: Vec<ContextAdmissionRecordV2>,
    observed_unix_ms: u64,
    frontier: &str,
) -> ContextAdmissionSnapshotV2 {
    verify_admission_snapshot_v2(
        ContextAdmissionSnapshotEvidenceV2 {
            issuer_digest: digest("admission-issuer"),
            source_snapshot_digest: digest(&format!("source-snapshot:{observed_unix_ms}")),
            revocation_frontier_digest: digest(frontier),
            witness_digest: digest(&format!("witness:{observed_unix_ms}:{frontier}")),
            observed_unix_ms,
            records,
        },
        &TestAdmissionVerifier { accept: true },
    )
    .unwrap_or_else(|error| panic!("valid snapshot: {error}"))
}

fn candidate(
    item_id: &str,
    role: ContextRoleV2,
    content: &[u8],
    expected_value: FixedQ32,
    admission_snapshot: &ContextAdmissionSnapshotV2,
) -> ContextCandidateV2 {
    let source_digest = digest(&format!("source:{item_id}"));
    let tokenization = TokenizationReceiptV2::measure(id(item_id), content, &tokenizer())
        .unwrap_or_else(|error| panic!("valid tokenization: {error}"));
    let admission = admission_snapshot
        .verify_binding(
            &id(item_id),
            role,
            tokenization.content_digest(),
            source_digest,
        )
        .unwrap_or_else(|error| panic!("valid admission: {error}"));
    ContextCandidateV2::new(
        id(item_id),
        role,
        source_digest,
        digest("generation-vector"),
        tokenization,
        expected_value,
        admission,
        false,
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"))
}

fn request(
    candidates: Vec<ContextCandidateV2>,
    admission_snapshot: ContextAdmissionSnapshotV2,
    token_budget: u64,
) -> ContextCompilationRequestV2 {
    ContextCompilationRequestV2 {
        compilation_id: id("compilation:1"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation-vector"),
        model_profile: profile(1_000),
        admission_snapshot,
        token_budget,
        truncation_policy_digest: digest("truncation-policy"),
        candidates,
        mandatory_groups: Vec::new(),
    }
}

fn trusted_snapshot(content: &[u8], observed_unix_ms: u64) -> ContextAdmissionSnapshotV2 {
    snapshot(
        vec![admission_record(
            "item:trusted",
            ContextRoleV2::TrustedInstruction,
            content,
            digest("source:item:trusted"),
        )],
        observed_unix_ms,
        &format!("frontier:{observed_unix_ms}"),
    )
}

fn compile_one_trusted(content: &[u8], budget: u64) -> CompiledContextV2 {
    let admission_snapshot = trusted_snapshot(content, 10);
    let trusted = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        content,
        FixedQ32::ONE,
        &admission_snapshot,
    );
    compile_v2(request(vec![trusted], admission_snapshot, budget))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"))
}

fn serialize_one_trusted(
    compiled: &CompiledContextV2,
    content: &[u8],
) -> SerializedContextV2 {
    serialize_context_v2(
        compiled,
        id("serialization:1"),
        vec![ContextPayloadItemV2::new(
            id("item:trusted"),
            content.to_vec(),
        )],
        &FramingSerializer {
            identity: digest("serializer"),
        },
        &tokenizer(),
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"))
}

#[test]
fn deterministic_selection_preserves_verified_trusted_floor() {
    let trusted_content = b"trust";
    let evidence_a_content = b"aa";
    let evidence_b_content = b"bbbb";
    let admission_snapshot = snapshot(
        vec![
            admission_record(
                "item:trusted",
                ContextRoleV2::TrustedInstruction,
                trusted_content,
                digest("source:item:trusted"),
            ),
            admission_record(
                "item:evidence-a",
                ContextRoleV2::UntrustedEvidence,
                evidence_a_content,
                digest("source:item:evidence-a"),
            ),
            admission_record(
                "item:evidence-b",
                ContextRoleV2::UntrustedEvidence,
                evidence_b_content,
                digest("source:item:evidence-b"),
            ),
        ],
        10,
        "frontier:10",
    );
    let trusted = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        trusted_content,
        FixedQ32::ONE,
        &admission_snapshot,
    );
    let evidence_a = candidate(
        "item:evidence-a",
        ContextRoleV2::UntrustedEvidence,
        evidence_a_content,
        FixedQ32::ONE,
        &admission_snapshot,
    );
    let evidence_b = candidate(
        "item:evidence-b",
        ContextRoleV2::UntrustedEvidence,
        evidence_b_content,
        FixedQ32::ONE,
        &admission_snapshot,
    );
    let candidates = vec![trusted.clone(), evidence_a.clone(), evidence_b.clone()];
    let mut reversed = candidates.clone();
    reversed.reverse();
    let left = compile_v2(request(
        candidates,
        admission_snapshot.clone(),
        7,
    ))
    .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let right = compile_v2(request(reversed, admission_snapshot, 7))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    assert_eq!(left.receipt, right.receipt);
    assert_eq!(
        left.receipt.selected_item_ids,
        vec![trusted.item_id().clone(), evidence_a.item_id().clone()]
    );
    assert_eq!(
        left.receipt.omitted_item_ids,
        vec![evidence_b.item_id().clone()]
    );
}

#[test]
fn unauthenticated_admission_snapshot_cannot_create_typed_proof() {
    let evidence = ContextAdmissionSnapshotEvidenceV2 {
        issuer_digest: digest("admission-issuer"),
        source_snapshot_digest: digest("source-snapshot"),
        revocation_frontier_digest: digest("frontier"),
        witness_digest: digest("witness"),
        observed_unix_ms: 10,
        records: Vec::new(),
    };
    assert_eq!(
        verify_admission_snapshot_v2(
            evidence,
            &TestAdmissionVerifier { accept: false },
        ),
        Err(ContextCompilerV2Error::AdmissionVerificationFailure(
            "untrusted snapshot".to_string()
        ))
    );
}

#[test]
fn admission_proof_cannot_be_reused_for_different_source_binding() {
    let content = b"trusted";
    let admission_snapshot = trusted_snapshot(content, 10);
    let tokenization = TokenizationReceiptV2::measure(id("item:trusted"), content, &tokenizer())
        .unwrap_or_else(|error| panic!("tokenization: {error}"));
    let admission = admission_snapshot
        .verify_binding(
            &id("item:trusted"),
            ContextRoleV2::TrustedInstruction,
            tokenization.content_digest(),
            digest("source:item:trusted"),
        )
        .unwrap_or_else(|error| panic!("admission: {error}"));
    let forged = ContextCandidateV2::new(
        id("item:trusted"),
        ContextRoleV2::TrustedInstruction,
        digest("different-source"),
        digest("generation-vector"),
        tokenization,
        FixedQ32::ONE,
        admission,
        false,
    )
    .unwrap_or_else(|error| panic!("shape remains constructible: {error}"));
    assert_eq!(
        compile_v2(request(vec![forged], admission_snapshot, 100)),
        Err(ContextCompilerV2Error::AdmissionBindingMismatch(
            "item:trusted".to_string()
        ))
    );
}

#[test]
fn revoked_admission_fails_at_compile() {
    let content = b"trusted";
    let mut record = admission_record(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        content,
        digest("source:item:trusted"),
    );
    record.revoked_at_unix_ms = Some(8);
    record.revocation_digest = Some(digest("revocation"));
    let revoked_snapshot = snapshot(vec![record], 10, "frontier:revoked");
    assert_eq!(
        revoked_snapshot.verify_binding(
            &id("item:trusted"),
            ContextRoleV2::TrustedInstruction,
            Digest32::of_bytes(content),
            digest("source:item:trusted"),
        ),
        Err(ContextCompilerV2Error::AdmissionRevoked(
            "item:trusted".to_string()
        ))
    );
}

#[test]
fn attachment_revalidates_current_revocation_frontier() {
    let content = b"abc";
    let compiled = compile_one_trusted(content, 100);
    let serialized = serialize_one_trusted(&compiled, content);

    let mut current_record = admission_record(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        content,
        digest("source:item:trusted"),
    );
    current_record.revoked_at_unix_ms = Some(15);
    current_record.revocation_digest = Some(digest("revoked-now"));
    let current = snapshot(vec![current_record], 20, "frontier:20");

    assert_eq!(
        build_attachment(&compiled, serialized, &current, id("attachment:1")),
        Err(ContextCompilerV2Error::AdmissionRevoked(
            "item:trusted".to_string()
        ))
    );
}

#[test]
fn attachment_revalidates_selected_untrusted_evidence_revocation() {
    let content = b"evidence";
    let initial = snapshot(
        vec![admission_record(
            "item:evidence",
            ContextRoleV2::UntrustedEvidence,
            content,
            digest("source:item:evidence"),
        )],
        10,
        "frontier:10",
    );
    let evidence = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        content,
        FixedQ32::ONE,
        &initial,
    );
    let compiled = compile_v2(request(vec![evidence], initial, 100))
        .unwrap_or_else(|error| panic!("valid evidence compilation: {error}"));
    let serialized = serialize_context_v2(
        &compiled,
        id("serialization:evidence"),
        vec![ContextPayloadItemV2::new(
            id("item:evidence"),
            content.to_vec(),
        )],
        &FramingSerializer {
            identity: digest("serializer"),
        },
        &tokenizer(),
    )
    .unwrap_or_else(|error| panic!("valid evidence serialization: {error}"));

    let mut revoked = admission_record(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        content,
        digest("source:item:evidence"),
    );
    revoked.revoked_at_unix_ms = Some(15);
    revoked.revocation_digest = Some(digest("evidence-revoked"));
    let current = snapshot(vec![revoked], 20, "frontier:20");

    assert_eq!(
        build_attachment(&compiled, serialized, &current, id("attachment:evidence")),
        Err(ContextCompilerV2Error::AdmissionRevoked(
            "item:evidence".to_string()
        ))
    );
}

#[test]
fn final_payload_is_retokenized_and_serializer_overhead_can_refuse_attachment_path() {
    let content = b"abc";
    let compiled = compile_one_trusted(content, 3);
    assert_eq!(
        serialize_context_v2(
            &compiled,
            id("serialization:1"),
            vec![ContextPayloadItemV2::new(
                id("item:trusted"),
                content.to_vec(),
            )],
            &FramingSerializer {
                identity: digest("serializer"),
            },
            &tokenizer(),
        ),
        Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
            actual_tokens: 14,
            token_budget: 3,
        })
    );
}

#[test]
fn serialization_rejects_serializer_that_drops_selected_item() {
    let content = b"abc";
    let compiled = compile_one_trusted(content, 100);
    assert_eq!(
        serialize_context_v2(
            &compiled,
            id("serialization:dropped"),
            vec![ContextPayloadItemV2::new(
                id("item:trusted"),
                content.to_vec(),
            )],
            &DroppingSerializer {
                identity: digest("serializer"),
            },
            &tokenizer(),
        ),
        Err(ContextCompilerV2Error::PayloadPlacementSetMismatch)
    );
}

#[test]
fn serialization_rejects_payload_bytes_that_do_not_match_selected_content() {
    let content = b"abc";
    let compiled = compile_one_trusted(content, 100);
    assert_eq!(
        serialize_context_v2(
            &compiled,
            id("serialization:1"),
            vec![ContextPayloadItemV2::new(
                id("item:trusted"),
                b"different".to_vec(),
            )],
            &FramingSerializer {
                identity: digest("serializer"),
            },
            &tokenizer(),
        ),
        Err(ContextCompilerV2Error::PayloadContentMismatch(
            "item:trusted".to_string()
        ))
    );
}

#[test]
fn mandatory_group_provenance_changes_receipt_even_when_selected_set_is_same() {
    let evidence_content = b"e";
    let admission_snapshot = snapshot(
        vec![admission_record(
            "item:evidence",
            ContextRoleV2::UntrustedEvidence,
            evidence_content,
            digest("source:item:evidence"),
        )],
        10,
        "frontier:10",
    );
    let evidence = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        evidence_content,
        FixedQ32::ONE,
        &admission_snapshot,
    );

    let mut left_request = request(vec![evidence.clone()], admission_snapshot.clone(), 100);
    left_request.mandatory_groups = vec![MandatoryContextGroupV2 {
        group_id: id("group:1"),
        item_ids: vec![evidence.item_id().clone()],
        reason_digest: digest("reason:a"),
    }];
    let mut right_request = request(vec![evidence], admission_snapshot, 100);
    right_request.mandatory_groups = vec![MandatoryContextGroupV2 {
        group_id: id("group:1"),
        item_ids: vec![id("item:evidence")],
        reason_digest: digest("reason:b"),
    }];

    let left = compile_v2(left_request)
        .unwrap_or_else(|error| panic!("left compilation: {error}"));
    let right = compile_v2(right_request)
        .unwrap_or_else(|error| panic!("right compilation: {error}"));
    assert_eq!(left.receipt.selected_item_ids, right.receipt.selected_item_ids);
    assert_ne!(
        left.receipt.mandatory_groups_digest,
        right.receipt.mandatory_groups_digest
    );
    assert_ne!(left.receipt.receipt_digest, right.receipt.receipt_digest);
}

#[test]
fn exact_payload_attachment_and_provider_ack_form_one_proof_chain() {
    let content = b"abc";
    let compiled = compile_one_trusted(content, 100);
    let serialized = serialize_one_trusted(&compiled, content);
    assert_eq!(serialized.receipt().serialized_token_count, 14);
    let current = trusted_snapshot(content, 20);
    let attachment = build_attachment(
        &compiled,
        serialized,
        &current,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let delivery = deliver_attachment(
        &attachment,
        &TestDeliveryAdapter {
            identity: digest("adapter"),
            payload_override: None,
            ack: true,
            disposition: ContextDeliveryDispositionV2::Delivered,
            terminal: true,
        },
    )
    .unwrap_or_else(|error| panic!("valid delivery: {error}"));
    assert_eq!(
        delivery.disposition(),
        ContextDeliveryDispositionV2::Delivered
    );
    assert_eq!(delivery.authority(), AuthorityPosture::DENY_ALL);
    delivery
        .validate_for(&attachment)
        .unwrap_or_else(|error| panic!("valid receipt: {error}"));
}

#[test]
fn delivered_requires_provider_acknowledgement() {
    let content = b"abc";
    let compiled = compile_one_trusted(content, 100);
    let serialized = serialize_one_trusted(&compiled, content);
    let current = trusted_snapshot(content, 20);
    let attachment = build_attachment(
        &compiled,
        serialized,
        &current,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    assert_eq!(
        deliver_attachment(
            &attachment,
            &TestDeliveryAdapter {
                identity: digest("adapter"),
                payload_override: None,
                ack: false,
                disposition: ContextDeliveryDispositionV2::Delivered,
                terminal: true,
            },
        ),
        Err(ContextCompilerV2Error::MissingProviderAcknowledgement)
    );
}

#[test]
fn transport_payload_mismatch_fails_closed() {
    let content = b"abc";
    let compiled = compile_one_trusted(content, 100);
    let serialized = serialize_one_trusted(&compiled, content);
    let current = trusted_snapshot(content, 20);
    let attachment = build_attachment(
        &compiled,
        serialized,
        &current,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    assert_eq!(
        deliver_attachment(
            &attachment,
            &TestDeliveryAdapter {
                identity: digest("adapter"),
                payload_override: Some(digest("wrong-payload")),
                ack: true,
                disposition: ContextDeliveryDispositionV2::Delivered,
                terminal: true,
            },
        ),
        Err(ContextCompilerV2Error::DeliveryMismatch)
    );
}

#[test]
fn nonterminal_transport_attempt_is_indeterminate_not_delivered() {
    let content = b"abc";
    let compiled = compile_one_trusted(content, 100);
    let serialized = serialize_one_trusted(&compiled, content);
    let current = trusted_snapshot(content, 20);
    let attachment = build_attachment(
        &compiled,
        serialized,
        &current,
        id("attachment:1"),
    )
    .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let receipt = deliver_attachment(
        &attachment,
        &TestDeliveryAdapter {
            identity: digest("adapter"),
            payload_override: None,
            ack: false,
            disposition: ContextDeliveryDispositionV2::Indeterminate,
            terminal: false,
        },
    )
    .unwrap_or_else(|error| panic!("valid indeterminate receipt: {error}"));
    assert_eq!(
        receipt.disposition(),
        ContextDeliveryDispositionV2::Indeterminate
    );
}
