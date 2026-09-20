use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::CompactionInputRecordV3;
use codex_hepta_compact_engine::CompactionPlanV3;
use codex_hepta_compact_engine::CompactionPolicyV3;
use codex_hepta_compact_engine::CompactionQualificationV3;
use codex_hepta_compact_engine::QualifiedCompactionCandidateV3;
use codex_hepta_compact_engine::SemanticCompactionReceiptV1;
use codex_hepta_compact_engine::TrustedCompactionEvaluatorV1;
use codex_hepta_compact_engine::build_qualified_candidate;
use codex_hepta_compact_engine::plan_compaction;
use codex_hepta_compact_engine::prove_compaction;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sqlx::Executor;
use tempfile::TempDir;

use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

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

fn snapshot_key(compact_generation: u64) -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:production-compact"),
        purpose_id: id("purpose:production-compaction"),
        memory_ledger_frontier: 20,
        knowledge_fact_frontier: 14,
        tombstone_frontier: 6,
        source_ledger_frontier: 21,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(compact_generation),
        prompt_registry_revision: revision(4),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 8,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .expect("snapshot")
}

fn record(record_id: &str) -> MemoryRecord {
    MemoryRecord {
        record_id: id(record_id),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content:{record_id}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn input(record_id: &str, priority: u32) -> CompactionInputRecordV3 {
    CompactionInputRecordV3 {
        record: record(record_id),
        retention_priority: priority,
        retention_reason_digest: digest(&format!("reason:{record_id}")),
        encoded_bytes: 64,
        token_count: 16,
        tokenization_receipt_digest: digest(&format!("tokens:{record_id}")),
    }
}

fn policy() -> CompactionPolicyV3 {
    CompactionPolicyV3 {
        policy_id: id("policy:production-compact"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        tokenizer_digest: digest("tokenizer"),
        semantic_compactor_id: id("compactor:production"),
        semantic_compactor_implementation_digest: digest("semantic-implementation"),
        maximum_retained_records: 32,
        maximum_retained_bytes: 16_384,
        maximum_retained_tokens: 4_096,
        protected_record_ids: Vec::new(),
    }
}

fn semantic_receipt(
    plan: &CompactionPlanV3,
    output_label: &str,
) -> SemanticCompactionReceiptV1 {
    SemanticCompactionReceiptV1::new(
        plan.policy.semantic_compactor_id.clone(),
        plan.policy.semantic_compactor_implementation_digest,
        plan.policy.tokenizer_digest,
        plan.support_manifest_digest,
        digest(output_label),
        plan.loss_report.retained_bytes.max(1),
        plan.loss_report.retained_tokens.max(1),
    )
    .expect("semantic receipt")
}

fn evaluator() -> (TrustedCompactionEvaluatorV1, SigningKey) {
    let signing = SigningKey::from_bytes(&[41_u8; 32]);
    (
        TrustedCompactionEvaluatorV1 {
            evaluator_id: id("evaluator:production-compact"),
            implementation_digest: digest("evaluator-implementation"),
            attestation_digest: digest("evaluator-attestation"),
            verifying_key: signing.verifying_key().to_bytes(),
        },
        signing,
    )
}

fn candidate(
    compact_generation: u64,
    generation_value: u64,
    predecessor: Option<Digest32>,
    output_label: &str,
) -> QualifiedCompactionCandidateV3 {
    let plan = plan_compaction(
        snapshot_key(compact_generation),
        generation(generation_value),
        predecessor,
        &policy(),
        vec![input("memory:a", 2), input("memory:b", 1)],
    )
    .expect("plan");
    let receipt = semantic_receipt(&plan, output_label);
    build_qualified_candidate(plan, receipt).expect("candidate")
}

fn proof(
    candidate: &QualifiedCompactionCandidateV3,
) -> codex_hepta_compact_engine::CompactionProofV2 {
    let (evaluator, signing) = evaluator();
    let mut qualification = CompactionQualificationV3 {
        evaluator_id: evaluator.evaluator_id.clone(),
        evaluator_implementation_digest: evaluator.implementation_digest,
        evaluator_attestation_digest: evaluator.attestation_digest,
        evaluation_artifact_digest: digest("evaluation-artifact"),
        retained_query_suite_digest: digest("retained-query-suite"),
        reconstruction_obligation_digest: digest("reconstruction-obligation"),
        contradiction_holdout_digest: digest("contradiction-holdout"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
        signature: [0_u8; 64],
    };
    qualification.signature = signing
        .sign(&qualification.signing_bytes(candidate.candidate_digest))
        .to_bytes();
    prove_compaction(candidate, &evaluator, qualification).expect("proof")
}

fn fence(generation_value: u64, label: &str) -> ProductionCompactFenceV1 {
    ProductionCompactFenceV1::new(
        8,
        3,
        generation(generation_value),
        digest(label),
    )
    .expect("fence")
}

#[tokio::test]
async fn engine_to_owner_publish_reopen_and_reload_round_trip() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(241);
    let agent_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&agent_layout).await.expect("open");

    let candidate = candidate(1, 2, None, "summary:g2");
    let proof = proof(&candidate);
    let receipt = store
        .publish_production_compact_checkpoint(
            id("operation:compact:g2"),
            &candidate.checkpoint,
            &proof,
            &fence(2, "fence:g2"),
        )
        .await
        .expect("publish");
    assert_eq!(
        receipt.disposition,
        ProductionCompactPublishDisposition::Published
    );
    assert!(!receipt.receipt_digest.is_zero());

    drop(store);
    let reopened = CognitiveStore::open(&agent_layout).await.expect("reopen");
    let loaded = reopened
        .load_production_compact_checkpoint(&id("scope:production-compact"))
        .await
        .expect("load")
        .expect("checkpoint exists");
    assert_eq!(loaded.checkpoint, candidate.checkpoint);
    assert_eq!(loaded.proof, proof);
    assert_eq!(loaded.event_digest, receipt.event_digest);

    let replay = reopened
        .publish_production_compact_checkpoint(
            id("operation:compact:g2"),
            &loaded.checkpoint,
            &loaded.proof,
            &fence(2, "fence:g2"),
        )
        .await
        .expect("idempotent replay");
    assert_eq!(replay.disposition, ProductionCompactPublishDisposition::Replay);
    assert_eq!(replay.sequence, receipt.sequence);
}

#[tokio::test]
async fn crash_before_commit_retains_predecessor_after_reopen() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(242);
    let agent_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&agent_layout).await.expect("open");

    let first = candidate(1, 2, None, "summary:g2");
    let first_proof = proof(&first);
    store
        .publish_production_compact_checkpoint(
            id("operation:compact:g2"),
            &first.checkpoint,
            &first_proof,
            &fence(2, "fence:g2"),
        )
        .await
        .expect("first publish");

    let second = candidate(
        2,
        3,
        Some(first.checkpoint.checkpoint_digest),
        "summary:g3",
    );
    let second_proof = proof(&second);
    let error = store
        .publish_production_compact_checkpoint_crash_before_commit(
            id("operation:compact:g3"),
            &second.checkpoint,
            &second_proof,
            &fence(3, "fence:g3"),
        )
        .await
        .expect_err("fault must abort");
    assert_eq!(error, ProductionCompactError::FaultInjected);

    drop(store);
    let reopened = CognitiveStore::open(&agent_layout).await.expect("reopen");
    let loaded = reopened
        .load_production_compact_checkpoint(&id("scope:production-compact"))
        .await
        .expect("load")
        .expect("checkpoint");
    assert_eq!(
        loaded.checkpoint.checkpoint_digest,
        first.checkpoint.checkpoint_digest
    );
    assert_eq!(loaded.checkpoint.generation, generation(2));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_successors_enforce_single_cas_winner() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(243);
    let agent_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&agent_layout).await.expect("open");

    let first = candidate(1, 2, None, "summary:g2");
    let first_proof = proof(&first);
    store
        .publish_production_compact_checkpoint(
            id("operation:compact:g2"),
            &first.checkpoint,
            &first_proof,
            &fence(2, "fence:g2"),
        )
        .await
        .expect("first publish");

    let left = candidate(
        2,
        3,
        Some(first.checkpoint.checkpoint_digest),
        "summary:g3:left",
    );
    let left_proof = proof(&left);
    let right = candidate(
        2,
        3,
        Some(first.checkpoint.checkpoint_digest),
        "summary:g3:right",
    );
    let right_proof = proof(&right);

    let left_store = store.clone();
    let right_store = store.clone();
    let left_task = tokio::spawn(async move {
        left_store
            .publish_production_compact_checkpoint(
                id("operation:compact:g3:left"),
                &left.checkpoint,
                &left_proof,
                &fence(3, "fence:g3:left"),
            )
            .await
    });
    let right_task = tokio::spawn(async move {
        right_store
            .publish_production_compact_checkpoint(
                id("operation:compact:g3:right"),
                &right.checkpoint,
                &right_proof,
                &fence(3, "fence:g3:right"),
            )
            .await
    });
    let outcomes = [
        left_task.await.expect("left task"),
        right_task.await.expect("right task"),
    ];
    let successes = outcomes.iter().filter(|outcome| outcome.is_ok()).count();
    let conflicts = outcomes
        .iter()
        .filter(|outcome| matches!(outcome, Err(ProductionCompactError::Conflict(_))))
        .count();
    assert_eq!(successes, 1);
    assert_eq!(conflicts, 1);
}

