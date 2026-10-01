use std::collections::BTreeSet;

use codex_hepta_cognitive_read::CanonicalAuthoritativeReadShadowV2;
use codex_hepta_cognitive_read::CanonicalReadShadowRowV2;
use codex_hepta_cognitive_read::CanonicalSourceRevisionBindingV2;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf::MemoryScopeV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
use codex_hepta_cognitive_types::hnmf::ObservedIntervalV1;
use codex_hepta_cognitive_types::hnmf::PrivacyClassV1;
use codex_hepta_cognitive_types::hnmf::ProvenanceRefV1;
use codex_hepta_cognitive_types::hnmf::RetentionPolicyV1;
use codex_hepta_cognitive_types::hnmf::SpanRangeV1;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;

use super::*;
use crate::ContextAdmissionBindingV2;
use crate::ContextAdmissionRecordV2;
use crate::ContextAdmissionSnapshotV2;
use crate::ContextAdmissionVerifierV2;
use crate::ContextCandidateV2;
use crate::ContextModelProfileV2;
use crate::ExactTokenizerV2;
use crate::TokenizationReceiptV2;
use crate::verify_admission_snapshot_v2;
use crate::verify_admission_v2;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("valid contract id")
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value)).expect("valid contract digest")
}

fn event() -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: contract_id("event:one"),
        episode_id: contract_id("episode:one"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: contract_id("agent:one"),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: 1,
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: contract_id("span:one"),
            modality: ModalityKindV1::Text,
            asset_sha256: contract_digest("asset"),
            range: SpanRangeV1::ByteRange { start: 0, end: 4 },
            preprocessor_manifest_sha256: contract_digest("preprocessor"),
            feature_blob_sha256: None,
            symbolic_projection_sha256: None,
            uncertainty_ppm: 0,
            privacy_class: PrivacyClassV1::AgentPrivate,
            redaction_mask_sha256: None,
        }],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from(["door".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: contract_id("source:one"),
            source_revision: 1,
            source_sha256: contract_digest("source-digest:one"),
            observed_at_unix_ms: 1,
        }],
        verification: MemoryVerificationStateV1::Verified,
        retention_policy: RetentionPolicyV1::Persistent {
            retain_until_unix_ms: None,
        },
        objective_digest: contract_digest("objective"),
        ndu_state_digest: contract_digest("ndu"),
        causal_parents: BTreeSet::new(),
        temporal_neighbors: BTreeSet::new(),
        behavior_propensity_ppm: None,
        lifecycle: MemoryLifecycleV1::Active,
    }
}

