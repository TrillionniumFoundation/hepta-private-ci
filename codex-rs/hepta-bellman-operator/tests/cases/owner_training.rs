use super::*;
use codex_hepta_bellman_operator::MemoryTrainingError;
use codex_hepta_bellman_operator::MemoryTrainingObservationV1;
use codex_hepta_bellman_operator::MemoryTrainingProfileV1;
use codex_hepta_bellman_operator::MemoryTrainingSourceV1;
use codex_hepta_bellman_operator::StrictLearnedOperatorError;
use codex_hepta_bellman_operator::TerminalCellError;
use codex_hepta_bellman_operator::TerminalCellProfileV1;
use codex_hepta_bellman_operator::TerminalSupportedCellProfileV1;
use codex_hepta_bellman_operator::finish_memory_training_from_owner_v1;
use codex_hepta_bellman_operator::fit_terminal_cell_from_owner_v1;
use codex_hepta_bellman_operator::freeze_memory_training_from_owner_v1;
use codex_hepta_bellman_operator::freeze_supported_terminal_cells_from_owner_v1;
use codex_hepta_bellman_operator::freeze_terminal_cell_from_owner_v1;
use codex_hepta_bellman_operator::predict_tabular_operator_indexed_v2;

const NOW: u64 = 50;
const CONTENT: &str = "owner-authorized training observation";
const PAYLOAD: &[u8] = b"candidate payload binding fixture";

fn owner_dataset() -> TestResult<(Fixture, LedgerWriter, DatasetSnapshotReceiptV3, StableId)> {
    let fixture = Fixture::new()?;
    let mut owner = fixture.writer()?;
    let outcome = collect(&mut owner, "first", FixedQ32::ONE.raw())?;
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("owner-training-dataset")?,
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("policy"),
    };
    let signed = sign(
        owner.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&owner.snapshot()?, &plan)?,
    )?;
    let receipt = owner.freeze_dataset(plan, &signed, NOW)?;
    Ok((fixture, owner, receipt, outcome))
}

fn terminal_profile() -> TestResult<TerminalCellProfileV1> {
    Ok(TerminalCellProfileV1 {
        artifact_id: id("terminal-artifact")?,
        producer_id: id("terminal-producer")?,
        generation: Generation::new(1)?,
        sensor_id: id("terminal-sensor")?,
        objective_digest: digest("objective"),
        run_snapshot_digest: digest("first.run"),
        unit_profile_digest: digest("outcome-units"),
        action_ids: vec![id("first.selected")?],
        minimum_samples_per_action: 1,
    })
}

fn supported_profile() -> TestResult<TerminalSupportedCellProfileV1> {
    Ok(TerminalSupportedCellProfileV1 {
        cells: terminal_profile()?,
        candidate_ids: vec![id("abstain")?, id("first.selected")?],
    })
}

#[test]
fn supported_terminal_fit_preserves_owner_targets_and_abstains_outside_support() -> TestResult<()> {
    let (_fixture, owner, receipt, _) = owner_dataset()?;
    let frozen =
        freeze_supported_terminal_cells_from_owner_v1(&owner, &receipt, supported_profile()?, NOW)?;
    assert_eq!(frozen.dataset(), &receipt);
    assert_eq!(frozen.sample_count(), 1);
    let artifact = fit_terminal_cell_from_owner_v1(&owner, frozen, NOW)?;
    let prediction = predict_tabular_operator_indexed_v2(
        &artifact,
        &id("terminal-sensor")?,
        &id("first.selected")?,
    )?;
    assert_eq!(prediction.value, FixedQ32::ONE);
    assert!(!prediction.authority.grants_any());
    assert_eq!(
        predict_tabular_operator_indexed_v2(&artifact, &id("terminal-sensor")?, &id("abstain")?),
        Err(StrictLearnedOperatorError::UnsupportedCell),
    );

    let mut complete = terminal_profile()?;
    complete.action_ids.push(id("abstain")?);
    let frozen = freeze_terminal_cell_from_owner_v1(&owner, &receipt, complete, NOW)?;
    assert!(matches!(
        fit_terminal_cell_from_owner_v1(&owner, frozen, NOW),
        Err(TerminalCellError::Fit(StrictLearnedOperatorError::Learned(
            codex_hepta_bellman_operator::LearnedOperatorError::MissingCell { .. }
        )))
    ));
    Ok(())
}

