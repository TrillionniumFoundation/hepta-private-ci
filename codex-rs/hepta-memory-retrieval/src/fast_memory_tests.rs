use super::*;
use crate::RecallAbstentionReasonV1;
use crate::RecallDispositionV1;
use crate::RetrievalChannelV1;
use crate::RetrievalChannelWeightV1;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn config() -> FastMemoryConfigV1 {
    FastMemoryConfigV1 {
        owner_id: id("owner:one"),
        state_id: id("state:one"),
        base_model_digest: digest("frozen-base"),
        adapter_digest: digest("no-adapter"),
        key_width: 2,
        value_width: 2,
        learning_rate: 1.0,
        decay: 1.0,
    }
}
fn snapshot() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:private"),
        purpose_id: id("purpose:recall"),
        memory_ledger_frontier: 5,
        knowledge_fact_frontier: 5,
        tombstone_frontier: 1,
        source_ledger_frontier: 5,
        knowledge_graph_generation: Generation::new(1).expect("generation"),
        compact_checkpoint_generation: Generation::new(1).expect("generation"),
        prompt_registry_revision: Revision::new(1).expect("revision"),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 1,
        model_digest: digest("selected-model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
    })
    .expect("snapshot")
}
fn trained() -> FastMemoryV1 {
    let mut memory = FastMemoryV1::new(config(), snapshot()).expect("new");
    memory
        .update(
            &snapshot(),
            memory.state_digest(),
            &[1.0, 0.0],
            &[0.0, 1.0],
            digest("eligible-support"),
        )
        .expect("update");
    memory
}

#[test]
fn online_delta_changes_private_state_while_frozen_identity_is_unchanged() {
    let blank = FastMemoryV1::new(config(), snapshot()).expect("new");
    let memory = trained();
    assert_eq!(
        blank
            .predict(&snapshot(), &[1.0, 0.0])
            .expect("prediction")
            .values,
        vec![0.0, 0.0]
    );
    assert_eq!(
        memory
            .predict(&snapshot(), &[1.0, 0.0])
            .expect("prediction"),
        FastMemoryPredictionV1 {
            values: vec![0.0, 1.0],
            state_digest: memory.state_digest(),
            scalar_multiplications: 4,
            authority: AuthorityPosture::DENY_ALL,
        }
    );
    assert_eq!(
        (&memory.config, &memory.snapshot),
        (&blank.config, &blank.snapshot)
    );
    assert_ne!(memory.state_digest(), blank.state_digest());
}

#[test]
fn restoration_requires_exact_current_anchor_owner_scope_and_model() {
    let memory = trained();
    let bytes = memory.checkpoint();
    let anchor = memory.state_digest();
    assert_eq!(
        FastMemoryV1::restore(config(), snapshot(), &bytes, anchor).expect("restore"),
        memory
    );
    let mut configurations = vec![config(); 5];
    configurations[0].owner_id = id("owner:other");
    configurations[1].base_model_digest = digest("different-base");
    configurations[2].adapter_digest = digest("different-adapter");
    configurations[3].state_id = id("state:other");
    configurations[4].learning_rate = 0.5;
    for candidate in configurations {
        assert_eq!(
            FastMemoryV1::restore(candidate, snapshot(), &bytes, anchor),
            Err(FastMemoryErrorV1::InvalidCheckpoint)
        );
    }
    let mut changed = snapshot().vector;
    changed.scope_id = id("scope:other");
    let changed = CognitiveSnapshotKeyV1::new(changed).expect("snapshot");
    assert_eq!(
        FastMemoryV1::restore(config(), changed, &bytes, anchor),
        Err(FastMemoryErrorV1::InvalidCheckpoint)
    );
    let old = FastMemoryV1::new(config(), snapshot())
        .expect("new")
        .checkpoint();
    assert_eq!(
        FastMemoryV1::restore(config(), snapshot(), &old, anchor),
        Err(FastMemoryErrorV1::InvalidCheckpoint)
    );
    let mut corrupt = bytes.clone();
    corrupt[HEADER_BYTES] ^= 1;
    for invalid in [&corrupt[..], &bytes[..bytes.len() - 1]] {
        assert_eq!(
            FastMemoryV1::restore(config(), snapshot(), invalid, anchor),
            Err(FastMemoryErrorV1::InvalidCheckpoint)
        );
    }
}

