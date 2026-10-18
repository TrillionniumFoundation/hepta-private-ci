//! Bounded canonical input commitments; all collections have explicit lengths.
//! List order is immaterial, duplicate identities are never silently deduped.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::OpeRow;
use crate::ProductEvaluationError;
use crate::TemporalComparisonInputsV1;
use crate::push_id;

use super::MAX_BATCH_ROWS;

fn ids(bytes: &mut Vec<u8>, values: &[StableId]) -> Result<(), ProductEvaluationError> {
    if values.len() > MAX_BATCH_ROWS {
        return Err(ProductEvaluationError::Binding("outcome identity capacity"));
    }
    let mut ordered: Vec<_> = values.iter().collect();
    ordered.sort();
    if ordered.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(ProductEvaluationError::Binding(
            "duplicate outcome identity",
        ));
    }
    bytes.extend_from_slice(&(ordered.len() as u64).to_be_bytes());
    for value in ordered {
        push_id(bytes, value);
    }
    Ok(())
}

fn observations(bytes: &mut Vec<u8>, rows: &[OpeRow]) -> Result<(), ProductEvaluationError> {
    let mut ordered: Vec<_> = rows.iter().collect();
    ordered.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    if ordered
        .windows(2)
        .any(|pair| pair[0].decision_id == pair[1].decision_id)
    {
        return Err(ProductEvaluationError::Binding(
            "duplicate outcome observation",
        ));
    }
    bytes.extend_from_slice(&(ordered.len() as u64).to_be_bytes());
    for row in ordered {
        if row.actions.len() > 128 {
            return Err(ProductEvaluationError::Binding("outcome action capacity"));
        }
        let mut value = Vec::new();
        push_id(&mut value, &row.decision_id);
        push_id(&mut value, &row.chosen_action);
        value.push(u8::from(row.complete_candidates));
        let mut actions: Vec<_> = row.actions.iter().collect();
        actions.sort_by(|left, right| left.action_id.cmp(&right.action_id));
        if actions
            .windows(2)
            .any(|pair| pair[0].action_id == pair[1].action_id)
        {
            return Err(ProductEvaluationError::Binding("duplicate outcome action"));
        }
        value.extend_from_slice(&(actions.len() as u64).to_be_bytes());
        for action in actions {
            push_id(&mut value, &action.action_id);
            value.extend_from_slice(&action.behavior_probability.raw().to_be_bytes());
            value.extend_from_slice(&action.evaluation_probability.raw().to_be_bytes());
            value.extend_from_slice(&action.predicted_outcome.raw().to_be_bytes());
        }
        match row.finalized_outcome {
            Some(outcome) => {
                value.push(1);
                value.extend_from_slice(&outcome.raw().to_be_bytes());
            }
            None => value.push(0),
        }
        value.extend_from_slice(&row.outcome_observed_at.to_be_bytes());
        value.extend_from_slice(row.outcome_evidence.as_array());
        value.extend_from_slice(row.outcome_model_evidence.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&value).as_array());
    }
    Ok(())
}

pub fn product_outcome_inputs_digest_v1(
    inputs: &TemporalComparisonInputsV1,
) -> Result<Digest32, ProductEvaluationError> {
    for length in [
        inputs.training.len(),
        inputs.targets.len(),
        inputs.candidate_observations.len(),
        inputs.baseline_observations.len(),
        inputs.assignments.len(),
    ] {
        if length > MAX_BATCH_ROWS {
            return Err(ProductEvaluationError::Binding("outcome input capacity"));
        }
    }
    let mut bytes = b"hepta.learning-eval.outcome-inputs.v1".to_vec();
    let mut training: Vec<_> = inputs.training.iter().collect();
    training.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    if training
        .windows(2)
        .any(|pair| pair[0].decision_id == pair[1].decision_id)
    {
        return Err(ProductEvaluationError::Binding(
            "duplicate outcome training row",
        ));
    }
    bytes.extend_from_slice(&(training.len() as u64).to_be_bytes());
    for row in training {
        let mut value = Vec::new();
        for id in [
            &row.decision_id,
            &row.principal_lineage,
            &row.episode_lineage,
            &row.window_id,
            &row.action_id,
        ] {
            push_id(&mut value, id);
        }
        value.extend_from_slice(&row.outcome.raw().to_be_bytes());
        value.extend_from_slice(&row.observed_at.to_be_bytes());
        value.extend_from_slice(row.evidence_digest.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&value).as_array());
    }
    let mut targets: Vec<_> = inputs.targets.iter().collect();
    targets.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    if targets
        .windows(2)
        .any(|pair| pair[0].decision_id == pair[1].decision_id)
    {
        return Err(ProductEvaluationError::Binding("duplicate outcome target"));
    }
    bytes.extend_from_slice(&(targets.len() as u64).to_be_bytes());
    for row in targets {
        if row.actions.len() > 128 {
            return Err(ProductEvaluationError::Binding(
                "outcome target action capacity",
            ));
        }
        let mut value = Vec::new();
        for id in [
            &row.decision_id,
            &row.principal_lineage,
            &row.episode_lineage,
            &row.window_id,
        ] {
            push_id(&mut value, id);
        }
        value.extend_from_slice(&row.decision_at.to_be_bytes());
        ids(&mut value, &row.actions)?;
        bytes.extend_from_slice(Digest32::of_bytes(&value).as_array());
    }
    observations(&mut bytes, &inputs.candidate_observations)?;
    observations(&mut bytes, &inputs.baseline_observations)?;
    let mut assignments: Vec<_> = inputs.assignments.iter().collect();
    assignments.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    if assignments
        .windows(2)
        .any(|pair| pair[0].decision_id == pair[1].decision_id)
    {
        return Err(ProductEvaluationError::Binding(
            "duplicate outcome assignment",
        ));
    }
    bytes.extend_from_slice(&(assignments.len() as u64).to_be_bytes());
    for row in assignments {
        let mut value = Vec::new();
        push_id(&mut value, &row.decision_id);
        push_id(&mut value, &row.cluster_id);
        bytes.extend_from_slice(Digest32::of_bytes(&value).as_array());
    }
    ids(&mut bytes, &inputs.snapshot_ids)?;
    ids(&mut bytes, &inputs.future_window_ids)?;
    Ok(Digest32::of_bytes(&bytes))
}
