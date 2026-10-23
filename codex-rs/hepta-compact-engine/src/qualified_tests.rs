use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::hnmf::MemoryScopeV1;
use codex_hepta_cognitive_types::hnmf::MemoryVerificationStateV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
use codex_hepta_cognitive_types::hnmf::ObservedIntervalV1;
use codex_hepta_cognitive_types::hnmf::PrivacyClassV1;
use codex_hepta_cognitive_types::hnmf::ProvenanceRefV1;
use codex_hepta_cognitive_types::hnmf::RetentionPolicyV1;
use codex_hepta_cognitive_types::hnmf::SpanRangeV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:compact"),
        purpose_id: id("purpose:consolidation"),
        memory_ledger_frontier: 20,
        knowledge_fact_frontier: 14,
        tombstone_frontier: 6,
        source_ledger_frontier: 21,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(4),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 8,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot key: {error}"))
}

fn record(
    record_id: &str,
    revision_value: u64,
    predecessor_digest: Option<Digest32>,
    state: RecordState,
) -> MemoryRecord {
    MemoryRecord {
        record_id: id(record_id),
        revision: revision(revision_value),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("{record_id}:{revision_value}:{state:?}")),
        predecessor_digest,
        citations: Vec::new(),
        state,
    }
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("contract id")
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value)).expect("contract digest")
}

fn canonical_event_for(record: &MemoryRecord) -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: contract_id(&format!(
            "event:{}:{}",
            record.record_id,
            record.revision.get()
        )),
        episode_id: contract_id("episode:compaction"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: contract_id("agent:compaction"),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: record.revision.get(),
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: contract_id(&format!("span:{}", record.revision.get())),
            modality: ModalityKindV1::Text,
            asset_sha256: contract_digest("asset"),
            range: SpanRangeV1::ByteRange { start: 0, end: 1 },
            preprocessor_manifest_sha256: contract_digest("preprocessor"),
            feature_blob_sha256: None,
            symbolic_projection_sha256: None,
            uncertainty_ppm: 0,
            privacy_class: PrivacyClassV1::AgentPrivate,
            redaction_mask_sha256: None,
        }],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from(["compaction".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: contract_id("source:compaction"),
            source_revision: record.revision.get(),
            source_sha256: contract_digest("source"),
            observed_at_unix_ms: record.revision.get(),
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
        lifecycle: match record.state {
            RecordState::Live => MemoryLifecycleV1::Active,
            RecordState::Tombstone => MemoryLifecycleV1::Tombstoned {
                reason_sha256: contract_digest("tombstone"),
            },
        },
    }
}

fn input(record: MemoryRecord, priority: u32) -> CompactionInputRecordV2 {
    CompactionInputRecordV2 {
        retention_reason_digest: digest(&format!("reason:{}", record.record_id)),
        record,
        retention_priority: priority,
    }
}

fn policy(maximum: u32, protected: Vec<StableId>) -> CompactionPolicyV2 {
    CompactionPolicyV2 {
        policy_id: id("policy:compact"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        maximum_retained_records: maximum,
        protected_record_ids: protected,
    }
}

#[test]
fn protected_live_reference_is_retained_before_higher_priority_optional_record() {
    let protected = record("memory:protected", 1, None, RecordState::Live);
    let optional = record("memory:optional", 1, None, RecordState::Live);
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(1, vec![id("memory:protected")]),
        vec![input(optional, 100), input(protected, 1)],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    assert_eq!(candidate.retained_records.len(), 1);
    assert_eq!(
        candidate.retained_records[0].record_id,
        id("memory:protected")
    );
    assert_eq!(candidate.loss_report.protected_retained_records, 1);
    assert_eq!(candidate.loss_report.omitted_live_records, 1);
}

#[test]
fn tombstoned_head_is_never_replayed_or_retained() {
    let live = record("memory:deleted", 1, None, RecordState::Live);
    let tombstone = record(
        "memory:deleted",
        2,
        Some(live.record_digest()),
        RecordState::Tombstone,
    );
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(4, vec![id("memory:deleted")]),
        vec![input(live, 10), input(tombstone, 10)],
    )
    .unwrap_or_else(|error| panic!("valid deleted candidate: {error}"));
    assert!(candidate.retained_records.is_empty());
    assert_eq!(candidate.loss_report.deleted_records, 1);
    assert_eq!(candidate.loss_report.protected_deleted_records, 1);
    assert_eq!(candidate.checkpoint.tombstone_cutoff, 6);
}

