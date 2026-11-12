use pretty_assertions::assert_eq;

use super::*;

fn source() -> OriginalHoldoutSourceData {
    OriginalHoldoutSourceData {
        schema: 1,
        purpose: "runtime.learning.independent-b-source.v1".into(),
        objective: [1; 32],
        unit_profile: [2; 32],
        candidate_bundle: [3; 32],
        baseline_bundle: [4; 32],
        original_dataset: [5; 32],
        registered_at_seconds: 20,
        collected_after_seconds: 30,
        training: vec![TrainingRow {
            decision_id: "training-decision".into(),
            principal_lineage: "training-principal".into(),
            episode_lineage: "training-episode".into(),
            window_id: "training-window".into(),
            action_id: "left".into(),
            outcome_q32: FixedQ32::ONE.raw(),
            observed_at_seconds: 10,
            original_evidence: [6; 32],
        }],
        heldout: vec![HeldoutRow {
            decision_id: "heldout-decision".into(),
            principal_lineage: "heldout-principal".into(),
            episode_lineage: "heldout-episode".into(),
            window_id: "heldout-window".into(),
            cluster_id: "heldout-cluster".into(),
            decision_at_seconds: 40,
            complete_candidates: true,
            chosen_action: "left".into(),
            actions: vec![OriginalPolicyAction {
                action_id: "left".into(),
                behavior_probability_q32: ProbabilityQ32::ONE.raw(),
                candidate_probability_q32: ProbabilityQ32::ONE.raw(),
                baseline_probability_q32: ProbabilityQ32::ONE.raw(),
            }],
            finalized_outcome_q32: FixedQ32::ONE.raw() / 4,
            observed_at_seconds: 50,
            original_outcome_evidence: [7; 32],
        }],
        snapshot_ids: vec!["original-snapshot".into()],
        future_window_ids: vec!["heldout-window".into()],
    }
}

#[test]
fn independent_b_source_preserves_original_units_and_policy_probabilities() -> io::Result<()> {
    let original = source();
    let bytes = serde_json::to_vec(&original)?;
    let decoded = OriginalHoldoutSourceData::decode(&bytes)?;
    let inputs = decoded.inputs()?;
    assert_eq!(inputs.training[0].outcome, FixedQ32::ONE);
    let row = &inputs.candidate_observations[0];
    assert_eq!(
        row.finalized_outcome,
        Some(FixedQ32::from_raw(FixedQ32::ONE.raw() / 4))
    );
    assert_eq!(row.actions[0].behavior_probability, ProbabilityQ32::ONE);
    assert_eq!(inputs.candidate_observations, inputs.baseline_observations);
    assert_eq!(row.outcome_evidence, Digest32::from_array([7; 32]));
    assert_eq!(row.outcome_model_evidence, Digest32::ZERO);
    assert_eq!(row.actions[0].predicted_outcome, FixedQ32::ZERO);
    Ok(())
}

#[test]
fn independent_b_source_rejects_noncanonical_unknown_and_missing_data() -> io::Result<()> {
    let original = source();
    let bytes = serde_json::to_vec(&original)?;
    let mut spaced = bytes.clone();
    spaced.push(b'\n');
    assert!(OriginalHoldoutSourceData::decode(&spaced).is_err());
    let mut unknown = serde_json::to_value(&original)?;
    unknown["caller_claimed_authority"] = serde_json::json!(true);
    assert!(OriginalHoldoutSourceData::decode(&serde_json::to_vec(&unknown)?).is_err());
    let mut missing = source();
    missing.training.clear();
    assert!(OriginalHoldoutSourceData::decode(&serde_json::to_vec(&missing)?).is_err());
    missing = source();
    missing.collected_after_seconds = missing.registered_at_seconds;
    assert!(OriginalHoldoutSourceData::decode(&serde_json::to_vec(&missing)?).is_err());
    Ok(())
}

#[test]
fn independent_b_source_does_not_normalize_outcomes_or_invent_policy_support() {
    let mut original = source();
    original.heldout[0].finalized_outcome_q32 = FixedQ32::ONE.raw() + 1;
    assert!(original.inputs().is_err());
    original = source();
    original.training[0].outcome_q32 = -1;
    assert!(original.inputs().is_err());
    original = source();
    original.heldout[0].actions[0].candidate_probability_q32 = ProbabilityQ32::ONE.raw() + 1;
    assert!(original.inputs().is_err());
    original = source();
    original.heldout[0].actions[0].behavior_probability_q32 = 0;
    assert!(original.inputs().is_err());
    original = source();
    original.heldout[0].complete_candidates = false;
    assert!(original.inputs().is_err());
}

#[test]
fn independent_b_policy_statement_cannot_read_holdout_labels() -> io::Result<()> {
    let mut original = source();
    let policy = original.policy_payload()?;
    let manifest = original.manifest_digest()?;
    let original_bytes = serde_json::to_vec(&original)?;
    original.heldout[0].finalized_outcome_q32 = FixedQ32::ONE.raw() / 2;
    assert_eq!(original.policy_payload()?, policy);
    assert_eq!(original.manifest_digest()?, manifest);
    assert_ne!(serde_json::to_vec(&original)?, original_bytes);
    original.heldout[0].actions[0].candidate_probability_q32 = 0;
    assert_ne!(original.policy_payload()?, policy);
    assert_eq!(original.manifest_digest()?, manifest);
    original.heldout[0].episode_lineage = "different-original-episode".into();
    assert_ne!(original.manifest_digest()?, manifest);
    Ok(())
}

#[test]
fn independent_b_source_rejects_missing_evidence_duplicate_identity_and_time_rewrite() {
    let mut original = source();
    original.heldout[0].original_outcome_evidence = [0; 32];
    assert!(original.inputs().is_err());
    original = source();
    original.heldout[0].decision_id = original.training[0].decision_id.clone();
    assert!(original.inputs().is_err());
    original = source();
    original.heldout[0].observed_at_seconds = original.heldout[0].decision_at_seconds - 1;
    assert!(original.inputs().is_err());
    original = source();
    original.heldout[0].chosen_action = "absent-original-action".into();
    assert!(original.inputs().is_err());
    original = source();
    original
        .future_window_ids
        .push(original.future_window_ids[0].clone());
    assert!(original.inputs().is_err());
}

#[test]
fn independent_b_source_rejects_zero_probability_chosen_action_even_with_valid_totals() {
    let mut original = source();
    original.heldout[0].actions[0] = OriginalPolicyAction {
        action_id: "left".into(),
        behavior_probability_q32: 0,
        candidate_probability_q32: 0,
        baseline_probability_q32: 0,
    };
    original.heldout[0].actions.push(OriginalPolicyAction {
        action_id: "right".into(),
        behavior_probability_q32: ProbabilityQ32::ONE.raw(),
        candidate_probability_q32: ProbabilityQ32::ONE.raw(),
        baseline_probability_q32: ProbabilityQ32::ONE.raw(),
    });
    assert!(original.inputs().is_err());
}
