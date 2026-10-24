//! Offline joint-generation evidence adapter to the existing policy evaluator.
//!
//! This bounded research transport does not authenticate observations, execute a
//! model, solve a dynamic policy, select an artifact, or grant effect authority.
//! Callers pin the objective, source bundle and model snapshot independently.
//! One contribution per completed joint rollout charges its total measured wall
//! time (including its controller) once, separately from modeled work units.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AggregationOperator;
use crate::AxisAggregationRule;
use crate::AxisDirection;
use crate::AxisLimit;
use crate::AxisValue;
use crate::ContributionSet;
use crate::EvaluationPolicyV1;
use crate::FeasibilityPosture;
use crate::NduError;
use crate::NduEvaluationReceiptV2;
use crate::RequiredOrganSet;
use crate::SubjectClass;
use crate::UtilityContribution;
use crate::UtilityProfile;
use crate::evaluate_candidates_with_policy;

pub const GENERATION_ROLLOUT_MAX_BYTES: usize = 1024 * 1024;
const Q32: i64 = 1_i64 << 32;
const MAX_MODELED_UNITS: u64 = 1_000_000;
const MAX_WALL_NS: u64 = 86_400_000_000_000;
const HEADER: &str = "hepta.ndu.generation-rollout.v1";

/// Caller-held frozen identities; equality is a scope check, not attestation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GenerationRolloutPinsV1 {
    pub objective_digest: Digest32,
    pub source_bundle_digest: Digest32,
    pub model_snapshot_digest: Digest32,
}

/// Exact transport identity and the actual owner evaluator's advisory receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GenerationRolloutReceiptV1 {
    pub input_digest: Digest32,
    pub pins: GenerationRolloutPinsV1,
    pub subject_class: SubjectClass,
    pub episode_id: StableId,
    pub required_modality_mask: u8,
    pub evaluation: NduEvaluationReceiptV2,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GenerationRolloutError {
    InvalidField(&'static str),
    Ndu(NduError),
}

impl fmt::Display for GenerationRolloutError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidField(field) => write!(formatter, "invalid generation rollout {field}"),
            Self::Ndu(error) => write!(formatter, "generation rollout evaluator: {error}"),
        }
    }
}

impl Error for GenerationRolloutError {}

