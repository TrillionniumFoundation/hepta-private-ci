//! Deterministic bounded parameter candidate generation.
//!
//! This is the first native generator path: callers provide ranked learning
//! signals, not a preconstructed candidate set. The generator deterministically
//! emits no-change plus bounded prefix candidates and then relies on the existing
//! V2 verifier for trust-region and canonical integrity enforcement.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::Error;
use crate::ParameterCandidateKindV2;
use crate::ParameterCandidateRequestV2;
use crate::ParameterDeltaV2;
use crate::ParameterProposalRequestV2;
use crate::ParameterProposalV2;
use crate::propose_v2;
use crate::types::MAX_CANDIDATES;
use crate::types::MAX_PARAMETER_DELTAS;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterLearningSignalV1 {
    pub layer_id: StableId,
    pub parameter_id: StableId,
    /// Signed deterministic update pressure. Magnitude ranks the signal and the
    /// sign determines update direction.
    pub score_raw: i64,
    pub lower_bound: FixedQ32,
    pub upper_bound: FixedQ32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CandidateGeneratorConfigV1 {
    /// Maximum absolute raw Q32 step emitted for any parameter.
    pub maximum_step_raw: i64,
    /// Maximum number of update candidates in addition to explicit no-change.
    pub maximum_update_candidates: usize,
}

impl Default for CandidateGeneratorConfigV1 {
    fn default() -> Self {
        Self {
            maximum_step_raw: 1,
            maximum_update_candidates: 4,
        }
    }
}

pub fn generate_parameter_proposal_v2(
    mut request: ParameterProposalRequestV2,
    mut signals: Vec<ParameterLearningSignalV1>,
    config: CandidateGeneratorConfigV1,
) -> Result<ParameterProposalV2, Error> {
    if !request.candidates.is_empty() {
        return Err(Error::GeneratorCandidatesMustBeEmpty);
    }
    if config.maximum_step_raw <= 0
        || config.maximum_update_candidates == 0
        || config.maximum_update_candidates >= MAX_CANDIDATES
    {
        return Err(Error::InvalidGeneratorConfig);
    }
    if signals.is_empty() || signals.len() > MAX_PARAMETER_DELTAS {
        return Err(Error::GeneratorSignalCountOutOfRange);
    }

    signals.sort_by(|left, right| {
        signal_magnitude(right.score_raw)
            .cmp(&signal_magnitude(left.score_raw))
            .then_with(|| left.layer_id.cmp(&right.layer_id))
            .then_with(|| left.parameter_id.cmp(&right.parameter_id))
    });

    let mut seen = std::collections::BTreeSet::new();
    for signal in &signals {
        if !seen.insert(signal.parameter_id.clone()) {
            return Err(Error::DuplicateParameter(signal.parameter_id.to_string()));
        }
        if signal.score_raw == 0 {
            return Err(Error::ZeroGeneratorSignal(signal.parameter_id.to_string()));
        }
        if signal.evidence_digest.is_zero() {
            return Err(Error::EmptyDigest("parameter evidence"));
        }
        if signal.lower_bound > signal.upper_bound {
            return Err(Error::InvertedBounds(signal.parameter_id.to_string()));
        }
    }

    let update_count = config
        .maximum_update_candidates
        .min(signals.len())
        .min(MAX_CANDIDATES - 1);
    let mut candidates = Vec::with_capacity(update_count + 1);
    candidates.push(ParameterCandidateRequestV2 {
        candidate_id: StableId::new("candidate:auto:no-change")
            .map_err(|_| Error::Arithmetic)?,
        kind: ParameterCandidateKindV2::NoChange,
        parameter_deltas: Vec::new(),
    });

    for width in 1..=update_count {
        let mut deltas = Vec::with_capacity(width);
        for signal in signals.iter().take(width) {
            let magnitude = signal_magnitude(signal.score_raw)
                .min(u64::try_from(config.maximum_step_raw).map_err(|_| Error::Arithmetic)?);
            let signed = if signal.score_raw < 0 {
                -i64::try_from(magnitude).map_err(|_| Error::Arithmetic)?
            } else {
                i64::try_from(magnitude).map_err(|_| Error::Arithmetic)?
            };
            let delta = FixedQ32::from_raw(signed)
                .clamp(signal.lower_bound, signal.upper_bound)
                .map_err(|_| Error::Arithmetic)?;
            if delta == FixedQ32::ZERO {
                return Err(Error::GeneratorSignalClampedToZero(
                    signal.parameter_id.to_string(),
                ));
            }
            deltas.push(ParameterDeltaV2 {
                layer_id: signal.layer_id.clone(),
                parameter_id: signal.parameter_id.clone(),
                delta,
                lower_bound: signal.lower_bound,
                upper_bound: signal.upper_bound,
                evidence_digest: signal.evidence_digest,
            });
        }
        candidates.push(ParameterCandidateRequestV2 {
            candidate_id: StableId::new(format!("candidate:auto:{width:02}"))
                .map_err(|_| Error::Arithmetic)?,
            kind: ParameterCandidateKindV2::Update,
            parameter_deltas: deltas,
        });
    }

    request.candidates = candidates;
    propose_v2(request)
}

fn signal_magnitude(value: i64) -> u64 {
    value.unsigned_abs()
}