#[test]
fn invalid_updates_leave_state_unchanged_and_stale_retries_do_not_learn_twice() {
    let mut memory = trained();
    let before = memory.clone();
    for key in [
        &[f64::NAN, 0.0][..],
        &[f64::INFINITY, 0.0],
        &[2.0, 0.0],
        &[1.0],
    ] {
        assert_eq!(
            memory.update(
                &snapshot(),
                before.state_digest(),
                key,
                &[1.0, 0.0],
                digest("support")
            ),
            Err(FastMemoryErrorV1::InvalidVector)
        );
    }
    assert_eq!(
        memory.update(
            &snapshot(),
            before.state_digest(),
            &[1.0, 0.0],
            &[f64::NAN, 0.0],
            digest("support")
        ),
        Err(FastMemoryErrorV1::InvalidVector)
    );
    assert_eq!(
        memory.update(
            &snapshot(),
            before.state_digest(),
            &[1.0, 0.0],
            &[1.0, 0.0],
            Digest32::ZERO
        ),
        Err(FastMemoryErrorV1::InvalidSupport)
    );
    assert_eq!(
        memory.update(
            &snapshot(),
            digest("stale-anchor"),
            &[1.0, 0.0],
            &[1.0, 0.0],
            digest("support")
        ),
        Err(FastMemoryErrorV1::StaleState)
    );
    assert_eq!(memory, before);
}

#[test]
fn source_or_permission_drift_requires_new_empty_state_and_rejects_old_restore() {
    let memory = trained();
    let mut changed = snapshot().vector;
    changed.tombstone_frontier += 1;
    changed.authority_epoch += 1;
    let current = CognitiveSnapshotKeyV1::new(changed).expect("current");
    assert_eq!(
        memory.predict(&current, &[1.0, 0.0]),
        Err(FastMemoryErrorV1::SnapshotMismatch)
    );
    assert_eq!(
        FastMemoryV1::restore(
            config(),
            current.clone(),
            &memory.checkpoint(),
            memory.state_digest()
        ),
        Err(FastMemoryErrorV1::InvalidCheckpoint)
    );
    assert_eq!(
        memory.reset(current.clone(), config().state_id),
        Err(FastMemoryErrorV1::InvalidReset)
    );
    let reset = memory
        .reset(current.clone(), id("state:reset"))
        .expect("reset");
    assert_eq!(
        reset
            .predict(&current, &[1.0, 0.0])
            .expect("prediction")
            .values,
        vec![0.0, 0.0]
    );
    assert_eq!(reset.predecessor, memory.state_digest());
    assert_eq!(
        reset.reset(snapshot(), id("state:rollback")),
        Err(FastMemoryErrorV1::InvalidReset)
    );
    let mut new_config = config();
    new_config.state_id = id("state:reset");
    assert_eq!(
        FastMemoryV1::restore(
            new_config,
            current,
            &reset.checkpoint(),
            reset.state_digest()
        )
        .expect("reset restore"),
        reset
    );
    let mut changed = snapshot().vector;
    changed.encoder_preprocessor_digest = digest("new-encoder");
    assert_eq!(
        memory.reset(
            CognitiveSnapshotKeyV1::new(changed).expect("snapshot"),
            id("state:migrate")
        ),
        Err(FastMemoryErrorV1::InvalidReset)
    );
}

#[test]
fn reset_cannot_regress_individual_graph_compaction_or_registry_generations() {
    let mut current = snapshot().vector;
    current.knowledge_graph_generation = Generation::new(2).expect("generation");
    current.compact_checkpoint_generation = Generation::new(2).expect("generation");
    current.prompt_registry_revision = Revision::new(2).expect("revision");
    let memory = FastMemoryV1::new(
        config(),
        CognitiveSnapshotKeyV1::new(current.clone()).expect("snapshot"),
    )
    .expect("new");
    let mut regressions = vec![current; 3];
    regressions[0].knowledge_graph_generation = Generation::new(1).expect("generation");
    regressions[1].compact_checkpoint_generation = Generation::new(1).expect("generation");
    regressions[2].prompt_registry_revision = Revision::new(1).expect("revision");
    for regression in regressions {
        assert_eq!(
            memory.reset(
                CognitiveSnapshotKeyV1::new(regression).expect("snapshot"),
                id("state:regressed")
            ),
            Err(FastMemoryErrorV1::InvalidReset)
        );
    }
}