fn shadow() -> CanonicalAuthoritativeReadShadowV2 {
    let event = event();
    let event_digest = canonical_contract_digest_v1(&event).expect("canonical event");
    let row = CanonicalReadShadowRowV2 {
        legacy_record_id: id("memory:one"),
        legacy_record_revision: Revision::new(1).expect("revision"),
        legacy_record_digest: digest("legacy-record"),
        source_revisions: vec![CanonicalSourceRevisionBindingV2 {
            source_id: id("source:one"),
            source_revision: 1,
            source_digest: digest("source-digest:one"),
        }],
        event_id: event.event_id.clone(),
        event_digest,
        event,
    };
    let mut shadow = CanonicalAuthoritativeReadShadowV2 {
        request_digest: digest("request"),
        snapshot_receipt_digest: digest("snapshot-receipt"),
        generation_vector_digest: digest("generation-vector"),
        read_receipt_digest: digest("read-receipt"),
        rows: vec![row],
        omitted_count: 0,
        binding_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    shadow.binding_digest = shadow.compute_binding_digest();
    shadow.validate().expect("valid shadow");
    shadow
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
struct Verifier;

impl ContextAdmissionVerifierV2 for Verifier {
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

fn request(ingress: &VerifiedCognitiveReadIngressV2) -> ContextCompilationRequestV2 {
    let bytes = b"rendered canonical event";
    let tokenization =
        TokenizationReceiptV2::from_exact_bytes(id("event:one"), bytes, &ByteTokenizer)
            .expect("tokenization");
    let snapshot = verify_admission_snapshot_v2(
        ContextAdmissionSnapshotV2::new(
            id("snapshot:one"),
            digest("scope"),
            digest("authority-domain"),
            10,
            1,
            Vec::new(),
            true,
            None,
        )
        .expect("snapshot"),
        &Verifier,
    )
    .expect("verified snapshot");
    let row = &ingress.rows()[0];
    let admission = verify_admission_v2(
        ContextAdmissionRecordV2::new(
            id("admission:one"),
            ContextAdmissionBindingV2 {
                item_id: id("event:one"),
                role: ContextRoleV2::UntrustedEvidence,
                content_digest: tokenization.content_digest(),
                source_digest: row.source_digest(),
                generation_vector_digest: ingress.generation_vector_digest(),
                scope_digest: digest("scope"),
                authority_domain_digest: digest("authority-domain"),
                contains_secret: false,
            },
            1,
            1_000,
        )
        .expect("admission record"),
        &snapshot,
        &Verifier,
    )
    .expect("verified admission");
    ContextCompilationRequestV2 {
        compilation_id: id("compilation:one"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: ingress.generation_vector_digest(),
        scope_digest: digest("scope"),
        authority_domain_digest: digest("authority-domain"),
        admission_verifier_digest: digest("admission-verifier"),
        model_profile: ContextModelProfileV2 {
            model_digest: digest("model-profile"),
            provider_id_digest: digest("provider"),
            provider_model_digest: digest("provider-model"),
            tokenizer_digest: digest("tokenizer"),
            serializer_digest: digest("serializer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
            maximum_context_tokens: 1_000,
        },
        token_budget: 1_000,
        truncation_policy_digest: digest("truncation"),
        candidates: vec![ContextCandidateV2 {
            item_id: id("event:one"),
            role: ContextRoleV2::UntrustedEvidence,
            content_digest: tokenization.content_digest(),
            source_digest: row.source_digest(),
            generation_vector_digest: ingress.generation_vector_digest(),
            tokenization,
            expected_value: FixedQ32::ONE,
            admission,
        }],
        mandatory_groups: Vec::new(),
    }
}

#[test]
fn complete_revision_bound_shadow_compiles_through_existing_v2_admission() {
    let shadow = shadow();
    let ingress = verify_cognitive_read_ingress_v2(&shadow).expect("ingress");
    assert_eq!(ingress.rows().len(), 1);
    assert!(!ingress.authority().grants_any());

    let compiled = compile_cognitive_read_v2(&ingress, request(&ingress)).expect("compile");
    assert_eq!(compiled.receipt().selected_item_ids(), &[id("event:one")]);
    assert!(!compiled.receipt().authority().grants_any());
}

#[test]
fn omission_and_source_substitution_fail_closed() {
    let mut incomplete = shadow();
    incomplete.omitted_count = 1;
    incomplete.binding_digest = incomplete.compute_binding_digest();
    assert!(matches!(
        verify_cognitive_read_ingress_v2(&incomplete),
        Err(CognitiveReadIngressError::IncompleteSourceRead { omitted: 1 })
    ));

    let shadow = shadow();
    let ingress = verify_cognitive_read_ingress_v2(&shadow).expect("ingress");
    let mut request = request(&ingress);
    request.candidates[0].source_digest = digest("substituted-source");
    assert!(matches!(
        compile_cognitive_read_v2(&ingress, request),
        Err(CognitiveReadIngressError::CandidateSourceMismatch(_))
    ));
}

#[test]
fn cognitive_rows_cannot_be_promoted_to_trusted_instructions() {
    let shadow = shadow();
    let ingress = verify_cognitive_read_ingress_v2(&shadow).expect("ingress");
    let mut request = request(&ingress);
    request.candidates[0].role = ContextRoleV2::TrustedInstruction;
    assert!(matches!(
        compile_cognitive_read_v2(&ingress, request),
        Err(CognitiveReadIngressError::CandidateRoleMismatch(_))
    ));
}

#[test]
fn ingress_envelope_preflight_precedes_shadow_validation() {
    let mut oversized = shadow();
    oversized
        .rows
        .resize(MAX_CONTEXT_CANDIDATES_V2 + 1, oversized.rows[0].clone());
    oversized.binding_digest = Digest32::ZERO;
    assert_eq!(
        verify_cognitive_read_ingress_v2(&oversized).err(),
        Some(CognitiveReadIngressError::InvalidRowCount)
    );

    let mut empty = shadow();
    empty.rows.clear();
    empty.binding_digest = Digest32::ZERO;
    assert_eq!(
        verify_cognitive_read_ingress_v2(&empty).err(),
        Some(CognitiveReadIngressError::InvalidRowCount)
    );

    let mut incomplete = shadow();
    incomplete.omitted_count = 1;
    incomplete.binding_digest = Digest32::ZERO;
    assert_eq!(
        verify_cognitive_read_ingress_v2(&incomplete).err(),
        Some(CognitiveReadIngressError::IncompleteSourceRead { omitted: 1 })
    );

    let mut bounded = shadow();
    bounded.binding_digest = Digest32::ZERO;
    assert!(matches!(
        verify_cognitive_read_ingress_v2(&bounded),
        Err(CognitiveReadIngressError::Shadow(
            CanonicalReadShadowV2Error::EmptyDigest
        ))
    ));
}
