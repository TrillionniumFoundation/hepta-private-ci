use super::*;

use crate::v2::ContextAdmissionSnapshotV2;
use crate::v2::ContextAdmissionVerifierV2;
use crate::v2::ContextModelProfileV2;
use crate::v2::ContextRealizedItemV2;
use crate::v2::ContextRoleV2;
use crate::v2::verify_admission_snapshot_v2;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(value: &str) -> StableId {
    match StableId::new(value.to_owned()) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error:?}"),
    }
}

fn items() -> Vec<ContextRealizedItemV2> {
    vec![
        ContextRealizedItemV2 {
            item_id: id("context:item:system"),
            role: ContextRoleV2::TrustedInstruction,
            content: "系统策略\nline\u{0000}control".as_bytes().to_vec(),
        },
        ContextRealizedItemV2 {
            item_id: id("context:item:schema"),
            role: ContextRoleV2::Schema,
            content: br#"{"type":"object","required":["answer"]}"#.to_vec(),
        },
    ]
}

fn tokenizer_identity() -> ProviderTokenizerIdentityV2 {
    ProviderTokenizerIdentityV2 {
        provider_id_digest: digest("provider"),
        provider_model_digest: digest("provider-model"),
        tokenizer_binary_digest: digest("tokenizer-binary"),
        tokenizer_version_digest: digest("tokenizer-version"),
        vocabulary_digest: digest("tokenizer-vocabulary"),
        normalization_policy_digest: digest("normalization-policy"),
    }
}

fn profile(maximum_context_tokens: u64) -> ContextModelProfileV2 {
    let template_digest = digest("template");
    let tool_schema_digest = digest("tool-schema");
    let identity = tokenizer_identity();
    ContextModelProfileV2 {
        model_digest: digest("model"),
        provider_id_digest: identity.provider_id_digest,
        provider_model_digest: identity.provider_model_digest,
        tokenizer_digest: identity.digest(),
        serializer_digest: canonical_context_serializer_digest(
            template_digest,
            tool_schema_digest,
        ),
        template_digest,
        tool_schema_digest,
        maximum_context_tokens,
    }
}

#[derive(Clone)]
struct ExactByteTokenizer {
    identity: ProviderTokenizerIdentityV2,
}

impl ExactProviderRequestTokenizerV2 for ExactByteTokenizer {
    fn identity(&self) -> ProviderTokenizerIdentityV2 {
        self.identity.clone()
    }

    fn count_tokens(
        &self,
        exact_provider_request: &[u8],
    ) -> Result<u64, ProviderBoundContextErrorV2> {
        u64::try_from(exact_provider_request.len())
            .map_err(|_| ProviderBoundContextErrorV2::Arithmetic)
    }
}

struct FramingPolicy;

impl ProviderRequestFramingPolicyV2 for FramingPolicy {
    fn policy_digest(&self) -> Digest32 {
        digest("provider-framing-policy")
    }

    fn permits(&self, framing_kind: &StableId, bytes: &[u8]) -> bool {
        match framing_kind.as_str() {
            "provider:frame:prefix" => bytes == b"{\"input\":",
            "provider:frame:suffix" => bytes == b"}",
            _ => false,
        }
    }
}

