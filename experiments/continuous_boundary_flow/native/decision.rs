//! The original NDU evaluator consumes scores derived from actual sparse activations.
use crate::Q;
use crate::Result;
use crate::model::Profile;
use crate::model::Readout;
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
fn axis(name: &str, value: i64) -> Result<AxisValue> {
    Ok(AxisValue {
        axis: StableId::new(name)?,
        value: FixedQ32::from_raw(value),
    })
}
fn rule(name: &str) -> Result<AxisAggregationRule> {
    Ok(AxisAggregationRule {
        axis: StableId::new(name)?,
        operator: AggregationOperator::Sum,
    })
}
pub fn decide(
    profile: &Profile,
    activation: &[i64],
    risk: i64,
    support: Digest32,
) -> Result<Readout> {
    if !(0..=Q).contains(&risk) {
        return Err("Invalid declared risk".into());
    }
    let scores = profile.scores(activation)?;
    let objective = profile.objective_digest.parse::<Digest32>()?;
    let generation = Generation::new(1)?;
    let names = ["keep", "repair", "abstain"];
    let mut contributions = Vec::new();
    for (i, name) in names.iter().enumerate() {
        contributions.push(UtilityContribution {
            candidate_id: StableId::new(*name)?,
            organ_id: StableId::new("continuous-cell")?,
            objective_digest: objective,
            generation,
            feasibility: FeasibilityPosture::Feasible,
            utility: vec![axis(
                "task.value",
                scores[i].checked_mul(256).ok_or("Q32 score overflow")?,
            )?],
            risk: vec![],
            resource: vec![],
            uncertainty: vec![axis("task.value", 0)?],
            support_digest: support,
        });
    }
    let result = evaluate_candidates_with_policy(
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
            utility_rules: vec![rule("task.value")?],
            risk_rules: vec![],
            resource_rules: vec![],
            uncertainty_rules: vec![rule("task.value")?],
            pareto_absolute_tolerances: vec![axis("task.value", 0)?],
        },
    )?;
    let frontier: Vec<String> = result
        .base
        .pareto_frontier
        .iter()
        .map(|v| v.candidate_id.as_str().to_owned())
        .collect();
    // A registered local task tie rule; it grants no native production authority.
    let selected = ["abstain", "repair", "keep"]
        .iter()
        .find(|x| frontier.iter().any(|v| v == **x))
        .ok_or("Empty feasible task frontier")?;
    let action = if *selected == "abstain" {
        "stop"
    } else {
        *selected
    }
    .to_string();
    Ok(Readout {
        scores_q24: scores,
        action,
        tie: frontier.len() > 1,
        native_ndu_digest: result.evaluation_digest_v2.to_string(),
        native_ndu_frontier: frontier,
    })
}
