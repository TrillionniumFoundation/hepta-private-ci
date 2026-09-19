use super::*;

use codex_hepta_types::ProbabilityQ32;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn decision(index: usize) -> LedgerEvent {
    LedgerEvent::AuthenticatedDecisionV2(crate::AuthenticatedDecisionRecordV2 {
        record_id: id(&format!("decision-record-{index:05}")),
        episode_id: id(&format!("episode-{index:05}")),
        run_snapshot_digest: digest(&format!("run-{index}")),
        objective_digest: digest("objective"),
        policy_digest: digest("policy"),
        generator_id: id("generator"),
        generator_controller_id: id("generator-controller"),
        generator_credential_chain_digest: digest("generator-credential"),
        generator_signing_key_digest: digest("generator-key"),
        generator_scope_digest: digest("scope"),
        generator_authority_epoch: 7,
        candidate_ids: vec![id("action"), id("abstain")],
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        candidate_completeness_digest: digest("complete"),
        support_digest: digest("decision-support"),
        authentication_digest: digest("decision-auth"),
    })
}

#[test]
fn checkpoint_is_content_addressed_and_supports_binary_lookup() {
    let mut ledger = LearningLedger::new();
    for index in 0..4096 {
        ledger.append(decision(index)).unwrap();
    }
    let snapshot = ledger.snapshot();
    let checkpoint = build_ledger_index_checkpoint(&snapshot).unwrap();
    verify_ledger_index_checkpoint(&snapshot, &checkpoint).unwrap();

    assert_eq!(checkpoint.record_count, 4096);
    assert_eq!(checkpoint.active_record_count, 4096);
    assert_eq!(
        checkpoint
            .lookup(&id("decision-record-02048"))
            .unwrap()
            .sequence,
        2049
    );

    let mut tampered = checkpoint.clone();
    tampered.entries[0].active = false;
    assert_eq!(
        verify_ledger_index_checkpoint(&snapshot, &tampered),
        Err(LedgerCheckpointError::DigestMismatch)
    );
}

#[test]
fn checkpoint_revocation_frontier_changes_without_rewriting_history() {
    let mut ledger = LearningLedger::new();
    ledger.append(decision(0)).unwrap();
    let before = build_ledger_index_checkpoint(&ledger.snapshot()).unwrap();
    ledger
        .append(LedgerEvent::UnlearningLineageV1(
            crate::UnlearningLineageEventV1 {
                record_id: id("unlearning-record"),
                lineage_id: id("unlearning-lineage"),
                source_record_id: id("decision-record-00000"),
                dataset_snapshot_id: id("dataset"),
                artifact_id: id("artifact"),
                authority_id: id("privacy-owner"),
                reason_digest: digest("withdrawal"),
                authentication_digest: digest("unlearning-auth"),
            },
        ))
        .unwrap();
    let after = build_ledger_index_checkpoint(&ledger.snapshot()).unwrap();

    assert_ne!(
        before.revocation_frontier_digest,
        after.revocation_frontier_digest
    );
    assert_eq!(after.active_record_count, 1);
    assert!(!after.lookup(&id("decision-record-00000")).unwrap().active);
}