#[tokio::test]
async fn forged_sqlite_event_is_rejected_as_corrupt_on_reload() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(244);
    let agent_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&agent_layout).await.expect("open");

    let first = candidate(1, 2, None, "summary:g2");
    let first_proof = proof(&first);
    let first_receipt = store
        .publish_production_compact_checkpoint(
            id("operation:compact:g2"),
            &first.checkpoint,
            &first_proof,
            &fence(2, "fence:g2"),
        )
        .await
        .expect("publish");

    let journal_id = format!(
        "{}:{}",
        PRODUCTION_COMPACT_OWNER_NAMESPACE,
        "scope:production-compact"
    );
    let forged = digest("forged-event");
    store
        .pool
        .execute(
            sqlx::query(
                "INSERT INTO cognitive_compact_events (
                    journal_id, owner_agent_id, sequence, generation, fencing_token,
                    event_json, previous_sha256, event_sha256, recorded_at_unix_seconds,
                    authority_epoch, owner_epoch
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(journal_id)
            .bind(owner.as_str())
            .bind(2_i64)
            .bind(3_i64)
            .bind(digest("fence:g3").to_string())
            .bind("{}")
            .bind(first_receipt.event_digest.to_string())
            .bind(forged.to_string())
            .bind(1_i64)
            .bind(8_i64)
            .bind(3_i64),
        )
        .await
        .expect("insert forged row");

    let error = store
        .load_production_compact_checkpoint(&id("scope:production-compact"))
        .await
        .expect_err("corruption must fail closed");
    assert!(matches!(
        error,
        ProductionCompactError::Serialization(_) | ProductionCompactError::Corrupt(_)
    ));
}