fn recall_input() -> (MemoryCueV1, RetrievalPolicyV1, Vec<FastMemoryCandidateV1>) {
    let cue = MemoryCueV1 {
        cue_id: id("cue:one"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("context"),
        request_digest: digest("request"),
        snapshot_key: snapshot(),
        cue_profile_digest: digest("cue-profile"),
    };
    let policy = RetrievalPolicyV1 {
        policy_id: id("policy:one"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 2,
        }],
        maximum_results: 2,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    };
    let candidates = (1..=2)
        .map(|number| FastMemoryCandidateV1 {
            features: if number == 1 {
                vec![1.0, 0.0]
            } else {
                vec![0.0, 1.0]
            },
            candidate: RetrievalChannelCandidateV1 {
                record: MemoryRecord {
                    record_id: id(&format!("memory:{number}")),
                    revision: Revision::new(1).expect("revision"),
                    kind: MemoryKind::Fact,
                    content_digest: digest(&format!("content:{number}")),
                    predecessor_digest: None,
                    citations: vec![],
                    state: RecordState::Live,
                },
                channel: RetrievalChannelV1::Lexical,
                channel_rank: number,
                normalized_score: FixedQ32::ONE,
                ood: ProbabilityQ32::ZERO,
                support_digest: digest("source-support"),
                contradiction_group_digest: None,
                generation_vector_digest: snapshot().vector_digest,
            },
        })
        .collect();
    (cue, policy, candidates)
}

#[test]
fn associations_only_permute_eligible_results_and_preserve_abstention() {
    let (cue, mut policy, mut candidates) = recall_input();
    let memory = trained();
    let ranked = memory
        .rerank(&cue, &policy, &[1.0, 0.0], &candidates)
        .expect("rerank");
    assert_eq!(
        ranked
            .ranked
            .iter()
            .map(|row| row.identity.record_id.clone())
            .collect::<Vec<_>>(),
        vec![id("memory:2"), id("memory:1")]
    );
    assert_eq!(ranked.base_recall.selections[0].record_id, id("memory:1"));
    policy.maximum_results = 1;
    let limited = memory
        .rerank(&cue, &policy, &[1.0, 0.0], &candidates)
        .expect("limited");
    assert_eq!(
        limited
            .ranked
            .iter()
            .map(|row| row.identity.record_id.clone())
            .collect::<Vec<_>>(),
        vec![id("memory:1")]
    );
    for row in &mut candidates {
        row.candidate.contradiction_group_digest = Some(digest("contradiction"));
    }
    let abstained = memory
        .rerank(&cue, &policy, &[1.0, 0.0], &candidates)
        .expect("abstained");
    assert_eq!(
        (
            abstained.base_recall.disposition,
            abstained.ranked,
            abstained.authority
        ),
        (
            RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence),
            vec![],
            AuthorityPosture::DENY_ALL
        )
    );
}

#[test]
fn stale_or_deleted_candidates_and_changed_duplicate_features_are_rejected() {
    let (cue, policy, mut candidates) = recall_input();
    let memory = trained();
    candidates[0].candidate.generation_vector_digest = digest("old-generation");
    assert!(matches!(
        memory.rerank(&cue, &policy, &[1.0, 0.0], &candidates),
        Err(FastMemoryErrorV1::Recall(_))
    ));
    candidates[0].candidate.generation_vector_digest = snapshot().vector_digest;
    candidates[0].candidate.record.state = RecordState::Tombstone;
    assert!(matches!(
        memory.rerank(&cue, &policy, &[1.0, 0.0], &candidates),
        Err(FastMemoryErrorV1::Recall(_))
    ));
    candidates[0].candidate.record.state = RecordState::Live;
    let mut conflicting = candidates[0].clone();
    conflicting.features = vec![0.0, 1.0];
    candidates.push(conflicting);
    assert_eq!(
        memory.rerank(&cue, &policy, &[1.0, 0.0], &candidates),
        Err(FastMemoryErrorV1::CandidateFeatures)
    );
}
