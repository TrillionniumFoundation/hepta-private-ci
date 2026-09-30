use super::*;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Revision;

use crate::MAX_COMPACTION_CITATIONS;

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

fn two_record_candidate() -> QualifiedCompactionCandidateV2 {
    build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(1, Vec::new()),
        vec![
            input(record("memory:a", 1, None, RecordState::Live), 2),
            input(record("memory:b", 1, None, RecordState::Live), 1),
        ],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"))
}

fn passing_qualification(candidate: &QualifiedCompactionCandidateV2) -> CompactionQualificationV2 {
    CompactionQualificationV2 {
        evaluator_id: id("evaluator:independent"),
        candidate_digest: candidate.candidate_digest,
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
    }
}

fn refresh_candidate_envelopes(candidate: &mut QualifiedCompactionCandidateV2) {
    candidate.loss_report.loss_report_digest = candidate.loss_report.compute_digest();
    candidate.checkpoint.checkpoint_digest = candidate.checkpoint.compute_checkpoint_digest();
    candidate.candidate_digest = candidate.compute_candidate_digest();
}

fn refresh_selection_manifests(candidate: &mut QualifiedCompactionCandidateV2) {
    let retained = candidate
        .retained_records
        .iter()
        .map(MemoryRecord::record_digest)
        .collect::<Vec<_>>();
    let mut supports = retained.clone();
    supports.extend_from_slice(&candidate.omitted_record_digests);
    supports.extend_from_slice(&candidate.deleted_record_digests);
    candidate.checkpoint.payload_digest = digest_digests(PAYLOAD_DOMAIN, &retained);
    candidate.checkpoint.omitted_information_digest =
        digest_digests(OMITTED_DOMAIN, &candidate.omitted_record_digests);
    candidate.checkpoint.support_manifest_digest =
        digest_digests(SUPPORT_MANIFEST_DOMAIN, &supports);
    refresh_candidate_envelopes(candidate);
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
        candidate_digest: candidate.candidate_digest,
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
fn changed_payload_cannot_validate_or_receive_the_original_checkpoint_proof() {
    let mut candidate = two_record_candidate();
    candidate.retained_records[0].content_digest = digest("substituted-content");
    candidate.candidate_digest = candidate.compute_candidate_digest();
    assert!(candidate.validate().is_err());
    assert!(prove_compaction(&candidate, passing_qualification(&candidate)).is_err());
}

#[test]
fn changed_omissions_cannot_keep_the_original_checkpoint() {
    let mut candidate = two_record_candidate();
    candidate.omitted_record_digests[0] = digest("substituted-omission");
    candidate.candidate_digest = candidate.compute_candidate_digest();
    assert!(candidate.validate().is_err());
}

#[test]
fn changed_support_manifest_is_rejected_even_with_recomputed_envelopes() {
    let mut candidate = two_record_candidate();
    candidate.checkpoint.support_manifest_digest = digest("unrelated-supports");
    refresh_candidate_envelopes(&mut candidate);
    assert!(candidate.validate().is_err());
}

#[test]
fn fabricated_loss_counts_cannot_receive_a_proof() {
    let mut candidate = two_record_candidate();
    candidate.loss_report.retained_records = 0;
    candidate.loss_report.omitted_live_records = 2;
    refresh_candidate_envelopes(&mut candidate);
    assert!(candidate.validate().is_err());
    assert!(prove_compaction(&candidate, passing_qualification(&candidate)).is_err());
}

#[test]
fn retained_and_omitted_sets_must_be_disjoint_even_with_matching_manifests() {
    let mut candidate = two_record_candidate();
    candidate.omitted_record_digests[0] = candidate.retained_records[0].record_digest();
    refresh_selection_manifests(&mut candidate);
    assert!(candidate.validate().is_err());
}

#[test]
fn omitted_set_cannot_repeat_a_source_head_even_with_matching_manifests() {
    let mut candidate = two_record_candidate();
    candidate
        .omitted_record_digests
        .push(candidate.omitted_record_digests[0]);
    candidate.loss_report.live_source_heads = 3;
    candidate.loss_report.source_current_heads = 3;
    candidate.loss_report.omitted_live_records = 2;
    refresh_selection_manifests(&mut candidate);
    assert!(candidate.validate().is_err());
}

#[test]
fn zero_omitted_digest_cannot_be_authenticated_by_recomputed_manifests() {
    let mut candidate = two_record_candidate();
    candidate.omitted_record_digests[0] = Digest32::ZERO;
    refresh_selection_manifests(&mut candidate);
    assert!(candidate.validate().is_err());
}

#[test]
fn checkpoint_deletion_cutoff_must_match_the_bound_source_snapshot() {
    let mut candidate = two_record_candidate();
    candidate.checkpoint.tombstone_cutoff += 1;
    refresh_candidate_envelopes(&mut candidate);
    assert!(candidate.validate().is_err());
}

#[test]
fn unknown_protected_reference_is_rejected_instead_of_silently_lost() {
    assert!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(1, vec![id("memory:absent")]),
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
        )
        .is_err()
    );
}

