use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

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

fn input(record: MemoryRecord, priority: u32) -> CompactionInputRecordV3 {
    input_with_footprint(record, priority, 32, 8)
}

fn input_with_footprint(
    record: MemoryRecord,
    priority: u32,
    encoded_bytes: u64,
    token_count: u64,
) -> CompactionInputRecordV3 {
    CompactionInputRecordV3 {
        retention_reason_digest: digest(&format!("reason:{}", record.record_id)),
        tokenization_receipt_digest: digest(&format!("tokens:{}", record.record_id)),
        record,
        retention_priority: priority,
        encoded_bytes,
        token_count,
    }
}

fn policy(maximum: u32, protected: Vec<StableId>) -> CompactionPolicyV3 {
    CompactionPolicyV3 {
        policy_id: id("policy:compact"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        tokenizer_digest: digest("tokenizer"),
        semantic_compactor_id: id("compactor:semantic"),
        semantic_compactor_implementation_digest: digest("semantic-implementation"),
        maximum_retained_records: maximum,
        maximum_retained_bytes: 4_096,
        maximum_retained_tokens: 1_024,
        protected_record_ids: protected,
    }
}

fn semantic_receipt(
    plan: &CompactionPlanV3,
    label: &str,
) -> SemanticCompactionReceiptV1 {
    SemanticCompactionReceiptV1::new(
        plan.policy.semantic_compactor_id.clone(),
        plan.policy.semantic_compactor_implementation_digest,
        plan.policy.tokenizer_digest,
        plan.support_manifest_digest,
        digest(label),
        plan.loss_report.retained_bytes.max(1),
        plan.loss_report.retained_tokens.max(1),
    )
    .unwrap_or_else(|error| panic!("valid semantic receipt: {error}"))
}

fn candidate(
    policy: &CompactionPolicyV3,
    inputs: Vec<CompactionInputRecordV3>,
) -> QualifiedCompactionCandidateV3 {
    let plan = plan_compaction(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        policy,
        inputs,
    )
    .unwrap_or_else(|error| panic!("valid plan: {error}"));
    let receipt = semantic_receipt(&plan, "semantic-output");
    build_qualified_candidate(plan, receipt)
        .unwrap_or_else(|error| panic!("valid candidate: {error}"))
}

fn evaluator() -> (TrustedCompactionEvaluatorV1, SigningKey) {
    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let evaluator = TrustedCompactionEvaluatorV1 {
        evaluator_id: id("evaluator:independent"),
        implementation_digest: digest("evaluator-implementation"),
        attestation_digest: digest("evaluator-attestation"),
        verifying_key: signing_key.verifying_key().to_bytes(),
    };
    (evaluator, signing_key)
}

fn signed_qualification(
    candidate: &QualifiedCompactionCandidateV3,
    evaluator: &TrustedCompactionEvaluatorV1,
    signing_key: &SigningKey,
) -> CompactionQualificationV3 {
    let mut qualification = CompactionQualificationV3 {
        evaluator_id: evaluator.evaluator_id.clone(),
        evaluator_implementation_digest: evaluator.implementation_digest,
        evaluator_attestation_digest: evaluator.attestation_digest,
        evaluation_artifact_digest: digest("evaluation-artifact"),
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
        signature: [0_u8; 64],
    };
    qualification.signature = signing_key
        .sign(&qualification.signing_bytes(candidate.candidate_digest))
        .to_bytes();
    qualification
}

#[test]
fn protected_live_reference_is_retained_before_higher_priority_optional_record() {
    let protected = record("memory:protected", 1, None, RecordState::Live);
    let optional = record("memory:optional", 1, None, RecordState::Live);
    let candidate = candidate(
        &policy(1, vec![id("memory:protected")]),
        vec![input(optional, 100), input(protected, 1)],
    );
    assert_eq!(candidate.retained_records.len(), 1);
    assert_eq!(
        candidate.retained_records[0].record_id,
        id("memory:protected")
    );
    assert_eq!(candidate.loss_report.protected_retained_records, 1);
    assert_eq!(candidate.loss_report.omitted_live_records, 1);
}

#[test]
fn tombstoned_head_is_never_retained() {
    let live = record("memory:deleted", 1, None, RecordState::Live);
    let tombstone = record(
        "memory:deleted",
        2,
        Some(live.record_digest()),
        RecordState::Tombstone,
    );
    let candidate = candidate(
        &policy(4, vec![id("memory:deleted")]),
        vec![input(live, 10), input(tombstone, 10)],
    );
    assert!(candidate.retained_records.is_empty());
    assert_eq!(candidate.loss_report.deleted_records, 1);
    assert_eq!(candidate.loss_report.protected_deleted_records, 1);
    assert_eq!(candidate.checkpoint.tombstone_cutoff, 6);
}

#[test]
fn live_tombstone_live_regression_is_rejected() {
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
        plan_compaction(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(4, Vec::new()),
            vec![
                input(live, 1),
                input(tombstone, 1),
                input(resurrected, 1)
            ],
        ),
        Err(QualifiedCompactionError::ResurrectionDenied(
            "memory:resurrected".to_string()
        ))
    );
}

