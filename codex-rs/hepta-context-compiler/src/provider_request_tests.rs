use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use proptest::prelude::*;

use super::*;
use crate::ContextAdmissionBindingV2;
use crate::ContextAdmissionRecordV2;
use crate::ContextCandidateV2;
use crate::ContextCompilationRequestV2;
use crate::TokenizationReceiptV2;
use crate::build_attachment;
use crate::compile_v2;
use crate::verify_admission_snapshot_v2;
use crate::verify_admission_v2;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id {value}: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone, Copy, Debug)]
struct ByteTokenizer;

impl ExactTokenizerV2 for ByteTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("context-tokenizer")
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        Ok(u64::try_from(bytes.len()).unwrap_or(u64::MAX))
    }
}

#[derive(Clone, Debug)]
struct FinalByteTokenizer {
    provider: String,
    model: String,
}

impl ExactProviderRequestTokenizerV2 for FinalByteTokenizer {
    fn identity(&self) -> Result<ExactTokenizerIdentityV2, ProviderRequestProofErrorV2> {
        ExactTokenizerIdentityV2::new(
            self.provider.clone(),
            self.model.clone(),
            "test-tokenizer-1.0.0",
            digest("tokenizer-binary"),
            digest("tokenizer-vocabulary"),
            digest("normalization-none"),
        )
    }

    fn count_final_request_tokens(
        &self,
        final_request: &[u8],
    ) -> Result<u64, ProviderRequestProofErrorV2> {
        Ok(u64::try_from(final_request.len()).unwrap_or(u64::MAX))
    }
}

#[derive(Clone, Copy, Debug)]
struct AdmissionVerifier;

impl ContextAdmissionVerifierV2 for AdmissionVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("admission-verifier")
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        record.validate_shape().is_ok()
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        snapshot.validate_shape().is_ok()
    }
}

fn profile() -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        model_digest: digest("model-profile"),
        provider_id_digest: digest("provider-a"),
        provider_model_digest: digest("model-a"),
        tokenizer_digest: digest("context-tokenizer"),
        serializer_digest: digest("canonical-serializer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        maximum_context_tokens: 16_384,
    }
}

fn snapshot(
    snapshot_id: &str,
    observed_unix_ms: u64,
    revocation_epoch: u64,
    predecessor: Option<Digest32>,
    revoked: Vec<StableId>,
) -> ContextAdmissionSnapshotV2 {
    ContextAdmissionSnapshotV2::new(
        id(snapshot_id),
        digest("scope"),
        digest("authority-domain"),
        observed_unix_ms,
        revocation_epoch,
        revoked,
        true,
        predecessor,
    )
    .unwrap_or_else(|error| panic!("valid snapshot: {error}"))
}

fn verified_snapshot() -> VerifiedAdmissionSnapshotV2 {
    verify_admission_snapshot_v2(snapshot("snapshot:1", 10, 1, None, Vec::new()), &AdmissionVerifier)
        .unwrap_or_else(|error| panic!("verified snapshot: {error}"))
}

fn candidate(
    item_id: &str,
    role: ContextRoleV2,
    content: &[u8],
    snapshot: &VerifiedAdmissionSnapshotV2,
) -> (ContextCandidateV2, ContextRealizedItemV2) {
    let item_id = id(item_id);
    let tokenization = TokenizationReceiptV2::from_exact_bytes(
        item_id.clone(),
        content,
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("tokenization: {error}"));
    let admission = ContextAdmissionRecordV2::new(
        id(&format!("admission:{}", item_id.as_str())),
        ContextAdmissionBindingV2 {
            item_id: item_id.clone(),
            role,
            content_digest: Digest32::of_bytes(content),
            source_digest: digest(&format!("source:{}", item_id.as_str())),
            generation_vector_digest: digest("generation-vector"),
            scope_digest: digest("scope"),
            authority_domain_digest: digest("authority-domain"),
            contains_secret: false,
        },
        1,
        10_000,
    )
    .unwrap_or_else(|error| panic!("admission record: {error}"));
    let admission = verify_admission_v2(admission, snapshot, &AdmissionVerifier)
        .unwrap_or_else(|error| panic!("verified admission: {error}"));
    (
        ContextCandidateV2 {
            item_id: item_id.clone(),
            role,
            content_digest: Digest32::of_bytes(content),
            source_digest: digest(&format!("source:{}", item_id.as_str())),
            generation_vector_digest: digest("generation-vector"),
            tokenization,
            expected_value: FixedQ32::ONE,
            admission,
        },
        ContextRealizedItemV2 {
            item_id,
            role,
            content: content.to_vec(),
        },
    )
}

