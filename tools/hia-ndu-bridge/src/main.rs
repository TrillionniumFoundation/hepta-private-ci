//! Bounded advisory transport over the actual NDU owner algorithms.
//! A supplied verification digest is lineage, never proof or effect authority.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::io::Read;
use std::process::ExitCode;

use codex_hepta_ndu::AggregationOperator;
use codex_hepta_ndu::AxisAggregationRule;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisLimit;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RecursiveUtilityPath;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityEvent;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_ndu::evaluate_recursive_utility;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

const MAX_INPUT: u64 = 1_048_576;
const Q32: i64 = 1_i64 << 32;
const UTILITY_LIMIT: i64 = 1_000_000 * Q32;
const SCHEMA: &str = "hepta.hia.ndu.request.v1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Event {
    event_digest: String,
    preference_digest: String,
    instant_q32: i64,
    discount_q32: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Candidate {
    id: String,
    verified: bool,
    verification_digest: String,
    support_digest: String,
    resource_cost_q32: i64,
    risk_q32: i64,
    uncertainty_q32: i64,
    terminal_q32: i64,
    events: Vec<Event>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: String,
    objective_digest: String,
    snapshot_digest: String,
    generation: u64,
    utility_unit: String,
    resource_unit: String,
    risk_unit: String,
    resource_budget_q32: i64,
    risk_ceiling_q32: i64,
    candidates: Vec<Candidate>,
}

fn digest(value: &str) -> Result<Digest32, String> {
    let result: Digest32 = value.parse().map_err(|error| format!("{error}"))?;
    if result.is_zero() {
        return Err("zero digest is not evidence".into());
    }
    Ok(result)
}

fn id(value: &str) -> Result<StableId, String> {
    StableId::new(value).map_err(|error| error.to_string())
}

fn axis(name: &str, value: i64) -> Result<AxisValue, String> {
    Ok(AxisValue {
        axis: id(name)?,
        value: FixedQ32::from_raw(value),
    })
}

fn rule(name: &str) -> Result<AxisAggregationRule, String> {
    Ok(AxisAggregationRule {
        axis: id(name)?,
        operator: AggregationOperator::Sum,
    })
}

fn identity() -> Value {
    json!({
        "schema": "hepta.hia.ndu.identity.v1",
        "source_commit": env!("HEPTA_NDU_SOURCE_COMMIT"),
        "source_digest": env!("HEPTA_NDU_SOURCE_DIGEST"),
        "bridge_digest": env!("HEPTA_NDU_BRIDGE_DIGEST"),
        "rustc": env!("HEPTA_NDU_RUSTC"),
        "algorithms": ["codex_hepta_ndu::evaluate_recursive_utility",
                       "codex_hepta_ndu::evaluate_candidates_with_policy"],
        "authority": "DENY_ALL",
        "safety_certificate": false
    })
}

