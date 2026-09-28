use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use proptest::prelude::*;
use serde::Deserialize;
use serde::Serialize;

use crate::consumer_adapters::COGNITIVE_STORE_CONSUMER_V1;
use crate::consumer_adapters::CanonicalShadowComparisonV1;
use crate::consumer_adapters::REGISTERED_CONSUMERS_V1;
use crate::contract::Validated;
use crate::hnmf::AssetExtentV1;
use crate::hnmf::AssetManifestV1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::ModalityKindV1;
use crate::hnmf::ModalitySpanRefV1;
use crate::hnmf::PrivacyClassV1;
use crate::hnmf::SpanRangeV1;
use crate::hnmf::validate_span_against_manifest_v1;
use crate::hnmf_learning::PlasticityClassV1;
use crate::hnmf_learning::SynapseRelationV1;
use crate::hnmf_learning::SynapseV1;
use crate::lane_c::CognitiveSnapshotKeyV1;
use crate::lane_c::FederatedCompletenessV1;
use crate::lane_c::FederatedCoverageV1;
use crate::lane_c::FederatedEvidenceItemV1;
use crate::lane_c::FederatedEvidenceResultV1;
use crate::lane_c::FederatedValidityV1;
use crate::lane_c::LaneCGenerationVectorV1;
use crate::lane_c::MemoryWriteDisposition;
use crate::lane_c::MemoryWriteIntentV1;
use crate::lane_c::MemoryWriteOutcomeV1;
use crate::lane_c::MemoryWriteReceiptV1;
use crate::lane_c::MemoryWriteRejectionCodeV1;
use crate::wire::CognitiveContractV1;
use crate::wire::canonical_contract_digest_bound_v1;
use crate::wire::canonical_contract_digest_v1;
use crate::wire::decode_validated_wire_v1;
use crate::wire::encode_wire_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid contract id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value))
        .unwrap_or_else(|error| panic!("valid digest: {error}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:hardening"),
        purpose_id: id("purpose:hardening"),
        memory_ledger_frontier: 7,
        knowledge_fact_frontier: 5,
        tombstone_frontier: 2,
        source_ledger_frontier: 9,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(2),
        prompt_registry_revision: revision(4),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 11,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot: {error}"))
}

#[test]
fn write_receipt_binds_complete_intent_and_rejection_has_no_record_placeholder() {
    let expected = snapshot_key();
    let intent = MemoryWriteIntentV1::new(
        id("intent:hardening"),
        digest("candidate"),
        expected.clone(),
        digest("writer-fence"),
        digest("authorization"),
    )
    .expect("valid intent");
    let mut committed_vector = expected.vector.clone();
    committed_vector.memory_ledger_frontier += 1;
    let committed_snapshot = CognitiveSnapshotKeyV1::new(committed_vector).expect("snapshot");
    let committed = MemoryWriteReceiptV1::committed(
        &intent,
        committed_snapshot,
        id("record:hardening"),
        digest("record"),
        expected.vector.memory_ledger_frontier + 1,
        MemoryWriteDisposition::Inserted,
    )
    .expect("committed receipt");
    committed
        .validate_against_intent(&intent)
        .expect("receipt binds intent");
    assert_eq!(committed.candidate_digest(), digest("candidate"));
    assert_eq!(committed.authorization_digest(), digest("authorization"));
    assert_eq!(committed.writer_fence_digest(), digest("writer-fence"));

    let different = MemoryWriteIntentV1::new(
        id("intent:hardening"),
        digest("different-candidate"),
        expected.clone(),
        digest("writer-fence"),
        digest("authorization"),
    )
    .expect("different intent");
    assert!(committed.validate_against_intent(&different).is_err());

    let rejected = MemoryWriteReceiptV1::rejected(
        &intent,
        expected,
        MemoryWriteRejectionCodeV1::AuthorizationDenied,
        digest("denial-evidence"),
    )
    .expect("rejected receipt");
    assert!(rejected.record_id().is_none());
    assert!(rejected.record_digest().is_none());
    assert!(rejected.committed_frontier().is_none());
    assert!(matches!(
        rejected.outcome(),
        MemoryWriteOutcomeV1::Rejected {
            code: MemoryWriteRejectionCodeV1::AuthorizationDenied,
            ..
        }
    ));
}

