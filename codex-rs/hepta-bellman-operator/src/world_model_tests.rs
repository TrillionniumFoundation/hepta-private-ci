use super::*;

fn id(value: &str) -> StableId {
    match StableId::new(value.to_owned()) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sample(name: &str, next: &str, outcome: i64) -> WorldModelSampleV1 {
    WorldModelSampleV1 {
        sample_id: id(name),
        state_id: id("state-a"),
        action_id: id("action-a"),
        next_state_id: id(next),
        outcome: FixedQ32::from_raw(outcome),
        evidence_digest: digest(&format!("evidence-{name}")),
    }
}

#[test]
fn op_04_transition_model_is_action_conditioned_and_probability_exact() {
    let model = match fit_transition_model(
        id("world-model-1"),
        digest("dataset"),
        vec![
            sample("sample-3", "state-c", 30),
            sample("sample-1", "state-b", 10),
            sample("sample-2", "state-b", 20),
        ],
    ) {
        Ok(model) => model,
        Err(error) => panic!("valid transition model failed: {error}"),
    };
    assert_eq!(model.estimates.len(), 1);
    let estimate = &model.estimates[0];
    assert_eq!(estimate.sample_count, 3);
    assert_eq!(estimate.mean_outcome, FixedQ32::from_raw(20));
    assert_eq!(estimate.branches.len(), 2);
    assert_eq!(estimate.branches[0].next_state_id, id("state-b"));
    assert_eq!(estimate.branches[0].count, 2);
    assert_eq!(estimate.branches[0].probability.raw(), 2_863_311_531);
    assert_eq!(estimate.branches[1].next_state_id, id("state-c"));
    assert_eq!(estimate.branches[1].count, 1);
    assert_eq!(estimate.branches[1].probability.raw(), 1_431_655_765);
    assert_eq!(
        estimate
            .branches
            .iter()
            .map(|branch| branch.probability.raw())
            .sum::<u64>(),
        ProbabilityQ32::ONE.raw()
    );
    assert!(!model.authority.grants_any());
}

#[test]
fn op_04_prediction_is_synthetic_and_unsupported_pairs_abstain() {
    let model = match fit_transition_model(
        id("world-model-1"),
        digest("dataset"),
        vec![sample("sample-1", "state-b", 10)],
    ) {
        Ok(model) => model,
        Err(error) => panic!("valid transition model failed: {error}"),
    };
    let prediction = match predict_transition(&model, &id("state-a"), &id("action-a")) {
        Ok(prediction) => prediction,
        Err(error) => panic!("supported prediction failed: {error}"),
    };
    assert!(prediction.synthetic);
    assert!(!prediction.authority.grants_any());
    assert_eq!(
        predict_transition(&model, &id("state-unknown"), &id("action-a")),
        Err(WorldModelError::UnsupportedStateAction)
    );
}

#[test]
fn world_model_rejects_duplicate_samples_and_invalid_outcomes() {
    let duplicate = sample("sample-1", "state-b", 10);
    assert_eq!(
        fit_transition_model(
            id("world-model-1"),
            digest("dataset"),
            vec![duplicate.clone(), duplicate],
        ),
        Err(WorldModelError::DuplicateSample("sample-1".to_owned()))
    );

    let invalid = sample("sample-2", "state-b", FixedQ32::ONE.raw() + 1);
    assert_eq!(
        fit_transition_model(id("world-model-2"), digest("dataset"), vec![invalid],),
        Err(WorldModelError::InvalidOutcome)
    );
}

#[test]
fn op_05_world_model_rejects_relabelled_duplicate_evidence() {
    let first = sample("sample-1", "state-b", 10);
    let mut relabelled = sample("sample-2", "state-c", 20);
    relabelled.evidence_digest = first.evidence_digest;
    assert_eq!(
        fit_transition_model(
            id("world-model-duplicate-evidence"),
            digest("dataset"),
            vec![first, relabelled],
        ),
        Err(WorldModelError::DuplicateEvidence)
    );
}

#[test]
fn op_05_world_model_dataset_receipt_binds_rows() {
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
    use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;

    let receipt = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("world-model-snapshot"),
            producer: AuthenticatedPrincipalV1 {
                principal_id: id("dataset-owner"),
                credential_chain_digest: digest("dataset-credential"),
                signing_key_digest: digest("dataset-key"),
                scope_digest: digest("dataset-scope"),
                authority_epoch: 4,
                authenticated_at: 10,
                expires_at: 100,
            },
            ledger_head_digest: digest("ledger-head"),
            objective_digest: digest("objective"),
            eligible_frontier: 2,
            outcome_watermark: 40,
            correction_cut_digest: digest("correction-cut"),
            revocation_cut_digest: digest("revocation-cut"),
            inclusion_policy_digest: digest("inclusion-policy"),
            source_record_digests: vec![
                digest("evidence-sample-1"),
                digest("evidence-sample-2"),
            ],
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        50,
    )
    .expect("frozen dataset");

    let rows = vec![
        sample("sample-1", "state-b", 10),
        sample("sample-2", "state-c", 20),
    ];
    let model = fit_transition_model_from_dataset_receipt_v3(
        id("world-model-bound"),
        &receipt,
        rows.clone(),
        50,
    )
    .expect("bound world model");
    assert_eq!(model.dataset_digest, receipt.snapshot.dataset_digest);

    let mut detached = rows;
    detached[1].evidence_digest = digest("detached-evidence");
    assert_eq!(
        fit_transition_model_from_dataset_receipt_v3(
            id("world-model-detached"),
            &receipt,
            detached,
            50,
        ),
        Err(WorldModelError::EvidenceOutsideDataset)
    );
}

