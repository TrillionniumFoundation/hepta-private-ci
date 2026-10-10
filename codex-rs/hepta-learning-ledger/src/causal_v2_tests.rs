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

fn actor(name: &str, credential: &str, key: &str) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(credential),
        signing_key_digest: digest(key),
        scope_digest: digest(&format!("scope-{name}")),
        authority_epoch: 7,
        authenticated_at: 10,
        expires_at: 100,
    }
}

#[test]
fn ledger_03_rejects_shared_credential_chain() {
    let generator = actor("generator", "shared-credential", "generator-key");
    let observer = actor("observer", "shared-credential", "observer-key");
    assert_eq!(
        verify_independent_roles(&generator, &observer, 50),
        Err(CausalV2Error::RoleCollision("credential chain"))
    );
}

#[test]
fn ledger_04_validates_terminal_watermark_and_correction_lineage() {
    let generator = actor("generator", "generator-credential", "generator-key");
    let observer = actor("observer", "observer-credential", "observer-key");
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("record-outcome-1"),
        outcome_id: id("outcome-1"),
        episode_id: id("episode-1"),
        observer,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(3 << 30)),
        unit_profile_digest: digest("reward-unit-v1"),
        support_digest: digest("observer-evidence"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay-profile"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: Some(id("outcome-0")),
            finalized_at: Some(46),
        },
    };
    let receipt = validate_authenticated_outcome(&generator, &outcome, 50);
    assert!(receipt.is_ok());

    let mut invalid = outcome;
    invalid.value = None;
    assert_eq!(
        validate_authenticated_outcome(&generator, &invalid, 50),
        Err(CausalV2Error::OutcomeStateMismatch)
    );
}

#[test]
fn ledger_credit_batch_enforces_conservation() {
    let batch = CreditAllocationBatchV1 {
        batch_id: id("credit-batch-1"),
        episode_id: id("episode-1"),
        outcome_id: id("outcome-1"),
        allocator: actor("allocator", "allocator-credential", "allocator-key"),
        terminal_outcome: FixedQ32::from_raw(100),
        allocations: vec![
            CreditAllocationV1 {
                target_id: id("artifact-b"),
                credit: FixedQ32::from_raw(30),
            },
            CreditAllocationV1 {
                target_id: id("artifact-a"),
                credit: FixedQ32::from_raw(60),
            },
        ],
        conservation_residual: FixedQ32::from_raw(10),
        support_digest: digest("credit-support"),
        finalized: true,
    };
    let receipt = match finalize_credit_batch(batch.clone(), 50) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid conserved batch failed: {error}"),
    };
    assert_eq!(receipt.allocation_count, 2);
    assert!(!receipt.batch_digest.is_zero());
    assert!(!receipt.authority.grants_any());

    let mut invalid = batch;
    invalid.conservation_residual = FixedQ32::from_raw(9);
    assert_eq!(
        finalize_credit_batch(invalid, 50),
        Err(CausalV2Error::CreditConservation)
    );
}

#[test]
fn ledger_candidate_receipt_binds_generator_relative_completeness() {
    let receipt = CandidateSetCompletenessReceiptV1 {
        set_id: id("set-1"),
        state_digest: digest("state"),
        generator_id: id("generator-v1"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: digest("grammar"),
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: digest("candidates"),
        candidate_count: 16,
        omitted_count_bound: 4,
        canonical_order_digest: digest("order"),
        complete_for_generator: true,
    };
    assert!(validate_candidate_set_completeness(&receipt).is_ok());

    let mut incomplete = receipt;
    incomplete.complete_for_generator = false;
    assert_eq!(
        validate_candidate_set_completeness(&incomplete),
        Err(CausalV2Error::IncompleteCandidateSet)
    );
}

#[test]
fn ledger_dataset_freeze_is_order_independent_and_rejects_duplicates() {
    let first = digest("record-a");
    let second = digest("record-b");
    let request = DatasetFreezeRequestV1 {
        snapshot_id: id("dataset-1"),
        producer: actor("dataset-owner", "dataset-credential", "dataset-key"),
        ledger_head_digest: digest("ledger-head"),
        objective_digest: digest("objective"),
        eligible_frontier: 12,
        outcome_watermark: 40,
        correction_cut_digest: digest("correction-cut"),
        revocation_cut_digest: digest("revocation-cut"),
        inclusion_policy_digest: digest("inclusion-policy"),
        source_record_digests: vec![second, first],
        pending_outcomes: 2,
        censored_outcomes: 1,
    };
    let ordered = match freeze_dataset(request.clone(), 50) {
        Ok(snapshot) => snapshot,
        Err(error) => panic!("valid dataset freeze failed: {error}"),
    };
    let mut reversed = request.clone();
    reversed.source_record_digests.reverse();
    let reversed = match freeze_dataset(reversed, 50) {
        Ok(snapshot) => snapshot,
        Err(error) => panic!("reordered dataset freeze failed: {error}"),
    };
    assert_eq!(ordered.dataset_digest, reversed.dataset_digest);
    let mut expected = vec![first, second];
    expected.sort_unstable();
    assert_eq!(ordered.source_record_digests, expected);

    let mut duplicate = request;
    duplicate.source_record_digests = vec![first, first];
    assert_eq!(
        freeze_dataset(duplicate, 50),
        Err(CausalV2Error::DuplicateSourceRecord)
    );
}
