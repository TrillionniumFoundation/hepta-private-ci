use super::*;

use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_types::FixedQ32;

use crate::ContextAdmissionBindingV2;
use crate::ContextAdmissionRecordV2;
use crate::ContextCandidateV2;
use crate::ContextCompilationRequestV2;
use crate::ContextProviderDeliveryDecisionV2;
use crate::MandatoryContextGroupV2;
use crate::TokenizationReceiptV2;
use crate::build_attachment;
use crate::compile_v2;
use crate::verify_admission_snapshot_v2;
use crate::verify_admission_v2;

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
        digest("context-tokenizer")
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        Ok(u64::try_from(bytes.len()).unwrap_or(u64::MAX))
    }
}

#[derive(Clone, Copy)]
struct UnitTokenizer;

impl ExactTokenizerV2 for UnitTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("unit-context-tokenizer")
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        Ok(u64::from(!bytes.is_empty()))
    }
}

#[derive(Clone, Copy)]
struct TestAdmissionVerifier;

impl ContextAdmissionVerifierV2 for TestAdmissionVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("admission-verifier")
    }

    fn verify_record(&self, _record: &ContextAdmissionRecordV2) -> bool {
        true
    }

    fn verify_snapshot(&self, _snapshot: &ContextAdmissionSnapshotV2) -> bool {
        true
    }
}

struct FixtureProviderTokenizer {
    descriptor: ProviderTokenizerDescriptorV2,
}

impl FixtureProviderTokenizer {
    fn new() -> Self {
        Self {
            descriptor: ProviderTokenizerDescriptorV2::new(
                digest("provider"),
                digest("model"),
                digest("fixture-tokenizer-binary"),
                "fixture-vocabulary-1",
                digest("fixture-vocabulary"),
                digest("unicode-scalar-no-normalization"),
            )
            .unwrap_or_else(|error| panic!("descriptor: {error}")),
        }
    }
}

impl ExactProviderRequestTokenizerV2 for FixtureProviderTokenizer {
    fn descriptor(&self) -> &ProviderTokenizerDescriptorV2 {
        &self.descriptor
    }

    fn count_tokens(
        &self,
        canonical_final_request: &[u8],
    ) -> Result<u64, ProviderBoundErrorV2> {
        let text = std::str::from_utf8(canonical_final_request)
            .map_err(|_| ProviderBoundErrorV2::FinalRequestSizeInvalid)?;
        Ok(u64::try_from(text.chars().count()).unwrap_or(u64::MAX))
    }
}

struct TestDeliveryVerifier {
    recorded_at_unix_ms: u64,
}

impl ContextProviderDeliveryVerifierV2 for TestDeliveryVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("provider-delivery-verifier")
    }

    fn verify_delivery(
        &self,
        receipt: &ProviderInvocationReceipt,
        preparation: &ContextDeliveryPreparationV2,
    ) -> Result<ContextProviderDeliveryDecisionV2, String> {
        let expected =
            Sha256Digest::for_bytes(preparation.preparation_digest().as_array());
        if receipt
            .intent
            .binding
            .ephemeral_input_witness_sha256
            .as_ref()
            != Some(&expected)
        {
            return Err("preparation witness mismatch".to_string());
        }
        Ok(ContextProviderDeliveryDecisionV2 {
            evidence_digest: digest("provider-delivery-evidence"),
            recorded_at_unix_ms: self.recorded_at_unix_ms,
        })
    }
}

fn profile() -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        model_digest: digest("model-profile"),
        provider_id_digest: digest("provider"),
        provider_model_digest: digest("model"),
        tokenizer_digest: digest("context-tokenizer"),
        serializer_digest: digest("canonical-context-serializer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        maximum_context_tokens: 4_096,
    }
}

fn unit_profile() -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        tokenizer_digest: digest("unit-context-tokenizer"),
        maximum_context_tokens: 1_000_000,
        ..profile()
    }
}

fn initial_snapshot() -> VerifiedAdmissionSnapshotV2 {
    let raw = ContextAdmissionSnapshotV2::new(
        id("snapshot:initial"),
        digest("scope"),
        digest("authority-domain"),
        10,
        7,
        Vec::new(),
        true,
        None,
    )
    .unwrap_or_else(|error| panic!("snapshot: {error}"));
    verify_admission_snapshot_v2(raw, &TestAdmissionVerifier)
        .unwrap_or_else(|error| panic!("verify snapshot: {error}"))
}