fn verified_provider_request(
    canonical: &CanonicalContextPayloadV2,
) -> VerifiedProviderRequestV2 {
    let prefix = b"{\"input\":";
    let suffix = b"}";
    let mut bytes = prefix.to_vec();
    let context_start = bytes.len();
    bytes.extend_from_slice(canonical.payload());
    let context_end = bytes.len();
    bytes.extend_from_slice(suffix);
    let request_end = bytes.len();

    let prefix_end = u64::try_from(prefix.len()).unwrap_or(u64::MAX);
    let context_start_u64 = u64::try_from(context_start).unwrap_or(u64::MAX);
    let context_end_u64 = u64::try_from(context_end).unwrap_or(u64::MAX);
    let request_end_u64 = u64::try_from(request_end).unwrap_or(u64::MAX);
    let segments = vec![
        match ProviderRequestSegmentV2::from_bytes(
            ProviderRequestSegmentKindV2::TypedFraming {
                framing_kind: id("provider:frame:prefix"),
            },
            0,
            prefix_end,
            &bytes,
        ) {
            Ok(value) => value,
            Err(error) => panic!("prefix segment: {error:?}"),
        },
        match ProviderRequestSegmentV2::from_bytes(
            ProviderRequestSegmentKindV2::CanonicalContext,
            context_start_u64,
            context_end_u64,
            &bytes,
        ) {
            Ok(value) => value,
            Err(error) => panic!("context segment: {error:?}"),
        },
        match ProviderRequestSegmentV2::from_bytes(
            ProviderRequestSegmentKindV2::TypedFraming {
                framing_kind: id("provider:frame:suffix"),
            },
            context_end_u64,
            request_end_u64,
            &bytes,
        ) {
            Ok(value) => value,
            Err(error) => panic!("suffix segment: {error:?}"),
        },
    ];
    match verify_provider_request_coverage_v2(canonical, bytes, segments, &FramingPolicy) {
        Ok(value) => value,
        Err(error) => panic!("provider request: {error:?}"),
    }
}

#[test]
fn canonical_serializer_has_complete_typed_byte_coverage() {
    let profile = profile(100_000);
    let serializer = match CanonicalContextSerializerV2::for_profile(&profile) {
        Ok(value) => value,
        Err(error) => panic!("serializer: {error:?}"),
    };
    let realized = items();
    let canonical = match serializer.serialize_with_coverage(&realized) {
        Ok(value) => value,
        Err(error) => panic!("canonical serialization: {error:?}"),
    };
    if let Err(error) = canonical.validate(&realized) {
        panic!("coverage validation: {error:?}");
    }

    assert_eq!(canonical.coverage().selected_item_ids().len(), realized.len());
    assert_eq!(
        canonical.coverage().segments().len(),
        1 + realized.len() * 2
    );
    let mut cursor = 0_u64;
    for segment in canonical.coverage().segments() {
        assert_eq!(segment.start_offset(), cursor);
        assert!(segment.end_offset() > segment.start_offset());
        cursor = segment.end_offset();
    }
    assert_eq!(
        cursor,
        u64::try_from(canonical.payload().len()).unwrap_or(u64::MAX)
    );
}

#[test]
fn canonical_coverage_rejects_any_payload_mutation() {
    let profile = profile(100_000);
    let serializer = match CanonicalContextSerializerV2::for_profile(&profile) {
        Ok(value) => value,
        Err(error) => panic!("serializer: {error:?}"),
    };
    let realized = items();
    let canonical = match serializer.serialize_with_coverage(&realized) {
        Ok(value) => value,
        Err(error) => panic!("canonical serialization: {error:?}"),
    };
    let mut mutated = canonical.payload().to_vec();
    let index = mutated.len() / 2;
    mutated[index] ^= 0x5a;
    assert_eq!(
        canonical.coverage().validate(&mutated, &realized),
        Err(ProviderBoundContextErrorV2::CanonicalCoverageMismatch)
    );
}

#[test]
fn provider_request_requires_contiguous_approved_framing() {
    let profile = profile(100_000);
    let serializer = match CanonicalContextSerializerV2::for_profile(&profile) {
        Ok(value) => value,
        Err(error) => panic!("serializer: {error:?}"),
    };
    let canonical = match serializer.serialize_with_coverage(&items()) {
        Ok(value) => value,
        Err(error) => panic!("canonical serialization: {error:?}"),
    };
    let verified = verified_provider_request(&canonical);
    if let Err(error) = verified.validate(&canonical, &FramingPolicy) {
        panic!("verified request: {error:?}");
    }

    let mut gap_segments = verified.segments().to_vec();
    gap_segments[1].start_offset = gap_segments[1].start_offset.saturating_add(1);
    assert_eq!(
        verify_provider_request_coverage_v2(
            &canonical,
            verified.bytes().to_vec(),
            gap_segments,
            &FramingPolicy,
        ),
        Err(ProviderBoundContextErrorV2::SegmentGapOrOverlap)
    );

    let mut rejected_segments = verified.segments().to_vec();
    rejected_segments[0].kind = ProviderRequestSegmentKindV2::TypedFraming {
        framing_kind: id("provider:frame:unapproved"),
    };
    assert_eq!(
        verify_provider_request_coverage_v2(
            &canonical,
            verified.bytes().to_vec(),
            rejected_segments,
            &FramingPolicy,
        ),
        Err(ProviderBoundContextErrorV2::FramingRejected(
            "provider:frame:unapproved".to_string()
        ))
    );
}