#[test]
fn protected_loss_counts_must_be_subsets_of_live_and_deleted_heads() {
    let base = two_record_candidate().loss_report;
    let mut excessive_live = base.clone();
    excessive_live.protected_live_records = 2;
    excessive_live.protected_retained_records = 2;
    excessive_live.loss_report_digest = excessive_live.compute_digest();
    assert!(excessive_live.validate().is_err());

    let mut excessive_deleted = base;
    excessive_deleted.protected_deleted_records = 1;
    excessive_deleted.loss_report_digest = excessive_deleted.compute_digest();
    assert!(excessive_deleted.validate().is_err());
}

#[test]
fn overflowing_loss_counts_are_rejected_without_panicking() {
    let base = two_record_candidate().loss_report;
    let mut head_overflow = base.clone();
    head_overflow.source_current_heads = 0;
    head_overflow.live_source_heads = u64::MAX;
    head_overflow.deleted_records = 1;
    head_overflow.retained_records = u64::MAX;
    head_overflow.omitted_live_records = 0;

    let mut selection_overflow = base.clone();
    selection_overflow.source_current_heads = u64::MAX;
    selection_overflow.live_source_heads = u64::MAX;
    selection_overflow.deleted_records = 0;
    selection_overflow.retained_records = u64::MAX;
    selection_overflow.omitted_live_records = 1;

    let mut protected_overflow = base;
    protected_overflow.protected_live_records = u64::MAX;
    protected_overflow.protected_retained_records = u64::MAX;
    protected_overflow.protected_deleted_records = 1;

    for mut report in [head_overflow, selection_overflow, protected_overflow] {
        report.loss_report_digest = report.compute_digest();
        let outcome = std::panic::catch_unwind(|| report.validate());
        assert!(outcome.is_ok(), "untrusted counts must not panic");
        assert!(outcome.is_ok_and(|result| result.is_err()));
    }
}

#[test]
fn imported_candidate_cannot_exceed_the_input_budget() {
    let mut candidate = two_record_candidate();
    candidate.omitted_record_digests = (0..MAX_QUALIFIED_COMPACTION_INPUTS)
        .map(|value| Digest32::of_bytes(&value.to_be_bytes()))
        .collect();
    candidate.loss_report.omitted_live_records = MAX_QUALIFIED_COMPACTION_INPUTS as u64;
    candidate.loss_report.live_source_heads = MAX_QUALIFIED_COMPACTION_INPUTS as u64 + 1;
    candidate.loss_report.source_current_heads = candidate.loss_report.live_source_heads;
    refresh_selection_manifests(&mut candidate);
    assert!(candidate.validate().is_err());
}

