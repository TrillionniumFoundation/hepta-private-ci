use std::collections::BTreeSet;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn profile(maximum_context_tokens: u64) -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        maximum_context_tokens,
    }
}

fn candidate(item: &str, role: ContextRoleV2, bytes: &[u8], token_count: u64) -> ContextCandidateV2 {
    let content_digest = Digest32::of_bytes(bytes);
    ContextCandidateV2 {
        item_id: id(item),
        role,
        content_digest,
        source_digest: digest(&format!("source:{item}")),
        generation_vector_digest: digest("generation"),
        tokenization: crate::TokenizationReceiptV2::new(
            id(item),
            content_digest,
            digest("tokenizer"),
            token_count,
        )
        .unwrap_or_else(|error| panic!("tokenization: {error}")),
        expected_value: codex_hepta_types::FixedQ32::ONE,
        trusted_admission_digest: match role {
            ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema => {
                Some(digest(&format!("admission:{item}")))
            }
            ContextRoleV2::UntrustedEvidence => None,
        },
        contains_secret: false,
    }
}

fn request(candidates: Vec<ContextCandidateV2>, budget: u64) -> ContextCompilationRequestV2 {
    ContextCompilationRequestV2 {
        compilation_id: id("compilation:verified"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation"),
        model_profile: profile(1_000),
        token_budget: budget,
        truncation_policy_digest: digest("truncation"),
        candidates,
        mandatory_groups: Vec::new(),
    }
}

struct AdmissionVerifier {
    revoked: BTreeSet<StableId>,
    wrong_receipt: bool,
}

impl ContextAdmissionVerifierV2 for AdmissionVerifier {
    fn verify_current(
        &self,
        candidate: &ContextCandidateV2,
        _now_unix_ms: u64,
    ) -> Result<VerifiedAdmissionEvidenceV2, ContextClosureErrorV2> {
        let receipt = if self.wrong_receipt {
            digest("wrong-admission")
        } else {
            digest(&format!("admission:{}", candidate.item_id.as_str()))
        };
        Ok(VerifiedAdmissionEvidenceV2 {
            item_id: candidate.item_id.clone(),
            role: candidate.role,
            content_digest: candidate.content_digest,
            source_digest: candidate.source_digest,
            generation_vector_digest: candidate.generation_vector_digest,
            admission_receipt_digest: receipt,
            owner_snapshot_digest: digest("owner-snapshot"),
            revocation_frontier_digest: digest("revocation-frontier"),
            expires_unix_ms: 10_000,
            active: !self.revoked.contains(&candidate.item_id),
        })
    }
}

struct ByteTokenizer;

impl ExactContextTokenizerV2 for ByteTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("tokenizer")
    }

    fn count_tokens(&self, payload: &[u8]) -> Result<u64, ContextClosureErrorV2> {
        u64::try_from(payload.len()).map_err(|_| ContextClosureErrorV2::TokenizerFailure("length".into()))
    }
}

struct DeliveryVerifier {
    payload_digest: Digest32,
    terminal: bool,
    disposition: ContextDeliveryDispositionV2,
}

impl ProviderDeliveryEvidenceVerifierV2 for DeliveryVerifier {
    fn verify_delivery(
        &self,
        attachment: &VerifiedContextAttachmentV2,
    ) -> Result<ProviderDeliveryEvidenceV2, ContextClosureErrorV2> {
        Ok(ProviderDeliveryEvidenceV2 {
            provider_request_id: id("provider-request:1"),
            transport_receipt_digest: digest("transport-receipt"),
            payload_digest: self.payload_digest,
            model_profile_digest: attachment.model_profile_digest,
            terminal_observed: self.terminal,
            disposition: self.disposition,
            observed_unix_ms: 2_000,
        })
    }
}

#[test]
fn caller_supplied_admission_digest_cannot_self_admit() {
    let trusted = candidate("trusted:1", ContextRoleV2::TrustedInstruction, b"A", 1);
    let verifier = AdmissionVerifier {
        revoked: BTreeSet::new(),
        wrong_receipt: true,
    };
    assert_eq!(
        compile_verified_v2(request(vec![trusted], 10), &verifier, 1_000),
        Err(ContextClosureErrorV2::AdmissionReceiptMismatch("trusted:1".into()))
    );
}

#[test]
fn attachment_revalidates_current_revocation() {
    let trusted = candidate("trusted:1", ContextRoleV2::TrustedInstruction, b"A", 1);
    let verifier = AdmissionVerifier {
        revoked: BTreeSet::new(),
        wrong_receipt: false,
    };
    let compiled = compile_verified_v2(request(vec![trusted.clone()], 10), &verifier, 1_000)
        .unwrap_or_else(|error| panic!("compile: {error}"));
    let serialization = record_verified_serialization_v2(
        &compiled,
        &profile(1_000),
        id("serialization:1"),
        b"A",
        &[SerializedContextSegmentV2 {
            item_id: trusted.item_id.clone(),
            start: 0,
            end: 1,
        }],
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("serialization: {error}"));

    let mut revoked = BTreeSet::new();
    revoked.insert(trusted.item_id);
    let revoked_verifier = AdmissionVerifier {
        revoked,
        wrong_receipt: false,
    };
    assert_eq!(
        build_revalidated_attachment_v2(
            &compiled,
            &serialization,
            id("attachment:1"),
            id("revalidation:1"),
            &revoked_verifier,
            2_000,
        ),
        Err(ContextClosureErrorV2::AdmissionStaleOrRevoked("trusted:1".into()))
    );
}