#[test]
fn plan_and_candidate_are_order_independent() {
    let inputs = vec![
        input(record("memory:a", 1, None, RecordState::Live), 3),
        input(record("memory:b", 1, None, RecordState::Live), 2),
        input(record("memory:c", 1, None, RecordState::Live), 1),
    ];
    let mut reversed = inputs.clone();
    reversed.reverse();
    let profile = policy(2, Vec::new());
    let left_plan = plan_compaction(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &profile,
        inputs,
    )
    .expect("left plan");
    let right_plan = plan_compaction(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &profile,
        reversed,
    )
    .expect("right plan");
    assert_eq!(left_plan, right_plan);

    let left_receipt = semantic_receipt(&left_plan, "same-output");
    let right_receipt = semantic_receipt(&right_plan, "same-output");
    let left = build_qualified_candidate(left_plan, left_receipt).expect("left candidate");
    let right = build_qualified_candidate(right_plan, right_receipt).expect("right candidate");
    assert_eq!(left, right);
}

#[test]
fn record_byte_and_token_budgets_all_bound_selection() {
    let protected = input_with_footprint(
        record("memory:protected", 1, None, RecordState::Live),
        1,
        40,
        20,
    );
    let optional = input_with_footprint(
        record("memory:optional", 1, None, RecordState::Live),
        100,
        30,
        20,
    );
    let mut profile = policy(2, vec![id("memory:protected")]);
    profile.maximum_retained_bytes = 50;
    profile.maximum_retained_tokens = 30;
    let plan = plan_compaction(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &profile,
        vec![optional, protected],
    )
    .expect("budgeted plan");
    assert_eq!(plan.retained_inputs.len(), 1);
    assert_eq!(
        plan.retained_inputs[0].record.record_id,
        id("memory:protected")
    );
    assert_eq!(plan.loss_report.retained_bytes, 40);
    assert_eq!(plan.loss_report.omitted_live_bytes, 30);
    assert_eq!(plan.loss_report.retained_tokens, 20);
    assert_eq!(plan.loss_report.omitted_live_tokens, 20);
}

#[test]
fn protected_reference_cannot_overflow_byte_or_token_budget() {
    let protected = input_with_footprint(
        record("memory:protected", 1, None, RecordState::Live),
        1,
        20,
        12,
    );
    let mut profile = policy(1, vec![id("memory:protected")]);
    profile.maximum_retained_bytes = 10;
    profile.maximum_retained_tokens = 10;
    assert_eq!(
        plan_compaction(
            snapshot_key(),
            generation(2),
            None,
            &profile,
            vec![protected],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedBudget)
    );
}

#[test]
fn missing_protected_reference_fails_closed() {
    assert_eq!(
        plan_compaction(
            snapshot_key(),
            generation(2),
            None,
            &policy(2, vec![id("memory:missing")]),
            vec![input(
                record("memory:present", 1, None, RecordState::Live),
                1
            )],
        ),
        Err(QualifiedCompactionError::MissingProtectedReference(
            "memory:missing".to_string()
        ))
    );
}

