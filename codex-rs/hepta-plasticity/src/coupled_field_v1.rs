//! Experimental deterministic coupled-field candidate replay using actual Hepta
//! proposal types and mutation policy. This is NOT an authority or a solver:
//! completeness is relative to the declared finite action family. A trusted host
//! must authenticate the expected profile digest, bases, solver transcript,
//! owner frontiers, norm denominators and policy before admission.
use crate::{
    LayerNormDenominatorV2, ParameterCandidateKindV2, ParameterCandidateRequestV2,
    ParameterDeltaV2, ParameterMutationPolicyErrorV1, ParameterMutationPolicyV1, ProposalWindowV2,
    authorize_parameter_mutation_v1, verify_parameter_mutation_policy_v1,
};
use codex_hepta_types::{Digest32, FixedQ32, StableId};
use std::collections::{BTreeMap, BTreeSet};
const MAX_PARAMETERS: usize = 4096;
const MAX_ACTIONS: usize = 31;
const MAX_BLOCKS: usize = 256;
const MAX_RANK: usize = 16;
const Q52: i128 = 1_i128 << 52;
const PICO: i128 = 1_000_000_000_000;
const DENOMINATOR: i128 = (1_i128 << 20) * PICO;
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FieldParameterV1 {
    pub parameter_id: StableId,
    pub lower: FixedQ32,
    pub upper: FixedQ32,
    pub basis_q52: Vec<i64>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FieldBlockV1 {
    pub owner_id: StableId,
    pub layer_id: StableId,
    pub owner_frontier_digest: Digest32,
    pub response_digest: Digest32,
    pub rank: usize,
    pub parameters: Vec<FieldParameterV1>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FieldActionV1 {
    pub action_id: StableId,
    pub solver_record_digest: Digest32,
    /// Coefficients in pico-units; one canonical vector for each block.
    pub coefficient_pico: Vec<Vec<i64>>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoupledFieldProfileV1 {
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub dataset_digest: Digest32,
    pub objective_digest: Digest32,
    pub solver_digest: Digest32,
    pub runtime_digest: Digest32,
    pub norm_evidence_digest: Digest32,
    pub policy: ParameterMutationPolicyV1,
    pub norm_layers: Vec<LayerNormDenominatorV2>,
    /// Sum of the block L2 update norms, raw Q32. The caller's registered
    /// policy and resource budget may require a stricter cap.
    pub path_budget: FixedQ32,
    pub blocks: Vec<FieldBlockV1>,
    pub actions: Vec<FieldActionV1>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispositionV1 {
    Update(StableId),
    NoChange,
    Duplicate,
    PathRejected,
    TrustRejected,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratedCoupledFieldV1 {
    pub profile_digest: Digest32,
    pub candidates: Vec<ParameterCandidateRequestV2>,
    pub outcomes: Vec<(StableId, DispositionV1)>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ErrorV1 {
    EmptyBinding,
    Noncanonical,
    Shape,
    ResourceLimit,
    Policy(ParameterMutationPolicyErrorV1),
    InvalidBounds,
    Arithmetic,
    ExpectedProfileMismatch,
    CandidateMismatch,
}
impl From<ParameterMutationPolicyErrorV1> for ErrorV1 {
    fn from(e: ParameterMutationPolicyErrorV1) -> Self {
        Self::Policy(e)
    }
}
fn check(b: bool, e: ErrorV1) -> Result<(), ErrorV1> {
    if b { Ok(()) } else { Err(e) }
}
fn len(out: &mut Vec<u8>, n: usize) -> Result<(), ErrorV1> {
    out.extend_from_slice(
        &u32::try_from(n)
            .map_err(|_| ErrorV1::Arithmetic)?
            .to_be_bytes(),
    );
    Ok(())
}
fn id(out: &mut Vec<u8>, s: &StableId) -> Result<(), ErrorV1> {
    len(out, s.as_str().len())?;
    out.extend_from_slice(s.as_str().as_bytes());
    Ok(())
}
fn digest(out: &mut Vec<u8>, d: Digest32) -> Result<(), ErrorV1> {
    check(!d.is_zero(), ErrorV1::EmptyBinding)?;
    out.extend_from_slice(d.as_array());
    Ok(())
}
fn strictly_sorted<T: Ord>(x: impl Iterator<Item = T>) -> bool {
    let mut prev = None;
    for v in x {
        if prev.as_ref().is_some_and(|p| p >= &v) {
            return false;
        }
        prev = Some(v);
    }
    true
}
fn norm_square(x: i64) -> u128 {
    let v = i128::from(x);
    (v * v) as u128
}
fn add(a: u128, b: u128) -> Result<u128, ErrorV1> {
    a.checked_add(b).ok_or(ErrorV1::Arithmetic)
}
fn relative(d: u128, b: u128, ppm: u128) -> Result<bool, ErrorV1> {
    check(b > 0, ErrorV1::InvalidBounds)?;
    let l = d
        .checked_mul(1_000_000_000_000)
        .ok_or(ErrorV1::Arithmetic)?;
    let r = b.checked_mul(ppm * ppm).ok_or(ErrorV1::Arithmetic)?;
    Ok(l <= r)
}
fn ceil_sqrt(n: u128) -> u128 {
    let a = n.isqrt();
    a + u128::from(a * a != n)
}
fn raw_delta(b: &[i64], c: &[i64]) -> Result<i64, ErrorV1> {
    check(b.len() == c.len(), ErrorV1::Shape)?;
    let n = b.iter().zip(c).try_fold(0_i128, |a, (&x, &y)| {
        a.checked_add(i128::from(x) * i128::from(y))
            .ok_or(ErrorV1::Arithmetic)
    })?;
    i64::try_from(n / DENOMINATOR).map_err(|_| ErrorV1::Arithmetic)
}
/// Validate bounded canonical profile and hash every replay input. The digest
/// only identifies this declaration; it is not authorization or solver proof.
pub fn coupled_profile_digest_v1(p: &CoupledFieldProfileV1) -> Result<Digest32, ErrorV1> {
    check(
        !p.blocks.is_empty()
            && p.blocks.len() <= MAX_BLOCKS
            && p.actions.len() <= MAX_ACTIONS
            && !p.norm_layers.is_empty()
            && p.norm_layers.len() <= MAX_BLOCKS,
        ErrorV1::ResourceLimit,
    )?;
    check(
        p.path_budget.raw() > 0 && p.path_budget <= FixedQ32::ONE,
        ErrorV1::InvalidBounds,
    )?;
    check(
        strictly_sorted(p.blocks.iter().map(|x| &x.owner_id))
            && strictly_sorted(p.actions.iter().map(|x| &x.action_id))
            && strictly_sorted(p.norm_layers.iter().map(|x| &x.layer_id)),
        ErrorV1::Noncanonical,
    )?;
    verify_parameter_mutation_policy_v1(&p.policy)?;
    check(
        p.policy.selected_artifact_digest == p.selected_artifact_digest
            && p.policy.window == p.window,
        ErrorV1::InvalidBounds,
    )?;
    let mut o = b"hepta.experimental.coupled-field.profile.v1\0".to_vec();
    for d in [
        p.selected_artifact_digest,
        p.window.window_digest,
        p.dataset_digest,
        p.objective_digest,
        p.solver_digest,
        p.runtime_digest,
        p.norm_evidence_digest,
        p.policy.policy_digest,
    ] {
        digest(&mut o, d)?;
    }
    id(&mut o, &p.window.window_id)?;
    o.extend_from_slice(&p.path_budget.raw().to_be_bytes());
    len(&mut o, p.norm_layers.len())?;
    let mut total_norm = 0_u128;
    for n in &p.norm_layers {
        check(n.baseline_squared_l2_raw_q64 > 0, ErrorV1::InvalidBounds)?;
        total_norm = add(total_norm, n.baseline_squared_l2_raw_q64)?;
        id(&mut o, &n.layer_id)?;
        o.extend_from_slice(&n.baseline_squared_l2_raw_q64.to_be_bytes());
    }
    let mut count = 0_usize;
    let mut seen = BTreeSet::new();
    len(&mut o, p.blocks.len())?;
    for b in &p.blocks {
        check(
            (1..=MAX_RANK).contains(&b.rank) && !b.parameters.is_empty(),
            ErrorV1::Shape,
        )?;
        count = count
            .checked_add(b.parameters.len())
            .filter(|n| *n <= MAX_PARAMETERS)
            .ok_or(ErrorV1::ResourceLimit)?;
        check(
            p.norm_layers.iter().any(|n| n.layer_id == b.layer_id),
            ErrorV1::InvalidBounds,
        )?;
        check(
            strictly_sorted(b.parameters.iter().map(|x| &x.parameter_id)),
            ErrorV1::Noncanonical,
        )?;
        id(&mut o, &b.owner_id)?;
        id(&mut o, &b.layer_id)?;
        digest(&mut o, b.owner_frontier_digest)?;
        digest(&mut o, b.response_digest)?;
        len(&mut o, b.rank)?;
        len(&mut o, b.parameters.len())?;
        for v in &b.parameters {
            check(seen.insert(v.parameter_id.clone()), ErrorV1::Noncanonical)?;
            check(
                v.basis_q52.len() == b.rank
                    && v.basis_q52.iter().all(|x| i128::from(*x).abs() <= Q52),
                ErrorV1::Shape,
            )?;
            check(
                v.lower <= FixedQ32::ZERO && v.upper >= FixedQ32::ZERO,
                ErrorV1::InvalidBounds,
            )?;
            authorize_parameter_mutation_v1(
                &p.policy,
                p.selected_artifact_digest,
                &p.window,
                &b.layer_id,
                &v.parameter_id,
                v.lower,
                v.upper,
            )?;
            id(&mut o, &v.parameter_id)?;
            o.extend_from_slice(&v.lower.raw().to_be_bytes());
            o.extend_from_slice(&v.upper.raw().to_be_bytes());
            for x in &v.basis_q52 {
                o.extend_from_slice(&x.to_be_bytes());
            }
        }
    }
    check(
        count
            .checked_mul(p.actions.len().max(1))
            .is_some_and(|n| n <= MAX_PARAMETERS),
        ErrorV1::ResourceLimit,
    )?;
    len(&mut o, p.actions.len())?;
    for a in &p.actions {
        id(&mut o, &a.action_id)?;
        digest(&mut o, a.solver_record_digest)?;
        check(a.coefficient_pico.len() == p.blocks.len(), ErrorV1::Shape)?;
        for (b, c) in p.blocks.iter().zip(&a.coefficient_pico) {
            check(
                c.len() == b.rank && c.iter().all(|x| i128::from(*x).abs() <= PICO),
                ErrorV1::Shape,
            )?;
            for x in c {
                o.extend_from_slice(&x.to_be_bytes());
            }
        }
    }
    Ok(Digest32::of_bytes(&o))
}
fn candidate_id(profile: Digest32, deltas: &[ParameterDeltaV2]) -> Result<StableId, ErrorV1> {
    let mut b = b"hepta.experimental.coupled-field.candidate.v1\0".to_vec();
    b.extend_from_slice(profile.as_array());
    len(&mut b, deltas.len())?;
    for d in deltas {
        id(&mut b, &d.layer_id)?;
        id(&mut b, &d.parameter_id)?;
        b.extend_from_slice(&d.delta.raw().to_be_bytes());
        b.extend_from_slice(&d.lower_bound.raw().to_be_bytes());
        b.extend_from_slice(&d.upper_bound.raw().to_be_bytes());
        digest(&mut b, d.evidence_digest)?;
    }
    StableId::new(format!("candidate:field:{}", Digest32::of_bytes(&b)))
        .map_err(|_| ErrorV1::Noncanonical)
}
pub fn generate_coupled_field_v1(
    p: &CoupledFieldProfileV1,
) -> Result<GeneratedCoupledFieldV1, ErrorV1> {
    let profile_digest = coupled_profile_digest_v1(p)?;
    let mut candidates = vec![ParameterCandidateRequestV2 {
        candidate_id: candidate_id(profile_digest, &[])?,
        kind: ParameterCandidateKindV2::NoChange,
        parameter_deltas: vec![],
    }];
    let denom: BTreeMap<_, _> = p
        .norm_layers
        .iter()
        .map(|n| (n.layer_id.clone(), n.baseline_squared_l2_raw_q64))
        .collect();
    let total = denom.values().try_fold(0_u128, |a, &b| add(a, b))?;
    let mut outcomes = Vec::new();
    let mut seen = BTreeSet::new();
    for a in &p.actions {
        let mut deltas = Vec::new();
        let mut path = 0_u128;
        let mut per_layer = BTreeMap::<StableId, u128>::new();
        let mut global = 0_u128;
        for (block, c) in p.blocks.iter().zip(&a.coefficient_pico) {
            let mut block_sq = 0_u128;
            for v in &block.parameters {
                let x = raw_delta(&v.basis_q52, c)?;
                let delta = FixedQ32::from_raw(x);
                // Do not clamp: clamping would change the coupled direction.
                check(delta >= v.lower && delta <= v.upper, ErrorV1::InvalidBounds)?;
                if x == 0 {
                    continue;
                }
                let sq = norm_square(x);
                block_sq = add(block_sq, sq)?;
                global = add(global, sq)?;
                let old = per_layer.entry(block.layer_id.clone()).or_default();
                *old = add(*old, sq)?;
                deltas.push(ParameterDeltaV2 {
                    layer_id: block.layer_id.clone(),
                    parameter_id: v.parameter_id.clone(),
                    delta,
                    lower_bound: v.lower,
                    upper_bound: v.upper,
                    evidence_digest: block.response_digest,
                });
            }
            path = add(path, ceil_sqrt(block_sq))?;
        }
        let outcome = if deltas.is_empty() {
            DispositionV1::NoChange
        } else if path > p.path_budget.raw() as u128 {
            DispositionV1::PathRejected
        } else {
            let mut pass = relative(global, total, 2500)?;
            for (l, sq) in per_layer {
                pass &= relative(sq, denom[&l], 5000)?;
            }
            if !pass {
                DispositionV1::TrustRejected
            } else {
                deltas.sort_by(|l, r| {
                    l.layer_id
                        .cmp(&r.layer_id)
                        .then(l.parameter_id.cmp(&r.parameter_id))
                });
                let k = candidate_id(profile_digest, &deltas)?;
                if !seen.insert(k.clone()) {
                    DispositionV1::Duplicate
                } else {
                    candidates.push(ParameterCandidateRequestV2 {
                        candidate_id: k.clone(),
                        kind: ParameterCandidateKindV2::Update,
                        parameter_deltas: deltas,
                    });
                    DispositionV1::Update(k)
                }
            }
        };
        outcomes.push((a.action_id.clone(), outcome));
    }
    candidates.sort_by(|l, r| l.candidate_id.cmp(&r.candidate_id));
    Ok(GeneratedCoupledFieldV1 {
        profile_digest,
        candidates,
        outcomes,
    })
}
/// expected_profile must come from independent authenticated live-owner
/// resolution. Reconstruct all outputs, including rejected and duplicate actions.
pub fn verify_coupled_field_v1(
    p: &CoupledFieldProfileV1,
    expected_profile: Digest32,
    g: &GeneratedCoupledFieldV1,
) -> Result<(), ErrorV1> {
    let d = coupled_profile_digest_v1(p)?;
    check(d == expected_profile, ErrorV1::ExpectedProfileMismatch)?;
    check(
        &generate_coupled_field_v1(p)? == g,
        ErrorV1::CandidateMismatch,
    )
}
