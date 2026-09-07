//! Deterministic parameter-only V2 construction and verification.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::types::*;

/// Build an internally consistent parameter candidate-set record.
///
/// This verifies deterministic bindings and norm arithmetic over the supplied
/// candidate set only. It does not authenticate generator-relative completeness,
/// independent identities, or the provenance, freshness, or completeness of any
/// caller-supplied lineage or evidence digest. It does not select a candidate,
/// accept a proposal, train or install an artifact, or grant authority.
pub fn propose_v2(request: ParameterProposalRequestV2) -> Result<ParameterProposalV2, Error> {
    validate_v2_header(
        &request.proposer_id,
        &request.evaluator_id,
        request.selected_artifact_digest,
        &request.window,
        request.baseline_generation,
        request.candidate_generation,
        request.dataset_digest,
        request.update_rule_digest,
        request.modulator_digest,
        request.modulator_broadcast_digest,
        request.eligibility_digest,
        request.evaluation_digest,
        request.rollback_predecessor_digest,
    )?;
    let norm_profile = build_norm_profile(request.selected_artifact_digest, request.norm_layers)?;
    let candidates = build_candidates(request.candidates, &norm_profile)?;
    let mut proposal = ParameterProposalV2 {
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        selected_artifact_digest: request.selected_artifact_digest,
        window: request.window,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        dataset_digest: request.dataset_digest,
        update_rule_digest: request.update_rule_digest,
        modulator_digest: request.modulator_digest,
        modulator_broadcast_digest: request.modulator_broadcast_digest,
        eligibility_digest: request.eligibility_digest,
        evaluation_digest: request.evaluation_digest,
        rollback_predecessor_digest: request.rollback_predecessor_digest,
        norm_profile,
        candidates,
        proposal_digest: Digest32::ZERO,
        status: ProposalStatus::RequiresIndependentAcceptance,
        authority: AuthorityPosture::DENY_ALL,
    };
    proposal.proposal_digest = digest_parameter_proposal_v2(&proposal)?;
    verify_parameter_proposal_v2(&proposal)?;
    Ok(proposal)
}