#[test]
fn final_payload_is_tokenized_from_actual_bytes_not_candidate_sum() {
    let evidence = candidate("evidence:1", ContextRoleV2::UntrustedEvidence, b"ABC", 1);
    let verifier = AdmissionVerifier {
        revoked: BTreeSet::new(),
        wrong_receipt: false,
    };
    let compiled = compile_verified_v2(request(vec![evidence.clone()], 10), &verifier, 1_000)
        .unwrap_or_else(|error| panic!("compile: {error}"));
    let serialization = record_verified_serialization_v2(
        &compiled,
        &profile(1_000),
        id("serialization:1"),
        b"<ABC>",
        &[SerializedContextSegmentV2 {
            item_id: evidence.item_id.clone(),
            start: 1,
            end: 4,
        }],
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("serialization: {error}"));
    assert_eq!(compiled.compiled.receipt.used_tokens, 1);
    assert_eq!(serialization.serialized_token_count, 5);
}

#[test]
fn final_serialized_payload_must_fit_budget() {
    let evidence = candidate("evidence:1", ContextRoleV2::UntrustedEvidence, b"ABC", 1);
    let verifier = AdmissionVerifier {
        revoked: BTreeSet::new(),
        wrong_receipt: false,
    };
    let compiled = compile_verified_v2(request(vec![evidence.clone()], 4), &verifier, 1_000)
        .unwrap_or_else(|error| panic!("compile: {error}"));
    assert_eq!(
        record_verified_serialization_v2(
            &compiled,
            &profile(1_000),
            id("serialization:1"),
            b"<ABC>",
            &[SerializedContextSegmentV2 {
                item_id: evidence.item_id,
                start: 1,
                end: 4,
            }],
            &ByteTokenizer,
        ),
        Err(ContextClosureErrorV2::FinalPayloadTokenBudgetExceeded {
            actual_tokens: 5,
            token_budget: 4,
        })
    );
}

#[test]
fn serialization_proves_selected_content_is_in_exact_payload() {
    let evidence = candidate("evidence:1", ContextRoleV2::UntrustedEvidence, b"ABC", 1);
    let verifier = AdmissionVerifier {
        revoked: BTreeSet::new(),
        wrong_receipt: false,
    };
    let compiled = compile_verified_v2(request(vec![evidence.clone()], 10), &verifier, 1_000)
        .unwrap_or_else(|error| panic!("compile: {error}"));
    assert_eq!(
        record_verified_serialization_v2(
            &compiled,
            &profile(1_000),
            id("serialization:1"),
            b"<XYZ>",
            &[SerializedContextSegmentV2 {
                item_id: evidence.item_id,
                start: 1,
                end: 4,
            }],
            &ByteTokenizer,
        ),
        Err(ContextClosureErrorV2::SerializedContentMismatch("evidence:1".into()))
    );
}

#[test]
fn delivery_requires_verified_transport_provider_evidence() {
    let evidence = candidate("evidence:1", ContextRoleV2::UntrustedEvidence, b"ABC", 1);
    let verifier = AdmissionVerifier {
        revoked: BTreeSet::new(),
        wrong_receipt: false,
    };
    let compiled = compile_verified_v2(request(vec![evidence.clone()], 10), &verifier, 1_000)
        .unwrap_or_else(|error| panic!("compile: {error}"));
    let serialization = record_verified_serialization_v2(
        &compiled,
        &profile(1_000),
        id("serialization:1"),
        b"ABC",
        &[SerializedContextSegmentV2 {
            item_id: evidence.item_id,
            start: 0,
            end: 3,
        }],
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("serialization: {error}"));
    let (attachment, _) = build_revalidated_attachment_v2(
        &compiled,
        &serialization,
        id("attachment:1"),
        id("revalidation:1"),
        &verifier,
        1_500,
    )
    .unwrap_or_else(|error| panic!("attachment: {error}"));

    let delivered = DeliveryVerifier {
        payload_digest: attachment.payload_digest,
        terminal: true,
        disposition: ContextDeliveryDispositionV2::Delivered,
    };
    let receipt = observe_verified_delivery_v2(&attachment, id("observation:1"), &delivered)
        .unwrap_or_else(|error| panic!("delivery: {error}"));
    assert_eq!(receipt.disposition, ContextDeliveryDispositionV2::Delivered);

    let mismatch = DeliveryVerifier {
        payload_digest: digest("wrong-payload"),
        terminal: true,
        disposition: ContextDeliveryDispositionV2::Delivered,
    };
    assert_eq!(
        observe_verified_delivery_v2(&attachment, id("observation:2"), &mismatch),
        Err(ContextClosureErrorV2::ProviderEvidenceMismatch)
    );
}

#[test]
fn mandatory_group_provenance_changes_verified_compilation_identity() {
    let evidence = candidate("evidence:1", ContextRoleV2::UntrustedEvidence, b"ABC", 1);
    let verifier = AdmissionVerifier {
        revoked: BTreeSet::new(),
        wrong_receipt: false,
    };
    let plain = compile_verified_v2(request(vec![evidence.clone()], 10), &verifier, 1_000)
        .unwrap_or_else(|error| panic!("plain: {error}"));
    let mut grouped_request = request(vec![evidence.clone()], 10);
    grouped_request.mandatory_groups = vec![MandatoryContextGroupV2 {
        group_id: id("group:1"),
        item_ids: vec![evidence.item_id],
        reason_digest: digest("reason"),
    }];
    let grouped = compile_verified_v2(grouped_request, &verifier, 1_000)
        .unwrap_or_else(|error| panic!("grouped: {error}"));
    assert_ne!(plain.mandatory_groups_digest, grouped.mandatory_groups_digest);
    assert_ne!(plain.verified_compilation_digest, grouped.verified_compilation_digest);
}