#[test]
fn deleted_source_lineage_remains_bound_after_all_live_payload_is_removed() {
    let first = record("memory:deleted", 1, None, RecordState::Live);
    let deleted = record(
        "memory:deleted",
        2,
        Some(first.record_digest()),
        RecordState::Tombstone,
    );
    let mut different_first = first.clone();
    different_first.content_digest = digest("different-original-content");
    let different_deleted = record(
        "memory:deleted",
        2,
        Some(different_first.record_digest()),
        RecordState::Tombstone,
    );
    let build = |live, tombstone| {
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(1, Vec::new()),
            vec![input(live, 1), input(tombstone, 1)],
        )
        .unwrap_or_else(|error| panic!("valid deleted candidate: {error}"))
    };
    let left = build(first, deleted.clone());
    let right = build(different_first, different_deleted);
    assert!(left.retained_records.is_empty());
    assert_eq!(left.deleted_record_digests, vec![deleted.record_digest()]);
    assert_eq!(left.loss_report, right.loss_report);
    assert_ne!(
        left.checkpoint.support_manifest_digest,
        right.checkpoint.support_manifest_digest
    );
    assert_ne!(left.candidate_digest, right.candidate_digest);

    let mut forged = left;
    forged.deleted_record_digests[0] = digest("unrelated-tombstone");
    forged.candidate_digest = forged.compute_candidate_digest();
    assert!(forged.validate().is_err());
}

#[test]
fn live_payload_cannot_also_be_counted_as_a_deleted_head() {
    let mut candidate = two_record_candidate();
    candidate
        .deleted_record_digests
        .push(candidate.retained_records[0].record_digest());
    candidate.loss_report.deleted_records = 1;
    candidate.loss_report.source_current_heads += 1;
    refresh_selection_manifests(&mut candidate);
    assert!(candidate.validate().is_err());
}

#[test]
fn observations_for_one_candidate_cannot_prove_a_different_selection() {
    let left = two_record_candidate();
    let right = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(1, Vec::new()),
        vec![
            input(record("memory:a", 1, None, RecordState::Live), 1),
            input(record("memory:b", 1, None, RecordState::Live), 2),
        ],
    )
    .unwrap_or_else(|error| panic!("valid alternate candidate: {error}"));
    let observations = passing_qualification(&left);
    assert!(prove_compaction(&left, observations.clone()).is_ok());
    assert!(prove_compaction(&right, observations).is_err());
}

#[test]
fn selection_reasons_and_priorities_remain_auditable_when_payload_is_unchanged() {
    let first = input(record("memory:a", 1, None, RecordState::Live), 1);
    let build = |input| {
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(1, Vec::new()),
            vec![input],
        )
        .unwrap_or_else(|error| panic!("valid candidate: {error}"))
    };
    let original = build(first.clone());
    let mut changed_reason = first.clone();
    changed_reason.retention_reason_digest = digest("different-retention-reason");
    let reason_candidate = build(changed_reason);
    let mut changed_priority = first;
    changed_priority.retention_priority = 99;
    let priority_candidate = build(changed_priority);

    assert_eq!(original.retained_records, reason_candidate.retained_records);
    assert_eq!(
        original.retained_records,
        priority_candidate.retained_records
    );
    assert_ne!(original.candidate_digest, reason_candidate.candidate_digest);
    assert_ne!(
        original.candidate_digest,
        priority_candidate.candidate_digest
    );
}

#[test]
fn checkpoint_identity_cannot_be_replaced_by_an_arbitrary_or_legacy_identity() {
    for identity in ["compact:2", "compact:unrelated"] {
        let mut candidate = two_record_candidate();
        candidate.checkpoint.checkpoint_id = id(identity);
        refresh_candidate_envelopes(&mut candidate);
        assert!(candidate.validate().is_err());
    }
}

#[test]
fn checkpoint_identity_distinguishes_snapshots_with_the_same_generation() {
    let first = two_record_candidate();
    let mut different_vector = snapshot_key().vector;
    different_vector.scope_id = id("scope:different");
    let different_snapshot = CognitiveSnapshotKeyV1::new(different_vector)
        .unwrap_or_else(|error| panic!("valid alternate snapshot: {error}"));
    let second = build_qualified_candidate(
        different_snapshot,
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(1, Vec::new()),
        vec![
            input(record("memory:a", 1, None, RecordState::Live), 2),
            input(record("memory:b", 1, None, RecordState::Live), 1),
        ],
    )
    .unwrap_or_else(|error| panic!("valid alternate candidate: {error}"));
    assert_eq!(first.checkpoint.generation, second.checkpoint.generation);
    assert_ne!(
        first.checkpoint.checkpoint_id,
        second.checkpoint.checkpoint_id
    );
}