#[test]
fn terminal_freeze_rejects_mismatched_units_grammar_and_insufficient_support() -> TestResult<()> {
    let (_fixture, owner, receipt, _) = owner_dataset()?;
    let original = supported_profile()?;
    let mut variants = Vec::new();
    let mut wrong_units = original.clone();
    wrong_units.cells.unit_profile_digest = digest("other-units");
    variants.push(wrong_units);
    let mut wrong_state = original.clone();
    wrong_state.cells.run_snapshot_digest = digest("other-run");
    variants.push(wrong_state);
    let mut insufficient = original.clone();
    insufficient.cells.minimum_samples_per_action = 2;
    variants.push(insufficient);
    let mut duplicate = original.clone();
    duplicate.cells.action_ids.push(id("first.selected")?);
    variants.push(duplicate);
    let mut missing_abstain = original.clone();
    missing_abstain
        .candidate_ids
        .retain(|value| value.as_str() != "abstain");
    variants.push(missing_abstain);
    let mut different_objective = original;
    different_objective.cells.objective_digest = digest("other-objective");
    variants.push(different_objective);
    for profile in variants {
        assert!(matches!(
            freeze_supported_terminal_cells_from_owner_v1(&owner, &receipt, profile, NOW),
            Err(TerminalCellError::Unsupported(_))
        ));
    }
    Ok(())
}

#[test]
fn owner_correction_invalidates_frozen_terminal_training() -> TestResult<()> {
    let (_fixture, mut owner, receipt, predecessor) = owner_dataset()?;
    let frozen =
        freeze_supported_terminal_cells_from_owner_v1(&owner, &receipt, supported_profile()?, NOW)?;
    append_correction(&mut owner, &predecessor)?;
    assert!(matches!(
        fit_terminal_cell_from_owner_v1(&owner, frozen, NOW),
        Err(TerminalCellError::Ledger(_))
    ));
    Ok(())
}

fn memory_profile() -> TestResult<MemoryTrainingProfileV1> {
    Ok(MemoryTrainingProfileV1 {
        job_id: id("memory-training-job")?,
        artifact_id: id("memory-artifact")?,
        producer_id: id("memory-producer")?,
        predecessor_generation: Generation::new(1)?,
        generation: Generation::new(2)?,
        objective_digest: digest("objective"),
        base_digest: digest("base"),
        encoder_digest: digest("encoder"),
        trainer_digest: digest("trainer"),
        scope_digest: digest("scope"),
        maximum_steps: 4,
        maximum_tokens_per_step: 16,
        maximum_payload_bytes: 1024,
        expires_at: 80,
    })
}

fn memory_source() -> MemoryTrainingSourceV1 {
    MemoryTrainingSourceV1 {
        support_digest: digest("first.support"),
        content_digest: digest(CONTENT),
        content: CONTENT.to_owned(),
    }
}

fn observation(
    job_digest: Digest32,
    profile: &MemoryTrainingProfileV1,
) -> MemoryTrainingObservationV1 {
    MemoryTrainingObservationV1 {
        job_digest,
        base_digest: profile.base_digest,
        frozen_base_after_digest: profile.base_digest,
        encoder_digest: profile.encoder_digest,
        trainer_digest: profile.trainer_digest,
        payload_digest: digest(PAYLOAD),
        payload_bytes: PAYLOAD.len() as u64,
        completed_steps: 2,
        consumed_tokens: 8,
        trainable_parameters: 16,
        changed_parameters: 4,
    }
}

#[test]
fn memory_candidate_binds_current_source_profile_and_exact_payload() -> TestResult<()> {
    let (_fixture, owner, receipt, _) = owner_dataset()?;
    let profile = memory_profile()?;
    let frozen = freeze_memory_training_from_owner_v1(
        &owner,
        &receipt,
        profile.clone(),
        memory_source(),
        NOW,
    )?;
    assert_eq!(frozen.profile(), &profile);
    assert_eq!(frozen.dataset(), &receipt);
    assert_eq!(frozen.source_text(), CONTENT);
    assert_eq!(frozen.source_support(), digest("first.support"));
    assert_eq!(frozen.content_digest(), digest(CONTENT));
    assert!(!frozen.job_digest().is_zero());
    assert!(!format!("{frozen:?}").contains(CONTENT));
    let mut changed_profile = profile.clone();
    changed_profile.maximum_steps += 1;
    let changed = freeze_memory_training_from_owner_v1(
        &owner,
        &receipt,
        changed_profile,
        memory_source(),
        NOW,
    )?;
    assert_ne!(changed.job_digest(), frozen.job_digest());
    let expected = observation(frozen.job_digest(), &profile);
    let candidate =
        finish_memory_training_from_owner_v1(&owner, frozen, expected.clone(), PAYLOAD, NOW)?;
    assert_eq!(candidate.observation(), &expected);
    assert_eq!(candidate.frozen().job_digest(), expected.job_digest);
    Ok(())
}

