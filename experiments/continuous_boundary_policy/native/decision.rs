//! Original NDU evaluates supplied research scores; it does not execute a neural model.
use crate::Result;
use crate::protocol::Row;
use crate::protocol::digest;
use codex_hepta_ndu::AggregationOperator;
use codex_hepta_ndu::AxisAggregationRule;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde_json::Value;
use serde_json::json;

fn axis(value: i64) -> Result<AxisValue> {
    Ok(AxisValue {
        axis: StableId::new("task.value")?,
        value: FixedQ32::from_raw(value),
    })
}

fn rule() -> Result<AxisAggregationRule> {
    Ok(AxisAggregationRule {
        axis: StableId::new("task.value")?,
        operator: AggregationOperator::Sum,
    })
}

pub fn decide(row: &Row, binary: Digest32) -> Result<Value> {
    let objective = row.objective_sha256.parse::<Digest32>()?;
    let support = row.support(binary)?;
    let generation = Generation::new(1)?;
    let mut contributions = Vec::with_capacity(3);
    for (index, name) in ["keep", "repair", "abstain"].iter().enumerate() {
        contributions.push(UtilityContribution {
            candidate_id: StableId::new(*name)?,
            organ_id: StableId::new("continuous-cell")?,
            objective_digest: objective,
            generation,
            feasibility: FeasibilityPosture::Feasible,
            utility: vec![axis(
                row.scores_q24[index]
                    .checked_mul(256)
                    .ok_or("Q32 overflow")?,
            )?],
            risk: vec![],
            resource: vec![],
            uncertainty: vec![axis(0)?],
            support_digest: support,
        });
    }
    let evaluation = evaluate_candidates_with_policy(
        ContributionSet {
            objective_digest: objective,
            generation,
            contributions,
        },
        UtilityProfile {
            profile_id: StableId::new("continuous-readout.utility.v1")?,
            axis_registry_digest: Digest32::of_bytes(b"task.value"),
            normalization_manifest_digest: Digest32::of_bytes(b"q32.task-utility.v1"),
            dimensions: vec![(StableId::new("task.value")?, AxisDirection::Maximize)],
            risk_ceilings: vec![],
            resource_ceilings: vec![],
            required_organs: RequiredOrganSet {
                organ_ids: vec![StableId::new("continuous-cell")?],
            },
        },
        /*scalarization*/ None,
        EvaluationPolicyV1 {
            policy_id: StableId::new("continuous-readout.evaluation.v1")?,
            utility_rules: vec![rule()?],
            risk_rules: vec![],
            resource_rules: vec![],
            uncertainty_rules: vec![rule()?],
            pareto_absolute_tolerances: vec![axis(0)?],
        },
    )?;
    let frontier: Vec<String> = evaluation
        .base
        .pareto_frontier
        .iter()
        .map(|candidate| candidate.candidate_id.as_str().to_owned())
        .collect();
    let selected = ["abstain", "repair", "keep"]
        .iter()
        .find(|candidate| frontier.iter().any(|name| name == **candidate))
        .ok_or("Empty feasible task frontier")?;
    let action = if *selected == "abstain" {
        "stop"
    } else {
        *selected
    };
    let mut receipt = json!({
        "schema": "hepta.boundary-policy.score-receipt.v1",
        "row_id": row.row_id,
        "model_sha256": row.model_sha256,
        "objective_sha256": row.objective_sha256,
        "observation_sha256": row.observation_sha256,
        "state_sha256": row.state_sha256,
        "scores_q24": row.scores_q24,
        "action": action,
        "tie": frontier.len() > 1,
        "native_ndu_frontier": frontier,
        "native_ndu_digest": evaluation.evaluation_digest_v2.to_string(),
        "support_sha256": support.to_string(),
        "native_binary_sha256": binary.to_string(),
        "owner_authority": "DENY_ALL",
        "durable_owner_execution": false,
        "model_inference_executed": false,
        "actual_ndu_calls": 1,
        "actual_kernel_calls": 0,
    });
    receipt["receipt_sha256"] = json!(digest(&receipt)?.to_string());
    Ok(receipt)
}