#[test]
fn frozen_inputs_validate_in_any_order_and_reject_semantic_drift() {
    let candidate = two_record_candidate();
    let frozen_policy = policy(1, Vec::new());
    let inputs = vec![
        input(record("memory:a", 1, None, RecordState::Live), 2),
        input(record("memory:b", 1, None, RecordState::Live), 1),
    ];
    assert_eq!(
        candidate.validate_against_inputs(&frozen_policy, inputs.clone()),
        Ok(())
    );
    let mut reversed = inputs.clone();
    reversed.reverse();
    assert_eq!(
        candidate.validate_against_inputs(&frozen_policy, reversed),
        Ok(())
    );

    let mut changed_policy = frozen_policy.clone();
    changed_policy.policy_id = id("policy:different");
    assert!(
        candidate
            .validate_against_inputs(&changed_policy, inputs.clone())
            .is_err()
    );
    let mut changed_priority = inputs.clone();
    changed_priority[0].retention_priority = 0;
    let mut changed_reason = inputs.clone();
    changed_reason[0].retention_reason_digest = digest("different-reason");
    let mut changed_record = inputs;
    changed_record[0].record.content_digest = digest("different-source-content");
    for changed in [changed_priority, changed_reason, changed_record] {
        assert!(
            candidate
                .validate_against_inputs(&frozen_policy, changed)
                .is_err()
        );
    }
}

#[test]
fn frozen_validation_accepts_semantically_identical_citation_order() {
    let mut source_record = record("memory:a", 1, None, RecordState::Live);
    source_record.citations = vec![
        Citation {
            source_id: id("source:a"),
            source_digest: digest("source-a"),
        },
        Citation {
            source_id: id("source:b"),
            source_digest: digest("source-b"),
        },
    ];
    let frozen_policy = policy(1, Vec::new());
    let mut source_input = input(source_record, 1);
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &frozen_policy,
        vec![source_input.clone()],
    )
    .unwrap_or_else(|error| panic!("valid cited candidate: {error}"));
    source_input.record.citations.reverse();
    assert_eq!(
        candidate.validate_against_inputs(&frozen_policy, vec![source_input]),
        Ok(())
    );
}

fn citation_budget_inputs(count: usize) -> Vec<CompactionInputRecordV2> {
    let citations = (0..64)
        .map(|value| Citation {
            source_id: id(&format!("source:{value}")),
            source_digest: digest("source-support"),
        })
        .collect::<Vec<_>>();
    (0..count)
        .map(|value| {
            let mut record = record(&format!("memory:{value}"), 1, None, RecordState::Live);
            record.citations = citations.clone();
            input(record, 1)
        })
        .collect()
}

fn encoded_byte_boundary_inputs() -> Vec<CompactionInputRecordV2> {
    let full_id = |prefix: String| {
        let suffix = "x".repeat(128 - prefix.len());
        id(&format!("{prefix}{suffix}"))
    };
    let citations = (0..64)
        .map(|value| Citation {
            source_id: full_id(format!("source:{value}")),
            source_digest: digest("source-support"),
        })
        .collect::<Vec<_>>();
    let mut inputs = (0..30_146)
        .map(|value| {
            let mut record = record("memory:temporary", 1, None, RecordState::Live);
            record.record_id = full_id(format!("memory:{value}"));
            if value < 1_024 {
                record.citations = citations.clone();
            }
            input(record, 1)
        })
        .collect::<Vec<_>>();
    // V1 records with a 128-byte ID and no predecessor encode to 200 bytes;
    // each 128-byte citation ID adds 164 bytes. The final 40-byte ID adds 112:
    // 30,146*200 + 1,024*64*164 + 112 = 16,777,216, exactly 16 MiB.
    inputs.push(input(
        record(
            "memory:extraXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
            1,
            None,
            RecordState::Live,
        ),
        1,
    ));
    inputs
}