#[test]
fn final_request_tokenization_binds_provider_model_binary_vocab_and_normalization() {
    let profile = profile(100_000);
    let serializer = match CanonicalContextSerializerV2::for_profile(&profile) {
        Ok(value) => value,
        Err(error) => panic!("serializer: {error:?}"),
    };
    let canonical = match serializer.serialize_with_coverage(&items()) {
        Ok(value) => value,
        Err(error) => panic!("canonical serialization: {error:?}"),
    };
    let request = verified_provider_request(&canonical);
    let tokenizer = ExactByteTokenizer {
        identity: tokenizer_identity(),
    };
    let tokenization = match tokenize_verified_provider_request_v2(
        &profile,
        &request,
        digest("wire-semantics"),
        &tokenizer,
    ) {
        Ok(value) => value,
        Err(error) => panic!("tokenization: {error:?}"),
    };
    if let Err(error) = tokenization.validate_for(&profile, &request) {
        panic!("tokenization validation: {error:?}");
    }
    assert_eq!(
        tokenization.token_count(),
        u64::try_from(request.bytes().len()).unwrap_or(u64::MAX)
    );

    let mut wrong_identity = tokenizer_identity();
    wrong_identity.vocabulary_digest = digest("wrong-vocabulary");
    let wrong_tokenizer = ExactByteTokenizer {
        identity: wrong_identity,
    };
    assert_eq!(
        tokenize_verified_provider_request_v2(
            &profile,
            &request,
            digest("wire-semantics"),
            &wrong_tokenizer,
        ),
        Err(ProviderBoundContextErrorV2::TokenizerIdentityMismatch)
    );
}

#[test]
fn final_request_tokenization_fails_closed_on_budget_overflow() {
    let profile = profile(1);
    let serializer = match CanonicalContextSerializerV2::for_profile(&profile) {
        Ok(value) => value,
        Err(error) => panic!("serializer: {error:?}"),
    };
    let canonical = match serializer.serialize_with_coverage(&items()) {
        Ok(value) => value,
        Err(error) => panic!("canonical serialization: {error:?}"),
    };
    let request = verified_provider_request(&canonical);
    let tokenizer = ExactByteTokenizer {
        identity: tokenizer_identity(),
    };
    assert!(matches!(
        tokenize_verified_provider_request_v2(
            &profile,
            &request,
            digest("wire-semantics"),
            &tokenizer,
        ),
        Err(ProviderBoundContextErrorV2::FinalTokenBudgetExceeded { .. })
    ));
}

#[derive(Clone)]
struct SnapshotVerifier {
    digest: Digest32,
}

impl ContextAdmissionVerifierV2 for SnapshotVerifier {
    fn verifier_digest(&self) -> Digest32 {
        self.digest
    }

    fn verify_record(&self, _record: &crate::v2::ContextAdmissionRecordV2) -> bool {
        true
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        snapshot.validate_shape().is_ok()
    }
}