#[test]
fn federation_completeness_is_cross_field_consistent() {
    let mut result = FederatedEvidenceResultV1 {
        query_id: id("query:hardening"),
        peer_id: id("peer:aggregate"),
        observed_snapshot: snapshot_key(),
        items: vec![FederatedEvidenceItemV1 {
            source_owner_id: id("owner:1"),
            record_id: id("record:1"),
            record_revision: revision(1),
            record_digest: digest("record"),
            support_digest: digest("support"),
            validity_digest: digest("validity"),
        }],
        coverage: FederatedCoverageV1 {
            requested_peers: 2,
            completed_peers: 1,
            failed_peers: 1,
            truncated_items: 0,
        },
        completeness: FederatedCompletenessV1::Partial,
        validity: FederatedValidityV1::Valid,
        expires_unix_ms: 10,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = result.compute_result_digest();
    result.validate().expect("valid partial result");

    result.completeness = FederatedCompletenessV1::Complete;
    result.result_digest = result.compute_result_digest();
    assert!(result.validate().is_err());
}

#[test]
fn selector_must_exist_in_the_bound_asset_index() {
    let manifest = AssetManifestV1 {
        asset_sha256: contract_digest("asset"),
        modality: ModalityKindV1::CodeAst,
        extent: AssetExtentV1::CodeAst {
            valid_paths: BTreeSet::from(["module/item".to_string()]),
        },
        preprocessor_manifest_sha256: contract_digest("preprocessor"),
    };
    let mut span = ModalitySpanRefV1 {
        span_id: contract_id("span:ast"),
        modality: ModalityKindV1::CodeAst,
        asset_sha256: contract_digest("asset"),
        range: SpanRangeV1::AstPath {
            path: "module/item".to_string(),
        },
        preprocessor_manifest_sha256: contract_digest("preprocessor"),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 0,
        privacy_class: PrivacyClassV1::AgentPrivate,
        redaction_mask_sha256: None,
    };
    validate_span_against_manifest_v1(&manifest, &span).expect("indexed selector");
    span.range = SpanRangeV1::AstPath {
        path: "module/missing".to_string(),
    };
    assert!(validate_span_against_manifest_v1(&manifest, &span).is_err());
}

#[test]
fn synapse_relation_sign_and_fixed_eligibility_are_enforced() {
    let mut synapse = SynapseV1 {
        source_node_id: contract_id("node:source"),
        target_node_id: contract_id("node:target"),
        relation: SynapseRelationV1::Inhibitory,
        weight_q16: -1,
        delay_steps: 0,
        plasticity_class: PlasticityClassV1::Fixed,
        eligibility_ppm: 0,
        support_manifest_sha256: contract_digest("support"),
        snapshot_generation: ContractGenerationV1::new(1).expect("generation"),
    };
    synapse.validate().expect("negative inhibitory synapse");
    synapse.weight_q16 = 1;
    assert!(synapse.validate().is_err());
    synapse.weight_q16 = -1;
    synapse.eligibility_ppm = 1;
    assert!(synapse.validate().is_err());
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TextProbeV1 {
    value: String,
}

impl CognitiveContractV1 for TextProbeV1 {
    const CONTRACT_ID: &'static str = "hepta.test.text-probe.v1";
    const SCHEMA_ID: &'static str = "hepta.test.text-probe.schema.v1";
    const MAX_ENCODED_BYTES: usize = 1_024;

    fn validate_contract(&self) -> Result<(), HnmfContractError> {
        if self.value.is_empty()
            || self.value.len() > 64
            || self.value.chars().any(char::is_control)
        {
            return Err(HnmfContractError::Invalid("text probe"));
        }
        Ok(())
    }
}

proptest! {
    #[test]
    fn canonical_wire_round_trip_is_a_property(value in "[a-z]{1,64}") {
        let probe = TextProbeV1 { value };
        let encoded = encode_wire_v1(&probe).expect("canonical encode");
        let decoded: Validated<TextProbeV1> =
            decode_validated_wire_v1(&encoded).expect("validated decode");
        prop_assert_eq!(decoded.as_inner(), &probe);
        prop_assert_eq!(encode_wire_v1(decoded.as_inner()).expect("reencode"), encoded);
    }
}

#[test]
fn bound_digest_includes_profile_and_preserves_unicode_code_points() {
    let nfc = TextProbeV1 {
        value: "é".to_string(),
    };
    let nfd = TextProbeV1 {
        value: "e\u{301}".to_string(),
    };
    assert_ne!(
        canonical_contract_digest_bound_v1(&nfc).expect("nfc digest"),
        canonical_contract_digest_bound_v1(&nfd).expect("nfd digest")
    );
    assert_ne!(
        canonical_contract_digest_v1(&nfc).expect("legacy digest"),
        canonical_contract_digest_bound_v1(&nfc).expect("bound digest")
    );
}

#[test]
fn rust_matches_the_cross_language_bound_digest_vector() {
    let span = ModalitySpanRefV1 {
        span_id: contract_id("span:1"),
        modality: ModalityKindV1::Text,
        asset_sha256: ContractDigestV1::parse(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        .expect("asset digest"),
        range: SpanRangeV1::ByteRange { start: 0, end: 4 },
        preprocessor_manifest_sha256: ContractDigestV1::parse(
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )
        .expect("preprocessor digest"),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 10_000,
        privacy_class: PrivacyClassV1::AgentPrivate,
        redaction_mask_sha256: None,
    };
    assert_eq!(
        canonical_contract_digest_bound_v1(&span)
            .expect("bound digest")
            .to_string(),
        "3b26fc9684c21992c2a1740a1b2521b9297579f48a9c9cc2d4d9ee574afcfcb3",
    );
}

#[test]
fn consumer_registry_and_shadow_receipt_are_machine_checkable() {
    assert_eq!(REGISTERED_CONSUMERS_V1.len(), 5);
    let comparison = CanonicalShadowComparisonV1::new(
        &COGNITIVE_STORE_CONSUMER_V1,
        digest("legacy"),
        digest("canonical"),
    )
    .expect("comparison");
    comparison.validate().expect("valid comparison");
    assert!(!comparison.matched());
}