#[test]
fn both_builders_accept_the_aggregate_citation_boundary() {
    let inputs = citation_budget_inputs(MAX_COMPACTION_CITATIONS / 64);
    assert!(
        crate::compact(
            generation(2),
            digest("snapshot"),
            inputs.iter().map(|input| input.record.clone()).collect(),
        )
        .is_ok()
    );
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(2_048, Vec::new()),
        inputs,
    )
    .unwrap_or_else(|error| panic!("citation boundary must succeed: {error}"));
    assert!(candidate.validate().is_ok());
}

#[test]
fn aggregate_citation_overflow_is_rejected_before_record_validation() {
    let mut inputs = citation_budget_inputs(MAX_COMPACTION_CITATIONS / 64 + 1);
    inputs[0].record.content_digest = Digest32::ZERO;
    let expected = CompactionResourceError::CitationLimitExceeded;
    assert_eq!(
        crate::compact(
            generation(2),
            digest("snapshot"),
            inputs.iter().map(|input| input.record.clone()).collect(),
        ),
        Err(crate::Error::ResourceBudgetExceeded(expected))
    );
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(2_048, Vec::new()),
            inputs,
        ),
        Err(QualifiedCompactionError::ResourceBudgetExceeded(expected))
    );
}

#[test]
fn both_builders_accept_exactly_the_encoded_byte_boundary() {
    let inputs = encoded_byte_boundary_inputs();
    assert!(
        crate::compact(
            generation(2),
            digest("snapshot"),
            inputs.iter().map(|input| input.record.clone()).collect(),
        )
        .is_ok()
    );
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(32_768, Vec::new()),
        inputs,
    )
    .unwrap_or_else(|error| panic!("encoded byte boundary must succeed: {error}"));
    assert!(candidate.validate().is_ok());
}

#[test]
fn both_builders_reject_one_byte_over_the_encoded_boundary() {
    let mut inputs = encoded_byte_boundary_inputs();
    let last = inputs
        .last_mut()
        .unwrap_or_else(|| panic!("boundary has a final record"));
    last.record.record_id = id("memory:extraXXXXXXXXXXXXXXXXXXXXXXXXXXXXX");
    let expected = CompactionResourceError::EncodedByteLimitExceeded;
    assert_eq!(
        crate::compact(
            generation(2),
            digest("snapshot"),
            inputs.iter().map(|input| input.record.clone()).collect(),
        ),
        Err(crate::Error::ResourceBudgetExceeded(expected))
    );
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(32_768, Vec::new()),
            inputs,
        ),
        Err(QualifiedCompactionError::ResourceBudgetExceeded(expected))
    );
}

#[test]
fn imported_candidate_citation_budget_precedes_loss_and_digest_checks() {
    let mut candidate = two_record_candidate();
    candidate.retained_records = citation_budget_inputs(MAX_COMPACTION_CITATIONS / 64 + 1)
        .into_iter()
        .map(|input| input.record)
        .collect();
    assert_eq!(
        candidate.validate(),
        Err(QualifiedCompactionError::ResourceBudgetExceeded(
            CompactionResourceError::CitationLimitExceeded
        ))
    );
}

#[test]
fn imported_candidate_counts_digest_references_in_its_byte_budget() {
    let mut candidate = two_record_candidate();
    candidate.retained_records = encoded_byte_boundary_inputs()
        .into_iter()
        .map(|input| input.record)
        .collect();
    // The retained payload is exactly 16 MiB; the existing omitted reference
    // contributes another 32 bytes before any loss accounting or rehashing.
    assert_eq!(
        candidate.validate(),
        Err(QualifiedCompactionError::ResourceBudgetExceeded(
            CompactionResourceError::EncodedByteLimitExceeded
        ))
    );
}

#[test]
fn omitted_and_deleted_vectors_share_one_head_budget() {
    let mut candidate = two_record_candidate();
    candidate.omitted_record_digests = vec![Digest32::ZERO; MAX_QUALIFIED_COMPACTION_INPUTS / 2];
    candidate.deleted_record_digests = vec![Digest32::ZERO; MAX_QUALIFIED_COMPACTION_INPUTS / 2];
    assert_eq!(
        candidate.validate(),
        Err(QualifiedCompactionError::InputLimitExceeded)
    );
}