fn successor_snapshot(
    predecessor: &VerifiedAdmissionSnapshotV2,
    observed_unix_ms: u64,
    revocation_epoch: u64,
    revoked: Vec<StableId>,
) -> Result<VerifiedAdmissionSnapshotSuccessorV2, ProviderBoundErrorV2> {
    let raw = ContextAdmissionSnapshotV2::new(
        id(&format!("snapshot:successor:{observed_unix_ms}:{revocation_epoch}")),
        predecessor.scope_digest(),
        predecessor.authority_domain_digest(),
        observed_unix_ms,
        revocation_epoch,
        revoked,
        true,
        Some(predecessor.snapshot_digest()),
    )?;
    verify_typed_admission_snapshot_successor_v2(
        raw,
        predecessor,
        &TestAdmissionVerifier,
    )
}

fn candidate(
    item_id: &str,
    role: ContextRoleV2,
    content: Vec<u8>,
    snapshot: &VerifiedAdmissionSnapshotV2,
    tokenizer: &impl ExactTokenizerV2,
) -> (ContextCandidateV2, ContextRealizedItemV2) {
    let tokenization =
        TokenizationReceiptV2::from_exact_bytes(id(item_id), &content, tokenizer)
            .unwrap_or_else(|error| panic!("tokenization: {error}"));
    let source_digest = digest(&format!("source:{item_id}"));
    let record = ContextAdmissionRecordV2::new(
        id(&format!("admission:{item_id}")),
        ContextAdmissionBindingV2 {
            item_id: id(item_id),
            role,
            content_digest: tokenization.content_digest(),
            source_digest,
            generation_vector_digest: digest("generation-vector"),
            scope_digest: digest("scope"),
            authority_domain_digest: digest("authority-domain"),
            contains_secret: false,
        },
        1,
        100_000,
    )
    .unwrap_or_else(|error| panic!("admission record: {error}"));
    let admission = verify_admission_v2(record, snapshot, &TestAdmissionVerifier)
        .unwrap_or_else(|error| panic!("verify admission: {error}"));
    (
        ContextCandidateV2 {
            item_id: id(item_id),
            role,
            content_digest: tokenization.content_digest(),
            source_digest,
            generation_vector_digest: digest("generation-vector"),
            tokenization,
            expected_value: FixedQ32::ONE,
            admission,
        },
        ContextRealizedItemV2 {
            item_id: id(item_id),
            role,
            content,
        },
    )
}

fn compile_fixture(
    profile: ContextModelProfileV2,
    candidates: Vec<ContextCandidateV2>,
    token_budget: u64,
) -> CompiledContextV2 {
    compile_v2(ContextCompilationRequestV2 {
        compilation_id: id("compilation:provider-bound"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation-vector"),
        scope_digest: digest("scope"),
        authority_domain_digest: digest("authority-domain"),
        admission_verifier_digest: digest("admission-verifier"),
        model_profile: profile,
        token_budget,
        truncation_policy_digest: digest("truncation-policy"),
        candidates,
        mandatory_groups: Vec::<MandatoryContextGroupV2>::new(),
    })
    .unwrap_or_else(|error| panic!("compile fixture: {error}"))
}

fn strict_fixture() -> (
    VerifiedAdmissionSnapshotV2,
    ContextModelProfileV2,
    CompiledContextV2,
    CanonicalContextBundleV2,
    ContextAttachmentV2,
) {
    let snapshot = initial_snapshot();
    let profile = profile();
    let (instruction, instruction_bytes) = candidate(
        "item:instruction",
        ContextRoleV2::TrustedInstruction,
        b"follow policy".to_vec(),
        &snapshot,
        &ByteTokenizer,
    );
    let (evidence, evidence_bytes) = candidate(
        "item:evidence",
        ContextRoleV2::UntrustedEvidence,
        "snowman: \u{2603}\ncontrol:\u{0001}".as_bytes().to_vec(),
        &snapshot,
        &ByteTokenizer,
    );
    let compiled = compile_fixture(profile.clone(), vec![evidence, instruction], 4_096);
    let bundle = record_canonical_serialization_v2(
        &compiled,
        &profile,
        id("serialization:canonical"),
        vec![evidence_bytes, instruction_bytes],
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("canonical serialization: {error}"));
    let attachment = build_attachment(
        &compiled,
        bundle.serialized(),
        &profile,
        &snapshot,
        id("attachment:canonical"),
    )
    .unwrap_or_else(|error| panic!("attachment: {error}"));
    (snapshot, profile, compiled, bundle, attachment)
}

fn provider_receipt(
    bundle: &CanonicalContextBundleV2,
    preparation: &ProviderBoundDeliveryPreparationV2,
    wire_sha256: Sha256Digest,
) -> ProviderInvocationReceipt {
    let binding = ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-request"),
        request_kind: ProviderRequestKind::Turn,
        provider_id: "provider".to_string(),
        provider_config_sha256: Sha256Digest::for_bytes(b"provider-config"),
        model: "model".to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
        logical_request_sha256: Sha256Digest::for_bytes(b"logical-request"),
        wire_semantic_sha256: wire_sha256,
        ephemeral_input_sha256: Some(Sha256Digest::for_bytes(bundle.payload())),
        ephemeral_input_witness_sha256: Some(Sha256Digest::for_bytes(
            preparation.preparation().preparation_digest().as_array(),
        )),
        previous_response_id_sha256: None,
        generate: true,
    };
    ProviderInvocationReceipt::new(
        ProviderInvocationIntent::for_host_attempt_id("host-attempt-1", binding),
        ProviderTerminal::Completed {
            response_id_sha256: Sha256Digest::for_bytes(b"response"),
            response_items_sha256: Sha256Digest::for_bytes(b"items"),
            token_usage_sha256: Sha256Digest::for_bytes(b"usage"),
            end_turn: Some(true),
        },
    )
}