/// Evaluate a bounded, strictly ordered TSV transport of completed rollouts.
/// Numeric utility is signed Q32 in [-1,1]; risk is Q32 in [0,1]. Text/image/
/// audio/video mask bits are 1/2/4/8. Non-abstain candidates must produce exactly
/// the requested modality set. The required `abstain` is a literal zero-effect
/// alternative, not a successful fulfillment of the generation request.
pub fn evaluate_generation_rollout_v1(
    input: &str,
    pins: GenerationRolloutPinsV1,
) -> Result<GenerationRolloutReceiptV1, GenerationRolloutError> {
    use GenerationRolloutError::InvalidField;
    if input.len() > GENERATION_ROLLOUT_MAX_BYTES
        || !input.is_ascii()
        || !input.ends_with('\n')
        || input.contains('\r')
    {
        return Err(InvalidField("transport"));
    }
    let mut lines = input.split_terminator('\n');
    if lines.next() != Some(HEADER) {
        return Err(InvalidField("version"));
    }
    let scope_line = lines.next().ok_or(InvalidField("scope"))?;
    let scope: Vec<_> = scope_line.split('\t').collect();
    if scope.len() != 11 || scope[0] != "scope" {
        return Err(InvalidField("scope shape"));
    }
    let supplied = GenerationRolloutPinsV1 {
        objective_digest: digest(scope[1])?,
        source_bundle_digest: digest(scope[2])?,
        model_snapshot_digest: digest(scope[3])?,
    };
    if supplied != pins {
        return Err(InvalidField("frozen pins"));
    }
    let episode_id = id(scope[4])?;
    let generation =
        Generation::new(unsigned(scope[5])?).map_err(|_| InvalidField("generation"))?;
    let required_mask = unsigned(scope[6])?;
    if required_mask > 15 || required_mask.count_ones() < 2 {
        return Err(InvalidField("required modalities"));
    }
    let modeled_cap = unsigned(scope[7])?;
    let wall_cap = unsigned(scope[8])?;
    let risk_cap = signed(scope[9])?;
    // Scope field 10 is the independently registered metric/normalization
    // manifest. Its bytes are bound; this adapter does not certify its content.
    let metric_digest = digest(scope[10])?;
    if modeled_cap == 0
        || modeled_cap > MAX_MODELED_UNITS
        || wall_cap == 0
        || wall_cap > MAX_WALL_NS
        || !(0..=Q32).contains(&risk_cap)
    {
        return Err(InvalidField("budget or risk ceiling"));
    }
    let input_digest = Digest32::of_bytes(input.as_bytes());
    let organ = id("generation.joint")?;
    let utility_axis = id("task.utility")?;
    let risk_axis = id("risk.normalized")?;
    let modeled_axis = id("resource.modeled_units")?;
    let measured_axis = id("resource.measured_seconds")?;
    let mut candidate_ids = BTreeSet::new();
    let mut support_ids = BTreeSet::new();
    let mut contributions = Vec::new();
    let mut has_abstain = false;
    for line in lines {
        let fields: Vec<_> = line.split('\t').collect();
        if fields.len() != 10 || fields[0] != "candidate" || contributions.len() >= 128 {
            return Err(InvalidField("candidate shape or count"));
        }
        let candidate_id = id(fields[1])?;
        if !candidate_ids.insert(candidate_id.clone()) {
            return Err(InvalidField("duplicate candidate"));
        }
        let mask = unsigned(fields[2])?;
        let mut feasibility = match fields[3] {
            "feasible" => FeasibilityPosture::Feasible,
            "hard_violation" => FeasibilityPosture::HardConstraintViolation,
            _ => return Err(InvalidField("feasibility")),
        };
        let utility = signed(fields[4])?;
        let risk = signed(fields[5])?;
        let modeled = unsigned(fields[6])?;
        let measured_ns = unsigned(fields[7])?;
        let support = digest(fields[8])?;
        // Exact observation binding is explicit on each candidate so a row
        // from another episode cannot be silently transplanted under this scope.
        if digest(fields[9])? != Digest32::of_bytes(scope_line.as_bytes()) {
            return Err(InvalidField("candidate scope digest"));
        }
        if !support_ids.insert(support)
            || mask > 15
            || !(-Q32..=Q32).contains(&utility)
            || !(0..=Q32).contains(&risk)
            || modeled > MAX_MODELED_UNITS
            || measured_ns > MAX_WALL_NS
        {
            return Err(InvalidField("candidate values or duplicate support"));
        }
        if candidate_id.as_str() == "abstain" {
            has_abstain = true;
            if mask != 0
                || feasibility != FeasibilityPosture::Feasible
                || utility != 0
                || risk != 0
                || modeled != 0
                || measured_ns != 0
                || support != Digest32::of_bytes(b"")
            {
                return Err(InvalidField("exact zero-effect abstain"));
            }
        } else {
            if measured_ns == 0 || support == Digest32::of_bytes(b"") {
                return Err(InvalidField("unobserved active candidate"));
            }
            if mask != required_mask {
                feasibility = FeasibilityPosture::HardConstraintViolation;
            }
        }
        // The exact complete envelope and row are in the evaluator's support
        // lineage. IDs, physical units and model/source bindings are not lost.
        let support_digest = Digest32::of_parts(&[
            b"hepta.ndu.generation-rollout.support.v1",
            input_digest.as_array(),
            line.as_bytes(),
        ]);
        contributions.push(UtilityContribution {
            candidate_id,
            organ_id: organ.clone(),
            objective_digest: pins.objective_digest,
            generation,
            feasibility,
            utility: vec![axis(utility_axis.clone(), utility)],
            risk: vec![axis(risk_axis.clone(), risk)],
            resource: vec![
                axis(modeled_axis.clone(), (modeled as i64) * Q32),
                axis(measured_axis.clone(), seconds_q32(measured_ns)?),
            ],
            uncertainty: vec![axis(utility_axis.clone(), 0)],
            support_digest,
        });
    }
    if !has_abstain {
        return Err(InvalidField("missing abstain"));
    }
    let profile = UtilityProfile {
        profile_id: id("generation-rollout.v1")?,
        axis_registry_digest: Digest32::of_bytes(
            b"task.utility:max:normalized[-1,1];risk.normalized:[0,1];resource.modeled_units:integer;resource.measured_seconds:seconds",
        ),
        normalization_manifest_digest: Digest32::of_parts(&[
            b"generation-rollout.normalization.v1:ns-ceiling-to-q32-seconds",
            metric_digest.as_array(),
        ]),
        dimensions: vec![(utility_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![AxisLimit {
            axis: risk_axis.clone(),
            maximum: FixedQ32::from_raw(risk_cap),
        }],
        resource_ceilings: vec![
            AxisLimit {
                axis: modeled_axis.clone(),
                maximum: FixedQ32::from_raw((modeled_cap as i64) * Q32),
            },
            AxisLimit {
                axis: measured_axis.clone(),
                maximum: FixedQ32::from_raw(seconds_q32(wall_cap)?),
            },
        ],
        required_organs: RequiredOrganSet { organ_ids: vec![organ] },
    };
    let policy = EvaluationPolicyV1 {
        policy_id: id("generation-rollout.single-joint.v1")?,
        utility_rules: vec![rule(utility_axis.clone())],
        risk_rules: vec![rule(risk_axis)],
        resource_rules: vec![rule(modeled_axis), rule(measured_axis)],
        uncertainty_rules: vec![rule(utility_axis.clone())],
        pareto_absolute_tolerances: vec![axis(utility_axis, 0)],
    };
    let evaluation = evaluate_candidates_with_policy(
        ContributionSet {
            objective_digest: pins.objective_digest,
            generation,
            contributions,
        },
        profile,
        /*scalarization*/ None,
        policy,
    )
    .map_err(GenerationRolloutError::Ndu)?;
    Ok(GenerationRolloutReceiptV1 {
        input_digest,
        pins,
        subject_class: SubjectClass::Episode,
        episode_id,
        required_modality_mask: required_mask as u8,
        evaluation,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn axis(axis: StableId, raw: i64) -> AxisValue {
    AxisValue {
        axis,
        value: FixedQ32::from_raw(raw),
    }
}

fn rule(axis: StableId) -> AxisAggregationRule {
    AxisAggregationRule {
        axis,
        operator: AggregationOperator::RequireEqual,
    }
}

fn id(value: &str) -> Result<StableId, GenerationRolloutError> {
    StableId::new(value).map_err(|_| GenerationRolloutError::InvalidField("stable ID"))
}

fn digest(value: &str) -> Result<Digest32, GenerationRolloutError> {
    let value: Digest32 = value
        .parse()
        .map_err(|_| GenerationRolloutError::InvalidField("digest"))?;
    if value.is_zero() {
        return Err(GenerationRolloutError::InvalidField("zero digest"));
    }
    Ok(value)
}

fn unsigned(value: &str) -> Result<u64, GenerationRolloutError> {
    let parsed: u64 = value
        .parse()
        .map_err(|_| GenerationRolloutError::InvalidField("unsigned integer"))?;
    if parsed.to_string() != value {
        return Err(GenerationRolloutError::InvalidField("noncanonical integer"));
    }
    Ok(parsed)
}

fn signed(value: &str) -> Result<i64, GenerationRolloutError> {
    let parsed: i64 = value
        .parse()
        .map_err(|_| GenerationRolloutError::InvalidField("signed integer"))?;
    if parsed.to_string() != value {
        return Err(GenerationRolloutError::InvalidField("noncanonical integer"));
    }
    Ok(parsed)
}

fn seconds_q32(nanoseconds: u64) -> Result<i64, GenerationRolloutError> {
    let numerator = u128::from(nanoseconds) * (Q32 as u128);
    i64::try_from(numerator.div_ceil(1_000_000_000))
        .map_err(|_| GenerationRolloutError::InvalidField("seconds overflow"))
}

#[cfg(test)]
#[path = "generation_rollout_tests.rs"]
mod tests;