fn evaluate(input: &[u8]) -> Result<Value, String> {
    let request: Request = serde_json::from_slice(input).map_err(|error| error.to_string())?;
    if request.schema != SCHEMA || !(1..=128).contains(&request.candidates.len()) {
        return Err("unsupported schema or candidate count".into());
    }
    if request.resource_budget_q32 < 0
        || !(0..=Q32).contains(&request.risk_ceiling_q32)
        || request.risk_unit != "probability"
        || !["nanoseconds", "microseconds", "bytes", "modeled-work"]
            .contains(&request.resource_unit.as_str())
    {
        return Err("invalid budget, risk ceiling or units".into());
    }
    id(&request.utility_unit)?;
    let objective = digest(&request.objective_digest)?;
    let snapshot = digest(&request.snapshot_digest)?;
    let generation = Generation::new(request.generation).map_err(|error| error.to_string())?;
    let request_digest = Digest32::of_bytes(input);
    let units = Digest32::of_bytes(
        &serde_json::to_vec(&json!({
            "utility": request.utility_unit, "resource": request.resource_unit,
            "risk": request.risk_unit, "fixed_point": "signed-Q32-nearest-ties-even"
        }))
        .map_err(|error| error.to_string())?,
    );
    let mut candidate_ids = BTreeSet::new();
    let mut contributions = Vec::new();
    let mut paths = Vec::new();
    for candidate in &request.candidates {
        let candidate_id = id(&candidate.id)?;
        if !candidate_ids.insert(candidate.id.clone()) {
            return Err("duplicate candidate identity".into());
        }
        if candidate.resource_cost_q32 < 0
            || !(0..=Q32).contains(&candidate.risk_q32)
            || !(0..=Q32).contains(&candidate.uncertainty_q32)
        {
            return Err("invalid candidate cost, risk or uncertainty".into());
        }
        let verification = digest(&candidate.verification_digest)?;
        let support = digest(&candidate.support_digest)?;
        if candidate.id == "abstain"
            && (!candidate.verified
                || candidate.resource_cost_q32 != 0
                || candidate.risk_q32 != 0
                || candidate.terminal_q32 != 0
                || candidate.events.iter().any(|event| event.instant_q32 != 0))
        {
            return Err("abstain must be an exact zero-effect, zero-cost alternative".into());
        }
        let events = candidate
            .events
            .iter()
            .enumerate()
            .map(|(index, event)| {
                Ok(UtilityEvent {
                    sequence: index as u64 + 1,
                    event_digest: digest(&event.event_digest)?,
                    preference_digest: digest(&event.preference_digest)?,
                    instant: FixedQ32::from_raw(event.instant_q32),
                    discount: FixedQ32::from_raw(event.discount_q32),
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        let coefficient = Digest32::of_bytes(b"hia.ndu.discounted-path.q32.v1");
        let path = RecursiveUtilityPath {
            objective_digest: objective,
            episode_digest: Digest32::of_parts(&[snapshot.as_array(), candidate.id.as_bytes()]),
            coefficient_digest: coefficient,
            units_digest: units,
            terminal_outcome_digest: support,
            terminal: FixedQ32::from_raw(candidate.terminal_q32),
            lower: FixedQ32::from_raw(-UTILITY_LIMIT),
            upper: FixedQ32::from_raw(UTILITY_LIMIT),
            events,
        };
        let recursive = evaluate_recursive_utility(&path).map_err(|error| error.to_string())?;
        if recursive.projection_count != 0 {
            return Err("projected utility is unsupported by this bridge profile".into());
        }
        let value = recursive.values[0].raw();
        let bound_support = Digest32::of_parts(&[
            b"hia.ndu.compiler-candidate.v1\0",
            request_digest.as_array(),
            snapshot.as_array(),
            verification.as_array(),
            support.as_array(),
            recursive.evidence_digest.as_array(),
        ]);
        contributions.push(UtilityContribution {
            candidate_id,
            organ_id: id("hia.compiler")?,
            objective_digest: objective,
            generation,
            feasibility: if candidate.verified {
                FeasibilityPosture::Feasible
            } else {
                FeasibilityPosture::HardConstraintViolation
            },
            utility: vec![axis("utility.net", value)?],
            risk: vec![axis("risk.tail", candidate.risk_q32)?],
            resource: vec![axis("resource.optimization", candidate.resource_cost_q32)?],
            uncertainty: vec![axis("utility.net", candidate.uncertainty_q32)?],
            support_digest: bound_support,
        });
        paths.push(json!({
            "id": candidate.id,
            "verification_digest": candidate.verification_digest,
            "support_digest": candidate.support_digest,
            "values_q32": recursive.values.iter().map(|value| value.raw()).collect::<Vec<_>>(),
            "recursive_evidence_digest": recursive.evidence_digest.to_string(),
            "resource_cost_q32": candidate.resource_cost_q32,
            "risk_q32": candidate.risk_q32,
            "projection_count": recursive.projection_count
        }));
    }
    let profile = UtilityProfile {
        profile_id: id("hia.compiler.v1")?,
        axis_registry_digest: Digest32::of_bytes(b"utility.net/risk.tail/resource.optimization.v1"),
        normalization_manifest_digest: units,
        dimensions: vec![(id("utility.net")?, AxisDirection::Maximize)],
        risk_ceilings: vec![AxisLimit {
            axis: id("risk.tail")?,
            maximum: FixedQ32::from_raw(request.risk_ceiling_q32),
        }],
        resource_ceilings: vec![AxisLimit {
            axis: id("resource.optimization")?,
            maximum: FixedQ32::from_raw(request.resource_budget_q32),
        }],
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("hia.compiler")?],
        },
    };
    let policy = EvaluationPolicyV1 {
        policy_id: id("hia.compiler.complete-path.v1")?,
        utility_rules: vec![rule("utility.net")?],
        risk_rules: vec![rule("risk.tail")?],
        resource_rules: vec![rule("resource.optimization")?],
        uncertainty_rules: vec![rule("utility.net")?],
        pareto_absolute_tolerances: vec![axis("utility.net", 0)?],
    };
    let evaluation = evaluate_candidates_with_policy(
        ContributionSet {
            objective_digest: objective,
            generation,
            contributions,
        },
        profile,
        /*scalarization*/ None,
        policy,
    )
    .map_err(|error| error.to_string())?;
    let base = &evaluation.base;
    Ok(json!({
        "schema": "hepta.hia.ndu.response.v1", "status": "advisory",
        "request_digest": request_digest.to_string(),
        "objective_digest": request.objective_digest, "snapshot_digest": request.snapshot_digest,
        "generation": request.generation,
        "identity": identity(),
        "authority": "DENY_ALL", "safety_certificate": false,
        "optimality_scope": "bounded-supplied-candidate-paths-only",
        "disposition": format!("{:?}", base.disposition),
        "advisory_candidate_id": base.advisory_recommendation.as_ref().map(StableId::as_str),
        "evaluated_candidate_ids": base.evaluated_candidates.iter().map(|row| row.candidate_id.as_str()).collect::<Vec<_>>(),
        "pareto_candidate_ids": base.pareto_frontier.iter().map(|row| row.candidate_id.as_str()).collect::<Vec<_>>(),
        "rejected": base.rejected_candidates.iter().map(|row| json!({
            "id": row.candidate_id.as_str(),
            "reasons": row.reasons.iter().map(|reason| format!("{reason:?}")).collect::<Vec<_>>()
        })).collect::<Vec<_>>(),
        "evaluation_digest": evaluation.evaluation_digest_v2.to_string(),
        "evaluation_policy_digest": evaluation.evaluation_policy_digest.to_string(),
        "utility_profile_digest": base.utility_profile_digest.to_string(),
        "paths": paths
    }))
}

fn run() -> Result<Value, String> {
    let arguments: Vec<_> = std::env::args().skip(1).collect();
    if arguments == ["--identity"] {
        return Ok(identity());
    }
    if !arguments.is_empty() {
        return Err("only --identity or one bounded JSON request on stdin is supported".into());
    }
    let mut input = Vec::new();
    std::io::stdin()
        .take(MAX_INPUT + 1)
        .read_to_end(&mut input)
        .map_err(|error| error.to_string())?;
    if input.len() as u64 > MAX_INPUT {
        return Err("request exceeds 1 MiB".into());
    }
    evaluate(&input)
}

fn main() -> ExitCode {
    match run() {
        Ok(value) => {
            println!("{value}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            println!(
                "{}",
                json!({"schema": "hepta.hia.ndu.response.v1",
                "status": "error", "error": error, "authority": "DENY_ALL",
                "safety_certificate": false})
            );
            ExitCode::FAILURE
        }
    }
}