#[test]
fn canonical_bundle_has_exhaustive_typed_coverage() {
    let (_snapshot, profile, compiled, bundle, _attachment) = strict_fixture();
    bundle
        .validate_for(&compiled, &profile)
        .unwrap_or_else(|error| panic!("bundle validates: {error}"));
    assert_eq!(
        bundle
            .segments()
            .iter()
            .map(|segment| segment.length)
            .sum::<u64>(),
        u64::try_from(bundle.payload().len()).unwrap_or(u64::MAX)
    );
    let selected = bundle
        .segments()
        .iter()
        .filter_map(|segment| match &segment.kind {
            CanonicalContextSegmentKindV2::SelectedItem { item_id, .. } => {
                Some(item_id.clone())
            }
            CanonicalContextSegmentKindV2::TypedFraming(_) => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(selected, compiled.receipt().selected_item_ids());
}

#[test]
fn canonical_bundle_rejects_gap_overlap_and_appended_bytes() {
    let (_snapshot, profile, compiled, bundle, _attachment) = strict_fixture();

    let mut gap = bundle.clone();
    gap.segments[1].offset = gap.segments[1].offset.saturating_add(1);
    assert!(matches!(
        gap.validate_for(&compiled, &profile),
        Err(ProviderBoundErrorV2::InvalidSegmentMap(_))
    ));

    let mut overlap = bundle.clone();
    overlap.segments[1].offset = overlap.segments[1].offset.saturating_sub(1);
    assert!(matches!(
        overlap.validate_for(&compiled, &profile),
        Err(ProviderBoundErrorV2::InvalidSegmentMap(_))
    ));

    let mut digest_mutation = bundle;
    digest_mutation.segments[0].content_digest = digest("forged");
    assert!(matches!(
        digest_mutation.validate_for(&compiled, &profile),
        Err(ProviderBoundErrorV2::DigestMismatch("canonical segment"))
    ));
}

struct AppendingSerializer;

impl ContextSerializerV2 for AppendingSerializer {
    fn serializer_digest(&self) -> Digest32 {
        digest("canonical-context-serializer")
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
        let mut payload = items
            .iter()
            .flat_map(|item| item.content.iter().copied())
            .collect::<Vec<_>>();
        payload.extend_from_slice(b"UNDECLARED");
        Ok(payload)
    }
}

#[test]
fn strict_api_removes_the_prepared_payload_injection_seam() {
    let snapshot = initial_snapshot();
    let profile = profile();
    let (candidate, realization) = candidate(
        "item:serializer-adversary",
        ContextRoleV2::TrustedInstruction,
        b"authorized".to_vec(),
        &snapshot,
        &ByteTokenizer,
    );
    let compiled = compile_fixture(profile.clone(), vec![candidate], 4_096);
    let legacy = record_serialization(
        &compiled,
        &profile,
        id("serialization:legacy-adversarial"),
        vec![realization.clone()],
        &AppendingSerializer,
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("legacy serializer demonstrates seam: {error}"));
    assert!(legacy.payload().ends_with(b"UNDECLARED"));

    let strict = record_canonical_serialization_v2(
        &compiled,
        &profile,
        id("serialization:strict"),
        vec![realization],
        &ByteTokenizer,
    )
    .unwrap_or_else(|error| panic!("strict serializer: {error}"));
    assert!(!strict.payload().windows(10).any(|window| window == b"UNDECLARED"));
    strict
        .validate_for(&compiled, &profile)
        .unwrap_or_else(|error| panic!("strict bundle validates: {error}"));
}

#[test]
fn typed_successor_rejects_reset_rollback_and_revocation_resurrection() {
    let predecessor = initial_snapshot();

    let reset = ContextAdmissionSnapshotV2::new(
        id("snapshot:reset"),
        predecessor.scope_digest(),
        predecessor.authority_domain_digest(),
        11,
        8,
        Vec::new(),
        true,
        None,
    )
    .unwrap_or_else(|error| panic!("reset snapshot shape: {error}"));
    assert!(verify_typed_admission_snapshot_successor_v2(
        reset,
        &predecessor,
        &TestAdmissionVerifier,
    )
    .is_err());

    let rollback = ContextAdmissionSnapshotV2::new(
        id("snapshot:rollback"),
        predecessor.scope_digest(),
        predecessor.authority_domain_digest(),
        9,
        6,
        Vec::new(),
        true,
        Some(predecessor.snapshot_digest()),
    )
    .unwrap_or_else(|error| panic!("rollback snapshot shape: {error}"));
    assert!(verify_typed_admission_snapshot_successor_v2(
        rollback,
        &predecessor,
        &TestAdmissionVerifier,
    )
    .is_err());

    let revoked_id = id("admission:revoked");
    let revoked = successor_snapshot(&predecessor, 11, 8, vec![revoked_id.clone()])
        .unwrap_or_else(|error| panic!("revoking successor: {error}"));
    let resurrection = ContextAdmissionSnapshotV2::new(
        id("snapshot:resurrection"),
        revoked.successor().scope_digest(),
        revoked.successor().authority_domain_digest(),
        12,
        9,
        Vec::new(),
        true,
        Some(revoked.successor().snapshot_digest()),
    )
    .unwrap_or_else(|error| panic!("resurrection shape: {error}"));
    assert!(verify_typed_admission_snapshot_successor_v2(
        resurrection,
        revoked.successor(),
        &TestAdmissionVerifier,
    )
    .is_err());
}

#[test]
fn exact_final_request_tokenization_binds_all_runtime_identity() {
    let tokenizer = FixtureProviderTokenizer::new();
    let request = "{\"model\":\"model\",\"input\":\"A\u{030A}\\n\u{0001}\u{2603}\"}".as_bytes();
    let wire = Sha256Digest::for_bytes(request);
    let receipt =
        tokenize_provider_final_request_v2(request, wire.clone(), 4_096, &tokenizer)
            .unwrap_or_else(|error| panic!("tokenize final request: {error}"));
    assert_eq!(
        receipt.token_count(),
        u64::try_from(
            std::str::from_utf8(request)
                .unwrap_or_else(|error| panic!("UTF-8 fixture: {error}"))
                .chars()
                .count()
        )
        .unwrap_or(u64::MAX)
    );
    assert_eq!(receipt.provider_wire_semantic_sha256(), &wire);

    let mut descriptor = tokenizer.descriptor.clone();
    descriptor.vocabulary_digest = digest("mutated-vocabulary");
    assert!(matches!(
        descriptor.validate(),
        Err(ProviderBoundErrorV2::DigestMismatch(
            "tokenizer descriptor"
        ))
    ));
    assert!(matches!(
        tokenize_provider_final_request_v2(
            request,
            Sha256Digest::for_bytes(b"different"),
            4_096,
            &tokenizer,
        ),
        Err(ProviderBoundErrorV2::ProviderWireDigestMismatch)
    ));
}

#[test]
fn provider_bound_delivery_closes_wire_semantic_identity() {
    let (snapshot, profile, compiled, bundle, attachment) = strict_fixture();
    let successor = successor_snapshot(&snapshot, 20, 8, Vec::new())
        .unwrap_or_else(|error| panic!("successor: {error}"));
    let final_request =
        b"{\"model\":\"model\",\"input\":[\"follow policy\",\"snowman: \\u2603\"]}";
    let tokenizer = FixtureProviderTokenizer::new();
    let tokenization = tokenize_provider_final_request_v2(
        final_request,
        Sha256Digest::for_bytes(final_request),
        profile.maximum_context_tokens,
        &tokenizer,
    )
    .unwrap_or_else(|error| panic!("final request tokenization: {error}"));
    let preparation = prepare_provider_bound_delivery_v2(
        &compiled,
        &bundle,
        &attachment,
        &profile,
        &successor,
        id("preparation:provider-bound"),
        digest("prompt-fragments"),
        tokenization,
    )
    .unwrap_or_else(|error| panic!("provider-bound preparation: {error}"));
    let provider_receipt = provider_receipt(
        &bundle,
        &preparation,
        Sha256Digest::for_bytes(final_request),
    );
    let receipt = observe_provider_bound_delivery_v2(
        &preparation,
        &compiled,
        &bundle,
        &attachment,
        &profile,
        id("delivery:provider-bound"),
        &provider_receipt,
        &TestDeliveryVerifier {
            recorded_at_unix_ms: 21,
        },
        22,
    )
    .unwrap_or_else(|error| panic!("provider-bound delivery: {error}"));
    receipt
        .validate_for(&preparation, &attachment, &bundle, &profile)
        .unwrap_or_else(|error| panic!("receipt validates: {error}"));

    let mismatched = provider_receipt(
        &bundle,
        &preparation,
        Sha256Digest::for_bytes(b"different-wire"),
    );
    assert!(matches!(
        observe_provider_bound_delivery_v2(
            &preparation,
            &compiled,
            &bundle,
            &attachment,
            &profile,
            id("delivery:mismatch"),
            &mismatched,
            &TestDeliveryVerifier {
                recorded_at_unix_ms: 21,
            },
            22,
        ),
        Err(ProviderBoundErrorV2::ProviderWireDigestMismatch)
    ));
}

#[test]
fn unicode_control_and_large_inputs_remain_exact_and_bounded() {
    let snapshot = initial_snapshot();
    let profile = unit_profile();
    let mut large = vec![b'x'; 1024 * 1024];
    let prefix = "雪\u{0000}\n".as_bytes();
    large[..prefix.len()].copy_from_slice(prefix);
    let (candidate, realization) = candidate(
        "item:large",
        ContextRoleV2::TrustedInstruction,
        large,
        &snapshot,
        &UnitTokenizer,
    );
    let compiled = compile_fixture(profile.clone(), vec![candidate], 1_000_000);
    let bundle = record_canonical_serialization_v2(
        &compiled,
        &profile,
        id("serialization:large"),
        vec![realization],
        &UnitTokenizer,
    )
    .unwrap_or_else(|error| panic!("large canonical bundle: {error}"));
    bundle
        .validate_for(&compiled, &profile)
        .unwrap_or_else(|error| panic!("large bundle validates: {error}"));

    let tokenizer = FixtureProviderTokenizer::new();
    assert!(matches!(
        tokenize_provider_final_request_v2(
            &[],
            Sha256Digest::for_bytes(&[]),
            1_000_000,
            &tokenizer,
        ),
        Err(ProviderBoundErrorV2::FinalRequestSizeInvalid)
    ));
}

#[test]
fn deterministic_mutation_corpus_never_accepts_segment_tampering() {
    let (_snapshot, profile, compiled, bundle, _attachment) = strict_fixture();
    for index in 0..bundle.segments.len() {
        let mut mutated = bundle.clone();
        mutated.segments[index].length = mutated.segments[index].length.saturating_add(1);
        assert!(
            mutated.validate_for(&compiled, &profile).is_err(),
            "segment length mutation {index} was accepted"
        );

        let mut mutated = bundle.clone();
        mutated.segments[index].content_digest =
            Digest32::of_bytes(format!("mutation:{index}").as_bytes());
        assert!(
            mutated.validate_for(&compiled, &profile).is_err(),
            "segment digest mutation {index} was accepted"
        );
    }
}