struct Fixture {
    compiled: CompiledContextV2,
    canonical: CanonicalSerializedContextV2,
    attachment: ContextAttachmentV2,
    predecessor: VerifiedAdmissionSnapshotV2,
    successor: VerifiedAdmissionSnapshotSuccessorV2,
    selected: BTreeMap<StableId, Digest32>,
}

fn fixture() -> Fixture {
    let predecessor = verified_snapshot();
    let (candidate, realization) = candidate(
        "item:developer",
        ContextRoleV2::TrustedInstruction,
        b"alpha",
        &predecessor,
    );
    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: id("compilation:provider-bound"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation-vector"),
        scope_digest: digest("scope"),
        authority_domain_digest: digest("authority-domain"),
        admission_verifier_digest: digest("admission-verifier"),
        model_profile: profile(),
        token_budget: 16_384,
        truncation_policy_digest: digest("truncation-policy"),
        candidates: vec![candidate],
        mandatory_groups: Vec::new(),
    })
    .unwrap_or_else(|error| panic!("compile: {error}"));
    let canonical = record_canonical_serialization_v2(
        &compiled,
        &profile(),
        id("serialization:canonical"),
        vec![realization],
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("canonical serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        canonical.serialized_context(),
        &profile(),
        &predecessor,
        id("attachment:canonical"),
    )
    .unwrap_or_else(|error| panic!("attachment: {error}"));
    let successor_raw = snapshot(
        "snapshot:2",
        20,
        2,
        Some(predecessor.snapshot_digest()),
        Vec::new(),
    );
    let successor = verify_typed_admission_snapshot_successor_v2(
        successor_raw,
        &predecessor,
        &AdmissionVerifier,
    )
    .unwrap_or_else(|error| panic!("successor: {error}"));
    let selected = BTreeMap::from([(id("item:developer"), digest("alpha"))]);
    Fixture {
        compiled,
        canonical,
        attachment,
        predecessor,
        successor,
        selected,
    }
}

fn segment(
    final_request: &[u8],
    offset: usize,
    length: usize,
    kind: ProviderRequestSegmentKindV2,
) -> ProviderRequestSegmentV2 {
    ProviderRequestSegmentV2 {
        offset: u64::try_from(offset).unwrap_or(u64::MAX),
        length: u64::try_from(length).unwrap_or(u64::MAX),
        encoded_digest: Digest32::of_bytes(&final_request[offset..offset + length]),
        kind,
    }
}

fn exact_request_proof(fixture: &Fixture) -> ProviderFinalRequestProofV2 {
    let final_request = b"prefix-alpha-suffix";
    let selected_start = b"prefix-".len();
    let selected_len = b"alpha".len();
    let suffix_start = selected_start + selected_len;
    let segments = vec![
        segment(
            final_request,
            0,
            selected_start,
            ProviderRequestSegmentKindV2::TypedFraming {
                framing_type: id("responses-json-prefix"),
                framing_policy_digest: digest("responses-json-v1"),
            },
        ),
        segment(
            final_request,
            selected_start,
            selected_len,
            ProviderRequestSegmentKindV2::SelectedContextItem {
                item_id: id("item:developer"),
                source_content_digest: digest("alpha"),
            },
        ),
        segment(
            final_request,
            suffix_start,
            final_request.len() - suffix_start,
            ProviderRequestSegmentKindV2::HostCanonicalMaterial {
                material_type: id("responses-json-suffix"),
                semantic_digest: digest("host-request-semantics"),
            },
        ),
    ];
    ProviderFinalRequestProofV2::from_exact_request(
        id("proof:provider-request"),
        fixture.attachment.attachment_digest(),
        fixture.canonical.serialized_context().receipt().payload_digest(),
        fixture.canonical.coverage_digest(),
        digest("wire-semantic-request"),
        final_request,
        segments,
        &fixture.selected,
        &FinalByteTokenizer {
            provider: "provider-a".to_owned(),
            model: "model-a".to_owned(),
        },
        30,
    )
    .unwrap_or_else(|error| panic!("provider request proof: {error}"))
}