#[test]
fn semantic_compactor_receipt_must_match_source_tokenizer_and_implementation() {
    let profile = policy(2, Vec::new());
    let plan = plan_compaction(
        snapshot_key(),
        generation(2),
        None,
        &profile,
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .expect("plan");
    let wrong = SemanticCompactionReceiptV1::new(
        profile.semantic_compactor_id.clone(),
        profile.semantic_compactor_implementation_digest,
        digest("wrong-tokenizer"),
        plan.support_manifest_digest,
        digest("summary"),
        10,
        2,
    )
    .expect("well-formed but wrong receipt");
    assert_eq!(
        build_qualified_candidate(plan, wrong),
        Err(QualifiedCompactionError::SemanticReceiptMismatch)
    );
}

#[test]
fn proof_requires_signed_independent_evaluator_and_binds_provenance() {
    let candidate = candidate(
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    );
    let (evaluator, signing_key) = evaluator();
    let qualification = signed_qualification(&candidate, &evaluator, &signing_key);
    let proof = prove_compaction(&candidate, &evaluator, qualification)
        .expect("valid signed proof");

    assert_eq!(
        proof.base_proof.checkpoint_digest,
        candidate.checkpoint.checkpoint_digest
    );
    assert_eq!(proof.evaluator_id, evaluator.evaluator_id);
    assert_eq!(
        proof.evaluator_implementation_digest,
        evaluator.implementation_digest
    );
    assert_eq!(
        proof.evaluator_attestation_digest,
        evaluator.attestation_digest
    );
    assert_eq!(proof.evaluator_key_digest, evaluator.key_digest());
    assert!(!proof.qualification_digest.is_zero());
    assert_eq!(proof.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn tampered_qualification_signature_is_rejected() {
    let candidate = candidate(
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    );
    let (evaluator, signing_key) = evaluator();
    let mut qualification = signed_qualification(&candidate, &evaluator, &signing_key);
    qualification.evaluation_artifact_digest = digest("tampered-artifact");
    assert_eq!(
        prove_compaction(&candidate, &evaluator, qualification),
        Err(QualifiedCompactionError::InvalidEvaluatorSignature)
    );
}

#[test]
fn failing_semantic_obligation_never_produces_proof() {
    let candidate = candidate(
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    );
    let (evaluator, signing_key) = evaluator();
    let mut qualification = signed_qualification(&candidate, &evaluator, &signing_key);
    qualification.deletion_non_resurrection_passed = false;
    qualification.signature = signing_key
        .sign(&qualification.signing_bytes(candidate.candidate_digest))
        .to_bytes();
    assert_eq!(
        prove_compaction(&candidate, &evaluator, qualification),
        Err(QualifiedCompactionError::DeletionNonResurrectionFailed)
    );
}

#[test]
fn protected_set_cannot_exceed_checkpoint_record_capacity() {
    let first = record("memory:a", 1, None, RecordState::Live);
    let second = record("memory:b", 1, None, RecordState::Live);
    assert_eq!(
        plan_compaction(
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
fn large_bounded_plan_remains_deterministic() {
    let mut inputs = (0_u32..4_096)
        .map(|index| {
            input_with_footprint(
                record(
                    &format!("memory:scale:{index:04}"),
                    1,
                    None,
                    RecordState::Live,
                ),
                index % 17,
                32,
                8,
            )
        })
        .collect::<Vec<_>>();
    let mut reversed = inputs.clone();
    reversed.reverse();

    let mut profile = policy(4_096, Vec::new());
    profile.maximum_retained_bytes = 4_096 * 32;
    profile.maximum_retained_tokens = 4_096 * 8;

    let left = plan_compaction(
        snapshot_key(),
        generation(2),
        None,
        &profile,
        std::mem::take(&mut inputs),
    )
    .expect("large plan");
    let right = plan_compaction(
        snapshot_key(),
        generation(2),
        None,
        &profile,
        reversed,
    )
    .expect("reversed large plan");

    assert_eq!(left.plan_digest, right.plan_digest);
    assert_eq!(left.retained_inputs.len(), 4_096);
    assert_eq!(left.loss_report.retained_bytes, 4_096 * 32);
    assert_eq!(left.loss_report.retained_tokens, 4_096 * 8);
}