pub fn verify_parameter_proposal_v2(proposal: &ParameterProposalV2) -> Result<(), Error> {
    validate_v2_header(
        &proposal.proposer_id,
        &proposal.evaluator_id,
        proposal.selected_artifact_digest,
        &proposal.window,
        proposal.baseline_generation,
        proposal.candidate_generation,
        proposal.dataset_digest,
        proposal.update_rule_digest,
        proposal.modulator_digest,
        proposal.modulator_broadcast_digest,
        proposal.eligibility_digest,
        proposal.evaluation_digest,
        proposal.rollback_predecessor_digest,
    )?;
    if proposal.authority.grants_any() {
        return Err(Error::AuthorityGranted);
    }
    let expected_profile = build_norm_profile(
        proposal.selected_artifact_digest,
        proposal.norm_profile.layers.clone(),
    )?;
    if expected_profile != proposal.norm_profile {
        return Err(Error::NormProfileMismatch);
    }
    let candidate_requests = proposal
        .candidates
        .iter()
        .map(|candidate| ParameterCandidateRequestV2 {
            candidate_id: candidate.candidate_id.clone(),
            kind: candidate.kind,
            parameter_deltas: candidate.parameter_deltas.clone(),
        })
        .collect();
    let expected_candidates = build_candidates(candidate_requests, &proposal.norm_profile)?;
    if expected_candidates != proposal.candidates {
        return Err(Error::NormMetricsMismatch("candidate set".to_string()));
    }
    if proposal.proposal_digest.is_zero()
        || proposal.proposal_digest != digest_parameter_proposal_v2(proposal)?
    {
        return Err(Error::ProposalDigestMismatch);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_v2_header(
    proposer_id: &StableId,
    evaluator_id: &StableId,
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
    baseline_generation: Generation,
    candidate_generation: Generation,
    dataset_digest: Digest32,
    update_rule_digest: Digest32,
    modulator_digest: Digest32,
    modulator_broadcast_digest: Digest32,
    eligibility_digest: Digest32,
    evaluation_digest: Digest32,
    rollback_predecessor_digest: Digest32,
) -> Result<(), Error> {
    if proposer_id == evaluator_id {
        return Err(Error::SelfEvaluation);
    }
    if baseline_generation.next() != Ok(candidate_generation) {
        return Err(Error::GenerationNotExactSuccessor);
    }
    for (name, digest) in [
        ("selected artifact", selected_artifact_digest),
        ("window", window.window_digest),
        ("dataset", dataset_digest),
        ("update rule", update_rule_digest),
        ("modulator", modulator_digest),
        ("modulator broadcast", modulator_broadcast_digest),
        ("eligibility", eligibility_digest),
        ("evaluation", evaluation_digest),
        ("rollback predecessor", rollback_predecessor_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if rollback_predecessor_digest != selected_artifact_digest {
        return Err(Error::RollbackPredecessorMismatch);
    }
    Ok(())
}

fn build_norm_profile(
    selected_artifact_digest: Digest32,
    mut layers: Vec<LayerNormDenominatorV2>,
) -> Result<ParameterNormProfileV2, Error> {
    if !(1..=MAX_NORM_LAYERS).contains(&layers.len()) {
        return Err(Error::NormLayerCountOutOfRange);
    }
    layers.sort_by(|left, right| left.layer_id.cmp(&right.layer_id));
    let mut seen = BTreeSet::new();
    let mut global = 0_u128;
    for layer in &layers {
        if !seen.insert(layer.layer_id.clone()) {
            return Err(Error::DuplicateNormLayer(layer.layer_id.to_string()));
        }
        if layer.baseline_squared_l2_raw_q64 == 0 {
            return Err(Error::ZeroNormDenominator(layer.layer_id.to_string()));
        }
        global = global
            .checked_add(layer.baseline_squared_l2_raw_q64)
            .ok_or(Error::Arithmetic)?;
    }
    let mut profile = ParameterNormProfileV2 {
        profile_digest: Digest32::ZERO,
        per_layer_max_relative_ppm: PER_LAYER_MAX_RELATIVE_PPM,
        global_max_relative_ppm: GLOBAL_MAX_RELATIVE_PPM,
        layers,
        global_baseline_squared_l2_raw_q64: global,
    };
    profile.profile_digest = digest_norm_profile(selected_artifact_digest, &profile)?;
    Ok(profile)
}

fn build_candidates(
    mut requests: Vec<ParameterCandidateRequestV2>,
    profile: &ParameterNormProfileV2,
) -> Result<Vec<ParameterCandidateV2>, Error> {
    if !(1..=MAX_CANDIDATES).contains(&requests.len()) {
        return Err(Error::CandidateCountOutOfRange);
    }
    requests.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    let mut no_change_count = 0_usize;
    let mut total_deltas = 0_usize;
    let mut candidates = Vec::with_capacity(requests.len());
    for mut request in requests {
        if !seen.insert(request.candidate_id.clone()) {
            return Err(Error::DuplicateCandidate(request.candidate_id.to_string()));
        }
        total_deltas = total_deltas
            .checked_add(request.parameter_deltas.len())
            .filter(|count| *count <= MAX_PARAMETER_DELTAS)
            .ok_or(Error::ParameterLimitExceeded)?;
        match request.kind {
            ParameterCandidateKindV2::NoChange => {
                no_change_count += 1;
                if !request.parameter_deltas.is_empty() {
                    return Err(Error::NoChangeHasDeltas(request.candidate_id.to_string()));
                }
            }
            ParameterCandidateKindV2::Update => {
                if request.parameter_deltas.is_empty() {
                    return Err(Error::UpdateHasNoDeltas(request.candidate_id.to_string()));
                }
            }
        }
        request.parameter_deltas.sort_by(|left, right| {
            left.layer_id
                .cmp(&right.layer_id)
                .then_with(|| left.parameter_id.cmp(&right.parameter_id))
        });
        validate_parameter_deltas_v2(&request.parameter_deltas, profile)?;
        let norm_metrics =
            compute_norm_metrics(&request.candidate_id, &request.parameter_deltas, profile)?;
        candidates.push(ParameterCandidateV2 {
            candidate_id: request.candidate_id,
            kind: request.kind,
            parameter_deltas: request.parameter_deltas,
            norm_metrics,
        });
    }
    match no_change_count {
        0 => Err(Error::MissingNoChangeCandidate),
        1 => Ok(candidates),
        _ => Err(Error::MultipleNoChangeCandidates),
    }
}

fn validate_parameter_deltas_v2(
    deltas: &[ParameterDeltaV2],
    profile: &ParameterNormProfileV2,
) -> Result<(), Error> {
    let layer_ids: BTreeSet<_> = profile
        .layers
        .iter()
        .map(|layer| layer.layer_id.clone())
        .collect();
    let mut parameter_ids = BTreeSet::new();
    for delta in deltas {
        if !parameter_ids.insert(delta.parameter_id.clone()) {
            return Err(Error::DuplicateParameter(delta.parameter_id.to_string()));
        }
        if !layer_ids.contains(&delta.layer_id) {
            return Err(Error::MissingNormLayer(delta.layer_id.to_string()));
        }
        if delta.delta == FixedQ32::ZERO {
            return Err(Error::ZeroParameterDelta(delta.parameter_id.to_string()));
        }
        if delta.evidence_digest.is_zero() {
            return Err(Error::EmptyDigest("parameter evidence"));
        }
        if delta.lower_bound > delta.upper_bound {
            return Err(Error::InvertedBounds(delta.parameter_id.to_string()));
        }
        if delta.delta < delta.lower_bound || delta.delta > delta.upper_bound {
            return Err(Error::DeltaOutsideBounds(delta.parameter_id.to_string()));
        }
    }
    Ok(())
}

fn compute_norm_metrics(
    candidate_id: &StableId,
    deltas: &[ParameterDeltaV2],
    profile: &ParameterNormProfileV2,
) -> Result<CandidateNormMetricsV2, Error> {
    let mut delta_by_layer: BTreeMap<StableId, u128> = profile
        .layers
        .iter()
        .map(|layer| (layer.layer_id.clone(), 0))
        .collect();
    for delta in deltas {
        let raw = i128::from(delta.delta.raw());
        let squared = u128::try_from(raw * raw).map_err(|_| Error::Arithmetic)?;
        let Some(layer_total) = delta_by_layer.get_mut(&delta.layer_id) else {
            return Err(Error::MissingNormLayer(delta.layer_id.to_string()));
        };
        *layer_total = layer_total.checked_add(squared).ok_or(Error::Arithmetic)?;
    }
    let mut layers = Vec::with_capacity(profile.layers.len());
    let mut global_delta = 0_u128;
    for denominator in &profile.layers {
        let delta_squared = delta_by_layer
            .get(&denominator.layer_id)
            .copied()
            .ok_or_else(|| Error::MissingNormLayer(denominator.layer_id.to_string()))?;
        if !within_relative_limit(
            delta_squared,
            denominator.baseline_squared_l2_raw_q64,
            profile.per_layer_max_relative_ppm,
        )? {
            return Err(Error::PerLayerTrustRegionExceeded(format!(
                "{}:{}",
                candidate_id, denominator.layer_id
            )));
        }
        global_delta = global_delta
            .checked_add(delta_squared)
            .ok_or(Error::Arithmetic)?;
        layers.push(LayerRelativeNormV2 {
            layer_id: denominator.layer_id.clone(),
            delta_squared_l2_raw_q64: delta_squared,
            baseline_squared_l2_raw_q64: denominator.baseline_squared_l2_raw_q64,
        });
    }
    if !within_relative_limit(
        global_delta,
        profile.global_baseline_squared_l2_raw_q64,
        profile.global_max_relative_ppm,
    )? {
        return Err(Error::GlobalTrustRegionExceeded(candidate_id.to_string()));
    }
    Ok(CandidateNormMetricsV2 {
        layers,
        global_delta_squared_l2_raw_q64: global_delta,
        global_baseline_squared_l2_raw_q64: profile.global_baseline_squared_l2_raw_q64,
    })
}

pub(crate) fn within_relative_limit(
    delta_squared: u128,
    baseline_squared: u128,
    maximum_relative_ppm: u32,
) -> Result<bool, Error> {
    if baseline_squared == 0 {
        return Ok(false);
    }
    let ppm_squared = u128::from(maximum_relative_ppm)
        .checked_mul(u128::from(maximum_relative_ppm))
        .ok_or(Error::Arithmetic)?;
    let denominator_squared = PPM_DENOMINATOR
        .checked_mul(PPM_DENOMINATOR)
        .ok_or(Error::Arithmetic)?;
    let left = delta_squared
        .checked_mul(denominator_squared)
        .ok_or(Error::Arithmetic)?;
    let right = baseline_squared
        .checked_mul(ppm_squared)
        .ok_or(Error::Arithmetic)?;
    Ok(left <= right)
}

fn digest_norm_profile(
    selected_artifact_digest: Digest32,
    profile: &ParameterNormProfileV2,
) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.plasticity.parameter-norm-profile.v1".to_vec();
    bytes.extend_from_slice(selected_artifact_digest.as_array());
    bytes.extend_from_slice(&profile.per_layer_max_relative_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.global_max_relative_ppm.to_be_bytes());
    push_len(&mut bytes, profile.layers.len())?;
    for layer in &profile.layers {
        push_id(&mut bytes, &layer.layer_id)?;
        bytes.extend_from_slice(&layer.baseline_squared_l2_raw_q64.to_be_bytes());
    }
    bytes.extend_from_slice(&profile.global_baseline_squared_l2_raw_q64.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_parameter_proposal_v2(proposal: &ParameterProposalV2) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.plasticity.parameter-proposal.v2".to_vec();
    bytes.extend_from_slice(&PARAMETER_V2.to_be_bytes());
    push_id(&mut bytes, &proposal.proposal_id)?;
    push_id(&mut bytes, &proposal.proposer_id)?;
    push_id(&mut bytes, &proposal.evaluator_id)?;
    bytes.extend_from_slice(proposal.selected_artifact_digest.as_array());
    push_id(&mut bytes, &proposal.window.window_id)?;
    bytes.extend_from_slice(proposal.window.window_digest.as_array());
    bytes.extend_from_slice(&proposal.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&proposal.candidate_generation.get().to_be_bytes());
    for digest in [
        proposal.dataset_digest,
        proposal.update_rule_digest,
        proposal.modulator_digest,
        proposal.modulator_broadcast_digest,
        proposal.eligibility_digest,
        proposal.evaluation_digest,
        proposal.rollback_predecessor_digest,
        proposal.norm_profile.profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, proposal.candidates.len())?;
    for candidate in &proposal.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(candidate_kind_code(candidate.kind));
        push_len(&mut bytes, candidate.parameter_deltas.len())?;
        for delta in &candidate.parameter_deltas {
            push_id(&mut bytes, &delta.layer_id)?;
            push_id(&mut bytes, &delta.parameter_id)?;
            bytes.extend_from_slice(&delta.delta.raw().to_be_bytes());
            bytes.extend_from_slice(&delta.lower_bound.raw().to_be_bytes());
            bytes.extend_from_slice(&delta.upper_bound.raw().to_be_bytes());
            bytes.extend_from_slice(delta.evidence_digest.as_array());
        }
        push_len(&mut bytes, candidate.norm_metrics.layers.len())?;
        for layer in &candidate.norm_metrics.layers {
            push_id(&mut bytes, &layer.layer_id)?;
            bytes.extend_from_slice(&layer.delta_squared_l2_raw_q64.to_be_bytes());
            bytes.extend_from_slice(&layer.baseline_squared_l2_raw_q64.to_be_bytes());
        }
        bytes.extend_from_slice(
            &candidate
                .norm_metrics
                .global_delta_squared_l2_raw_q64
                .to_be_bytes(),
        );
        bytes.extend_from_slice(
            &candidate
                .norm_metrics
                .global_baseline_squared_l2_raw_q64
                .to_be_bytes(),
        );
    }
    bytes.push(match proposal.status {
        ProposalStatus::RequiresIndependentAcceptance => 0,
    });
    bytes.push(0);
    Ok(Digest32::of_bytes(&bytes))
}

fn candidate_kind_code(kind: ParameterCandidateKindV2) -> u8 {
    match kind {
        ParameterCandidateKindV2::NoChange => 0,
        ParameterCandidateKindV2::Update => 1,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), Error> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| Error::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), Error> {
    let value = u32::try_from(value).map_err(|_| Error::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}