#[test]
fn compiler_owned_canonical_serializer_is_order_independent_and_fully_covered() {
    let predecessor = verified_snapshot();
    let (candidate_a, realization_a) = candidate(
        "item:a",
        ContextRoleV2::TrustedInstruction,
        b"alpha",
        &predecessor,
    );
    let (candidate_b, realization_b) = candidate(
        "item:b",
        ContextRoleV2::Schema,
        b"beta",
        &predecessor,
    );
    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: id("compilation:canonical"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation-vector"),
        scope_digest: digest("scope"),
        authority_domain_digest: digest("authority-domain"),
        admission_verifier_digest: digest("admission-verifier"),
        model_profile: profile(),
        token_budget: 16_384,
        truncation_policy_digest: digest("truncation-policy"),
        candidates: vec![candidate_b, candidate_a],
        mandatory_groups: Vec::new(),
    })
    .expect("compile");
    let left = record_canonical_serialization_v2(
        &compiled,
        &profile(),
        id("serialization:canonical"),
        vec![realization_a.clone(), realization_b.clone()],
        &ByteTokenizer,
    )
    .expect("left canonical serialization");
    let right = record_canonical_serialization_v2(
        &compiled,
        &profile(),
        id("serialization:canonical"),
        vec![realization_b, realization_a],
        &ByteTokenizer,
    )
    .expect("right canonical serialization");

    assert_eq!(left, right);
    assert_eq!(
        left.segments()
            .iter()
            .map(CanonicalContextSegmentV2::length)
            .sum::<u64>(),
        u64::try_from(left.serialized_context().payload().len()).unwrap_or(u64::MAX)
    );
    assert_eq!(
        left.segments()
            .iter()
            .filter(|segment| matches!(segment.kind(), CanonicalContextSegmentKindV2::SelectedItem { .. }))
            .count(),
        2
    );
}

#[test]
fn final_request_segment_map_rejects_gaps_duplicates_and_digest_tampering() {
    let fixture = fixture();
    let final_request = b"prefix-alpha-suffix";
    let selected_start = b"prefix-".len();
    let selected_len = b"alpha".len();
    let suffix_start = selected_start + selected_len;
    let framing = ProviderRequestSegmentKindV2::TypedFraming {
        framing_type: id("framing"),
        framing_policy_digest: digest("framing-policy"),
    };
    let selected = ProviderRequestSegmentKindV2::SelectedContextItem {
        item_id: id("item:developer"),
        source_content_digest: digest("alpha"),
    };
    let host = ProviderRequestSegmentKindV2::HostCanonicalMaterial {
        material_type: id("host-material"),
        semantic_digest: digest("host-semantics"),
    };

    let gap = vec![
        segment(final_request, 0, selected_start - 1, framing.clone()),
        segment(final_request, selected_start, selected_len, selected.clone()),
        segment(
            final_request,
            suffix_start,
            final_request.len() - suffix_start,
            host.clone(),
        ),
    ];
    assert_eq!(
        ProviderRequestSegmentMapV2::verify(final_request, gap, &fixture.selected),
        Err(ProviderRequestProofErrorV2::IncompleteSegmentCoverage)
    );

    let duplicate = vec![
        segment(final_request, 0, selected_start, framing),
        segment(final_request, selected_start, 2, selected.clone()),
        segment(final_request, selected_start + 2, 3, selected),
        segment(
            final_request,
            suffix_start,
            final_request.len() - suffix_start,
            host,
        ),
    ];
    assert_eq!(
        ProviderRequestSegmentMapV2::verify(final_request, duplicate, &fixture.selected),
        Err(ProviderRequestProofErrorV2::SelectedSetMismatch)
    );

    let mut proof = exact_request_proof(&fixture);
    proof.tokenization.final_request_digest = digest("tampered-final-request");
    assert_eq!(
        proof.validate_for(final_request),
        Err(ProviderRequestProofErrorV2::FinalRequestMismatch)
    );
}

