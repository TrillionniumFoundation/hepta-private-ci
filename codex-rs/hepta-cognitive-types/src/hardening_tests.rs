use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::contract::Validated;
use crate::hnmf::AssetExtentV1;
use crate::hnmf::AssetManifestV1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::ModalityKindV1;
use crate::hnmf::ModalitySpanRefV1;
use crate::hnmf::PrivacyClassV1;
use crate::hnmf::SpanRangeV1;
use crate::hnmf_learning::PlasticityClassV1;
use crate::hnmf_learning::SynapseRelationV1;
use crate::hnmf_learning::SynapseV1;
use crate::lane_c::CognitiveSnapshotKeyV1;
use crate::lane_c::LaneCGenerationVectorV1;
use crate::lane_c::MemoryWriteDisposition as LegacyMemoryWriteDisposition;
use crate::lane_c::MemoryWriteIntentV1 as LegacyMemoryWriteIntentV1;
use crate::lane_c::MemoryWriteReceiptV1 as LegacyMemoryWriteReceiptV1;
use crate::registry::RegistryErrorV1;
use crate::registry::decode_registered_wire_v1;
use crate::registry::inspect_registered_envelope_v1;
use crate::strict::SelectorResolutionContextV1;
use crate::strict::ValidateStrictV1;
use crate::strict::validate_json_pointer_v1;
use crate::wire::canonical_contract_digest_v1;
use crate::write_receipt::MemoryWriteOutcomeV1;
use crate::write_receipt::MemoryWriteReceiptV1;
use crate::write_receipt::MemoryWriteRejectionCodeV1;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid test id: {error}"))
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid contract id: {error}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn contract_generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value)
        .unwrap_or_else(|error| panic!("valid contract generation: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value))
        .unwrap_or_else(|error| panic!("valid contract digest: {error}"))
}

fn snapshot(memory_frontier: u64) -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:tenant-a"),
        purpose_id: id("purpose:memory"),
        memory_ledger_frontier: memory_frontier,
        knowledge_fact_frontier: 4,
        tombstone_frontier: 1,
        source_ledger_frontier: 7,
        knowledge_graph_generation: generation(2),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(3),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 2,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot: {error}"))
}

fn intent() -> LegacyMemoryWriteIntentV1 {
    LegacyMemoryWriteIntentV1 {
        intent_id: id("intent:1"),
        candidate_digest: digest("candidate"),
        expected_snapshot: snapshot(10),
        writer_fence_digest: digest("writer-fence"),
        authorization_digest: digest("authorization"),
    }
}

#[test]
fn committed_receipt_binds_full_intent_context() {
    let intent = intent();
    let legacy = LegacyMemoryWriteReceiptV1 {
        intent_id: intent.intent_id.clone(),
        record_id: id("record:1"),
        record_digest: digest("record"),
        committed_frontier: 11,
        snapshot_key: snapshot(11),
        disposition: LegacyMemoryWriteDisposition::Inserted,
        authority: AuthorityPosture::DENY_ALL,
    };
    let receipt = MemoryWriteReceiptV1::from_legacy_committed(
        &intent,
        "writer:cognitive-store",
        1_000,
        &legacy,
    )
    .unwrap_or_else(|error| panic!("valid committed receipt: {error}"));
    assert!(matches!(
        receipt.outcome(),
        MemoryWriteOutcomeV1::Committed { .. }
    ));

    let validated = Validated::from_cognitive_contract(receipt.clone())
        .unwrap_or_else(|error| panic!("validated receipt: {error}"));
    let legacy_digest = canonical_contract_digest_v1(&receipt)
        .unwrap_or_else(|error| panic!("legacy digest: {error}"));
    let domain_digest = validated
        .domain_bound_digest_v1()
        .unwrap_or_else(|error| panic!("domain digest: {error}"));
    assert_ne!(legacy_digest, domain_digest);
}