#[test]
fn memory_freeze_rejects_changed_source_and_invalid_generation() -> TestResult<()> {
    let (_fixture, owner, receipt, _) = owner_dataset()?;
    let mut changed_content = memory_source();
    changed_content.content.push_str(" altered");
    assert!(matches!(
        freeze_memory_training_from_owner_v1(
            &owner,
            &receipt,
            memory_profile()?,
            changed_content,
            NOW
        ),
        Err(MemoryTrainingError::Invalid(_))
    ));
    let mut changed_support = memory_source();
    changed_support.support_digest = digest("unrelated-owner-source");
    assert!(matches!(
        freeze_memory_training_from_owner_v1(
            &owner,
            &receipt,
            memory_profile()?,
            changed_support,
            NOW
        ),
        Err(MemoryTrainingError::Invalid(_))
    ));
    let mut skipped_generation = memory_profile()?;
    skipped_generation.generation = Generation::new(3)?;
    assert!(matches!(
        freeze_memory_training_from_owner_v1(
            &owner,
            &receipt,
            skipped_generation,
            memory_source(),
            NOW
        ),
        Err(MemoryTrainingError::Invalid(_))
    ));
    Ok(())
}

#[test]
fn memory_finish_rejects_payload_base_and_budget_drift() -> TestResult<()> {
    let (_fixture, owner, receipt, _) = owner_dataset()?;
    let profile = memory_profile()?;
    let frozen = freeze_memory_training_from_owner_v1(
        &owner,
        &receipt,
        profile.clone(),
        memory_source(),
        NOW,
    )?;
    let valid = observation(frozen.job_digest(), &profile);
    let mut variants = Vec::new();
    let mut changed_base = valid.clone();
    changed_base.frozen_base_after_digest = digest("modified-base");
    variants.push(changed_base);
    let mut changed_payload = valid.clone();
    changed_payload.payload_digest = digest("different-payload");
    variants.push(changed_payload);
    let mut excess_steps = valid.clone();
    excess_steps.completed_steps = profile.maximum_steps + 1;
    variants.push(excess_steps);
    let mut excess_tokens = valid.clone();
    excess_tokens.consumed_tokens =
        u64::from(valid.completed_steps * profile.maximum_tokens_per_step) + 1;
    variants.push(excess_tokens);
    let mut excess_changes = valid.clone();
    excess_changes.changed_parameters = valid.trainable_parameters + 1;
    variants.push(excess_changes);
    for result in variants {
        assert!(matches!(
            finish_memory_training_from_owner_v1(&owner, frozen.clone(), result, PAYLOAD, NOW),
            Err(MemoryTrainingError::Invalid(_))
        ));
    }
    assert!(matches!(
        finish_memory_training_from_owner_v1(&owner, frozen, valid, PAYLOAD, profile.expires_at),
        Err(MemoryTrainingError::Invalid(_))
    ));
    Ok(())
}

#[test]
fn memory_finish_revalidates_after_an_owner_correction() -> TestResult<()> {
    let (_fixture, mut owner, receipt, predecessor) = owner_dataset()?;
    let profile = memory_profile()?;
    let frozen = freeze_memory_training_from_owner_v1(
        &owner,
        &receipt,
        profile.clone(),
        memory_source(),
        NOW,
    )?;
    let observed = observation(frozen.job_digest(), &profile);
    append_correction(&mut owner, &predecessor)?;
    assert!(matches!(
        finish_memory_training_from_owner_v1(&owner, frozen, observed, PAYLOAD, NOW),
        Err(MemoryTrainingError::Ledger(_))
    ));
    Ok(())
}