#[test]
fn typed_snapshot_successor_rejects_reset_and_rollback() {
    let verifier = SnapshotVerifier {
        digest: digest("snapshot-verifier"),
    };
    let scope = digest("scope");
    let authority = digest("authority");
    let initial_raw = match ContextAdmissionSnapshotV2::new(
        id("snapshot:initial"),
        scope,
        authority,
        100,
        7,
        vec![id("admission:revoked:one")],
        true,
        None,
    ) {
        Ok(value) => value,
        Err(error) => panic!("initial snapshot: {error:?}"),
    };
    let initial = match verify_admission_snapshot_v2(initial_raw, &verifier) {
        Ok(value) => value,
        Err(error) => panic!("verify initial: {error:?}"),
    };
    let successor_raw = match ContextAdmissionSnapshotV2::new(
        id("snapshot:successor"),
        scope,
        authority,
        101,
        8,
        vec![
            id("admission:revoked:one"),
            id("admission:revoked:two"),
        ],
        true,
        Some(initial.snapshot_digest()),
    ) {
        Ok(value) => value,
        Err(error) => panic!("successor snapshot: {error:?}"),
    };
    let successor = match verify_typed_admission_snapshot_successor_v2(
        successor_raw,
        &initial,
        &verifier,
    ) {
        Ok(value) => value,
        Err(error) => panic!("verify successor: {error:?}"),
    };
    if let Err(error) = successor.validate(&initial) {
        panic!("typed successor: {error:?}");
    }

    let reset_raw = match ContextAdmissionSnapshotV2::new(
        id("snapshot:reset"),
        scope,
        authority,
        102,
        9,
        vec![
            id("admission:revoked:one"),
            id("admission:revoked:two"),
        ],
        true,
        None,
    ) {
        Ok(value) => value,
        Err(error) => panic!("reset snapshot: {error:?}"),
    };
    assert!(
        verify_typed_admission_snapshot_successor_v2(reset_raw, &initial, &verifier).is_err()
    );

    let rollback_raw = match ContextAdmissionSnapshotV2::new(
        id("snapshot:rollback"),
        scope,
        authority,
        99,
        6,
        vec![id("admission:revoked:one")],
        true,
        Some(initial.snapshot_digest()),
    ) {
        Ok(value) => value,
        Err(error) => panic!("rollback snapshot: {error:?}"),
    };
    assert!(
        verify_typed_admission_snapshot_successor_v2(rollback_raw, &initial, &verifier).is_err()
    );
}

#[test]
fn deterministic_generated_corpus_preserves_or_rejects_every_byte() {
    let profile = profile(1_000_000);
    let serializer = match CanonicalContextSerializerV2::for_profile(&profile) {
        Ok(value) => value,
        Err(error) => panic!("serializer: {error:?}"),
    };
    let mut state = 0x5eed_cafe_dead_beef_u64;
    for case in 0..128_u64 {
        state = state
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1);
        let length = usize::try_from((state % 4096) + 1).unwrap_or(1);
        let mut content = Vec::with_capacity(length);
        for index in 0..length {
            state = state
                .wrapping_mul(2_862_933_555_777_941_757)
                .wrapping_add(3_037_000_493);
            let mixed = state ^ u64::try_from(index).unwrap_or(0);
            content.push(u8::try_from(mixed & 0xff).unwrap_or(0));
        }
        let realized = vec![ContextRealizedItemV2 {
            item_id: id(&format!("context:fuzz:{case}")),
            role: if case % 2 == 0 {
                ContextRoleV2::TrustedInstruction
            } else {
                ContextRoleV2::UntrustedEvidence
            },
            content,
        }];
        let canonical = match serializer.serialize_with_coverage(&realized) {
            Ok(value) => value,
            Err(error) => panic!("generated case {case}: {error:?}"),
        };
        if let Err(error) = canonical.validate(&realized) {
            panic!("generated validation {case}: {error:?}");
        }
        let mut mutated = canonical.payload().to_vec();
        let mutation_index = usize::try_from(state).unwrap_or(0) % mutated.len();
        mutated[mutation_index] ^= 1;
        assert!(canonical.coverage().validate(&mutated, &realized).is_err());
    }
}

#[test]
fn large_unicode_and_control_payload_stays_bounded_and_exact() {
    let profile = profile(1_000_000);
    let serializer = match CanonicalContextSerializerV2::for_profile(&profile) {
        Ok(value) => value,
        Err(error) => panic!("serializer: {error:?}"),
    };
    let unit = "令牌🙂\u{0000}\u{001f}\n";
    let content = unit.repeat(16_384).into_bytes();
    let realized = vec![ContextRealizedItemV2 {
        item_id: id("context:large:unicode-control"),
        role: ContextRoleV2::TrustedInstruction,
        content,
    }];
    let canonical = match serializer.serialize_with_coverage(&realized) {
        Ok(value) => value,
        Err(error) => panic!("large serialization: {error:?}"),
    };
    if let Err(error) = canonical.validate(&realized) {
        panic!("large validation: {error:?}");
    }
    assert!(canonical.payload().len() < MAX_SERIALIZED_PAYLOAD_BYTES_V2);
}