#[test]
fn rejected_receipt_has_no_fabricated_record_fields() {
    let receipt = MemoryWriteReceiptV1::rejected(
        &intent(),
        "writer:cognitive-store",
        1_000,
        MemoryWriteRejectionCodeV1::AuthorizationRejected,
        None,
        false,
    )
    .unwrap_or_else(|error| panic!("valid rejection receipt: {error}"));
    let encoded = serde_json::to_string(&receipt)
        .unwrap_or_else(|error| panic!("serialize rejection receipt: {error}"));
    assert!(encoded.contains("\"state\":\"rejected\""));
    assert!(!encoded.contains("recordId"));
    assert!(!encoded.contains("recordDigest"));
}

#[test]
fn registered_reader_accepts_known_receipt_and_rejects_unknown_schema() {
    let receipt = MemoryWriteReceiptV1::rejected(
        &intent(),
        "writer:cognitive-store",
        1_000,
        MemoryWriteRejectionCodeV1::SnapshotConflict,
        Some(digest("observed-snapshot")),
        true,
    )
    .unwrap_or_else(|error| panic!("valid rejection receipt: {error}"));
    let bytes = Validated::from_cognitive_contract(receipt.clone())
        .unwrap_or_else(|error| panic!("validated receipt: {error}"))
        .encode_wire_v1()
        .unwrap_or_else(|error| panic!("encode receipt: {error}"));
    let decoded = decode_registered_wire_v1::<MemoryWriteReceiptV1>(&bytes)
        .unwrap_or_else(|error| panic!("decode registered receipt: {error}"));
    assert_eq!(decoded, receipt);

    let mut envelope: serde_json::Value = serde_json::from_slice(&bytes)
        .unwrap_or_else(|error| panic!("decode envelope fixture: {error}"));
    envelope["schema"] = serde_json::Value::String("hepta.unknown.v1".to_string());
    let unknown = serde_json::to_vec(&envelope)
        .unwrap_or_else(|error| panic!("encode unknown envelope: {error}"));
    assert!(matches!(
        inspect_registered_envelope_v1(&unknown),
        Err(RegistryErrorV1::UnknownContract { .. })
    ));
}

#[test]
fn strict_synapse_validator_binds_relation_to_weight_sign() {
    let synapse = SynapseV1 {
        source_node_id: contract_id("node:source"),
        target_node_id: contract_id("node:target"),
        relation: SynapseRelationV1::Inhibitory,
        weight_q16: 1,
        delay_steps: 1,
        plasticity_class: PlasticityClassV1::Fixed,
        eligibility_ppm: 0,
        support_manifest_sha256: contract_digest("support"),
        snapshot_generation: contract_generation(1),
    };
    synapse
        .validate()
        .unwrap_or_else(|error| panic!("shape-valid synapse: {error}"));
    assert!(synapse.validate_strict_v1().is_err());
}

#[test]
fn selector_context_resolves_ast_gui_and_rfc6901_paths() {
    assert!(validate_json_pointer_v1("/a~1b/c~0d").is_ok());
    assert!(validate_json_pointer_v1("/bad~2escape").is_err());

    let manifest = AssetManifestV1 {
        asset_sha256: contract_digest("asset"),
        modality: ModalityKindV1::CodeAst,
        extent: AssetExtentV1::CodeAst,
        preprocessor_manifest_sha256: contract_digest("preprocessor"),
    };
    let ast_path = "module/item[0]".to_string();
    let context = SelectorResolutionContextV1::new(
        manifest,
        contract_digest("selector-index"),
        BTreeSet::from([ast_path.clone()]),
        BTreeSet::new(),
        BTreeSet::new(),
    )
    .unwrap_or_else(|error| panic!("valid selector context: {error}"));
    let span = ModalitySpanRefV1 {
        span_id: contract_id("span:1"),
        modality: ModalityKindV1::CodeAst,
        asset_sha256: contract_digest("asset"),
        range: SpanRangeV1::AstPath { path: ast_path },
        preprocessor_manifest_sha256: contract_digest("preprocessor"),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 0,
        privacy_class: PrivacyClassV1::AgentPrivate,
        redaction_mask_sha256: None,
    };
    context
        .validate_span(&span)
        .unwrap_or_else(|error| panic!("resolved selector: {error}"));

    let missing = ModalitySpanRefV1 {
        range: SpanRangeV1::AstPath {
            path: "module/missing".to_string(),
        },
        ..span
    };
    assert!(context.validate_span(&missing).is_err());
}