#[test]
fn typed_snapshot_successor_rejects_reset_and_revocation_resurrection() {
    let predecessor = verified_snapshot();
    let reset = snapshot("snapshot:reset", 20, 2, None, Vec::new());
    assert!(
        verify_typed_admission_snapshot_successor_v2(reset, &predecessor, &AdmissionVerifier)
            .is_err()
    );

    let revoked = verify_admission_snapshot_v2(
        snapshot(
            "snapshot:revoked",
            20,
            2,
            None,
            vec![id("admission:item:developer")],
        ),
        &AdmissionVerifier,
    )
    .expect("verified revoked predecessor");
    let resurrection = snapshot(
        "snapshot:resurrection",
        30,
        3,
        Some(revoked.snapshot_digest()),
        Vec::new(),
    );
    assert!(
        verify_typed_admission_snapshot_successor_v2(
            resurrection,
            &revoked,
            &AdmissionVerifier,
        )
        .is_err()
    );
}

#[test]
fn exact_final_request_identity_is_durable_and_receipt_bound() {
    let fixture = fixture();
    fixture
        .successor
        .validate_for(&fixture.predecessor)
        .expect("typed successor witness");
    let proof = exact_request_proof(&fixture);
    let preparation = prepare_provider_bound_delivery_v2(
        &fixture.compiled,
        fixture.canonical.serialized_context(),
        &fixture.attachment,
        &profile(),
        &fixture.successor,
        proof,
        id("preparation:provider-bound"),
    )
    .expect("provider-bound preparation");
    let record = preparation.to_record();
    record.validate().expect("durable preparation record");
    assert_eq!(record.provider_id, "provider-a");
    assert_eq!(record.model, "model-a");
    assert_eq!(record.tokenizer_version, "test-tokenizer-1.0.0");
    assert_eq!(record.final_request_digest, digest("prefix-alpha-suffix"));
    assert_eq!(record.wire_semantic_digest, digest("wire-semantic-request"));
    assert_ne!(record.final_request_digest, record.wire_semantic_digest);

    let receipt = ProviderBoundDeliveryReceiptV2::observe_record(
        &record,
        id("attempt:1"),
        id("request-binding:1"),
        ProviderBoundTerminalV2::Completed {
            terminal_evidence_digest: digest("terminal-evidence"),
        },
        40,
    )
    .expect("terminal receipt");
    receipt
        .validate_for_record(&record)
        .expect("receipt remains preparation-bound");

    let mut tampered = record.clone();
    tampered.token_count = tampered.token_count.saturating_add(1);
    assert!(tampered.validate().is_err());
    assert!(receipt.validate_for_record(&tampered).is_err());
}

#[test]
fn unicode_control_and_large_exact_requests_are_counted_over_the_actual_bytes() {
    let tokenizer = FinalByteTokenizer {
        provider: "provider-unicode".to_owned(),
        model: "model-unicode".to_owned(),
    };
    let unicode = "{\"input\":\"東京\\n🦀\\u0000\"}".as_bytes();
    let receipt = ProviderFinalRequestTokenizationV2::from_exact_bytes(unicode, &tokenizer)
        .expect("encoded unicode/control request");
    assert_eq!(
        receipt.final_request_bytes(),
        u64::try_from(unicode.len()).unwrap_or(u64::MAX)
    );
    assert_eq!(
        receipt.token_count(),
        u64::try_from(unicode.len()).unwrap_or(u64::MAX)
    );

    let large = vec![b'x'; 2 * 1024 * 1024];
    let large_receipt = ProviderFinalRequestTokenizationV2::from_exact_bytes(&large, &tokenizer)
        .expect("bounded large request");
    assert_eq!(large_receipt.final_request_bytes(), 2 * 1024 * 1024);
}

proptest! {
    #[test]
    fn final_request_receipt_changes_for_any_single_byte_mutation(
        mut body in prop::collection::vec(any::<u8>(), 1..4096),
        replacement in any::<u8>(),
    ) {
        let tokenizer = FinalByteTokenizer {
            provider: "provider-proptest".to_owned(),
            model: "model-proptest".to_owned(),
        };
        let before = ProviderFinalRequestTokenizationV2::from_exact_bytes(&body, &tokenizer)
            .expect("original receipt");
        let index = body.len() / 2;
        let original = body[index];
        body[index] = if replacement == original { replacement.wrapping_add(1) } else { replacement };
        let after = ProviderFinalRequestTokenizationV2::from_exact_bytes(&body, &tokenizer)
            .expect("mutated receipt");
        prop_assert_ne!(before.final_request_digest(), after.final_request_digest());
        prop_assert_ne!(before.receipt_digest(), after.receipt_digest());
    }
}