#[test]
fn explicit_resurrection_after_tombstone_is_rejected() {
    let live = record("memory:resurrected", 1, None, RecordState::Live);
    let tombstone = record(
        "memory:resurrected",
        2,
        Some(live.record_digest()),
        RecordState::Tombstone,
    );
    let resurrected = record(
        "memory:resurrected",
        3,
        Some(tombstone.record_digest()),
        RecordState::Live,
    );
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(4, Vec::new()),
            vec![input(live, 1), input(tombstone, 1), input(resurrected, 1)],
        ),
        Err(QualifiedCompactionError::ResurrectionDenied(
            "memory:resurrected".to_string()
        ))
    );
}

#[test]
fn candidate_is_order_independent() {
    let inputs = vec![
        input(record("memory:a", 1, None, RecordState::Live), 3),
        input(record("memory:b", 1, None, RecordState::Live), 2),
        input(record("memory:c", 1, None, RecordState::Live), 1),
    ];
    let mut reversed = inputs.clone();
    reversed.reverse();
    let left = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(2, Vec::new()),
        inputs,
    )
    .unwrap_or_else(|error| panic!("valid left candidate: {error}"));
    let right = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(2, Vec::new()),
        reversed,
    )
    .unwrap_or_else(|error| panic!("valid right candidate: {error}"));
    assert_eq!(left, right);
}

#[test]
fn proof_requires_all_loss_and_deletion_obligations() {
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    let qualification = CompactionQualificationV2 {
        evaluator_id: id("evaluator:independent"),
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
    };
    let proof = prove_compaction(&candidate, qualification.clone())
        .unwrap_or_else(|error| panic!("valid proof: {error}"));
    assert_eq!(
        proof.checkpoint_digest,
        candidate.checkpoint.checkpoint_digest
    );
    assert_eq!(proof.authority, AuthorityPosture::DENY_ALL);

    let mut failed = qualification;
    failed.deletion_non_resurrection_passed = false;
    assert_eq!(
        prove_compaction(&candidate, failed),
        Err(QualifiedCompactionError::DeletionNonResurrectionFailed)
    );
}

#[test]
fn protected_set_cannot_exceed_checkpoint_capacity() {
    let first = record("memory:a", 1, None, RecordState::Live);
    let second = record("memory:b", 1, None, RecordState::Live);
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(1, vec![id("memory:a"), id("memory:b")]),
            vec![input(first, 1), input(second, 1)],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity)
    );
}

#[test]
fn canonical_compaction_entry_binds_every_legacy_revision_to_one_event() {
    let snapshot = snapshot_key();
    let mut record = record("memory:canonical", 1, None, RecordState::Live);
    record
        .citations
        .push(codex_hepta_cognitive_types::Citation {
            source_id: id("source:compaction"),
            source_digest: digest("source"),
        });
    let canonical = bind_canonical_compaction_input_v1(
        contract_id("operation:compact"),
        &snapshot,
        input(record.clone(), 10),
        canonical_event_for(&record),
    )
    .expect("canonical input");
    let product = build_qualified_candidate_with_canonical_events(
        snapshot,
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(1, Vec::new()),
        vec![canonical],
    )
    .expect("canonical candidate");
    product.validate().expect("canonical candidate validates");
    assert_eq!(product.input_bindings.len(), 1);
    assert!(product.input_bindings[0].currentness_revalidation_required);
    let mut removed = product.clone();
    removed.input_bindings.clear();
    assert!(
        removed.validate().is_err(),
        "missing canonical coverage cannot validate"
    );
    let mut replaced = product;
    replaced.inputs[0].input.retention_priority += 1;
    assert!(
        replaced.validate().is_err(),
        "priority belongs to the exact input binding"
    );
}
