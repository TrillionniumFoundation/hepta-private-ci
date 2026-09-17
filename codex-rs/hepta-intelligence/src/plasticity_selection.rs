//! Independent selection over already authenticated plasticity candidates.
//!
//! This module cannot install or activate artifacts. It converts future-window
//! evaluation evidence into a deterministic selection receipt that an external
//! selector/runtime may sign and adopt. The no-change baseline is mandatory.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, FixedQ32, Generation, StableId};

const MAX_SELECTION_CANDIDATES: usize = 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySelectionCandidateV1 {
    pub candidate_id: StableId,
    pub artifact_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub future_window_digest: Digest32,
    pub utility_delta_vs_baseline: FixedQ32,
    pub eligible: bool,
    pub regression_free: bool,
    pub no_change: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySelectionRequestV1 {
    pub selection_id: StableId,
    pub proposal_digest: Digest32,
    pub current_artifact_digest: Digest32,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub generator_id: StableId,
    pub evaluator_id: StableId,
    pub selector_id: StableId,
    pub candidates: Vec<PlasticitySelectionCandidateV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticitySelectionDecisionV1 {
    KeepBaseline { candidate_id: StableId },
    SelectUpdate { candidate_id: StableId, artifact_digest: Digest32 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySelectionReceiptV1 {
    pub selection_id: StableId,
    pub proposal_digest: Digest32,
    pub decision: PlasticitySelectionDecisionV1,
    pub baseline_artifact_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub future_window_digest: Digest32,
    pub selector_id: StableId,
    pub selection_digest: Digest32,
    pub activation_forbidden: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticitySelectionErrorV1 {
    EmptyDigest(&'static str),
    CandidateCountOutOfRange,
    DuplicateCandidate(String),
    RoleCollision,
    NonSuccessorGeneration,
    MissingNoChangeBaseline,
    MultipleNoChangeBaselines,
    InvalidNoChangeBaseline,
    MixedFutureWindows,
}

impl fmt::Display for PlasticitySelectionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticitySelectionErrorV1 {}

pub fn select_plasticity_candidate_v1(
    mut request: PlasticitySelectionRequestV1,
) -> Result<PlasticitySelectionReceiptV1, PlasticitySelectionErrorV1> {
    for (label, digest) in [
        ("proposal", request.proposal_digest),
        ("current artifact", request.current_artifact_digest),
    ] {
        if digest.is_zero() {
            return Err(PlasticitySelectionErrorV1::EmptyDigest(label));
        }
    }
    if request.baseline_generation.next() != Ok(request.candidate_generation) {
        return Err(PlasticitySelectionErrorV1::NonSuccessorGeneration);
    }
    if request.generator_id == request.evaluator_id
        || request.generator_id == request.selector_id
        || request.evaluator_id == request.selector_id
    {
        return Err(PlasticitySelectionErrorV1::RoleCollision);
    }
    if !(1..=MAX_SELECTION_CANDIDATES).contains(&request.candidates.len()) {
        return Err(PlasticitySelectionErrorV1::CandidateCountOutOfRange);
    }

    request
        .candidates
        .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut ids = BTreeSet::new();
    let mut baseline = None;
    let mut future_window = None;
    for candidate in &request.candidates {
        if !ids.insert(candidate.candidate_id.clone()) {
            return Err(PlasticitySelectionErrorV1::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.artifact_digest.is_zero() {
            return Err(PlasticitySelectionErrorV1::EmptyDigest("candidate artifact"));
        }
        if candidate.evaluation_digest.is_zero() {
            return Err(PlasticitySelectionErrorV1::EmptyDigest("candidate evaluation"));
        }
        if candidate.future_window_digest.is_zero() {
            return Err(PlasticitySelectionErrorV1::EmptyDigest("future window"));
        }
        match future_window {
            None => future_window = Some(candidate.future_window_digest),
            Some(expected) if expected != candidate.future_window_digest => {
                return Err(PlasticitySelectionErrorV1::MixedFutureWindows)
            }
            Some(_) => {}
        }
        if candidate.no_change {
            if baseline.replace(candidate).is_some() {
                return Err(PlasticitySelectionErrorV1::MultipleNoChangeBaselines);
            }
        }
    }
    let baseline = baseline.ok_or(PlasticitySelectionErrorV1::MissingNoChangeBaseline)?;
    if baseline.artifact_digest != request.current_artifact_digest
        || baseline.utility_delta_vs_baseline != FixedQ32::ZERO
        || !baseline.eligible
        || !baseline.regression_free
    {
        return Err(PlasticitySelectionErrorV1::InvalidNoChangeBaseline);
    }

    // Only a strictly positive, independently eligible, regression-free update
    // may beat the mandatory no-change baseline. Ties remain on the baseline.
    let selected = request
        .candidates
        .iter()
        .filter(|candidate| {
            !candidate.no_change
                && candidate.eligible
                && candidate.regression_free
                && candidate.utility_delta_vs_baseline > FixedQ32::ZERO
        })
        .max_by(|left, right| {
            left.utility_delta_vs_baseline
                .cmp(&right.utility_delta_vs_baseline)
                .then_with(|| right.candidate_id.cmp(&left.candidate_id))
        });
    let decision = selected.map_or_else(
        || PlasticitySelectionDecisionV1::KeepBaseline {
            candidate_id: baseline.candidate_id.clone(),
        },
        |candidate| PlasticitySelectionDecisionV1::SelectUpdate {
            candidate_id: candidate.candidate_id.clone(),
            artifact_digest: candidate.artifact_digest,
        },
    );
    let future_window_digest = future_window.expect("non-empty candidate set");

    let mut bytes = b"hepta.intelligence.plasticity-selection.v1\0".to_vec();
    push_id(&mut bytes, &request.selection_id);
    bytes.extend_from_slice(request.proposal_digest.as_array());
    bytes.extend_from_slice(request.current_artifact_digest.as_array());
    bytes.extend_from_slice(&request.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.candidate_generation.get().to_be_bytes());
    push_id(&mut bytes, &request.generator_id);
    push_id(&mut bytes, &request.evaluator_id);
    push_id(&mut bytes, &request.selector_id);
    bytes.extend_from_slice(future_window_digest.as_array());
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.extend_from_slice(candidate.artifact_digest.as_array());
        bytes.extend_from_slice(candidate.evaluation_digest.as_array());
        bytes.extend_from_slice(candidate.future_window_digest.as_array());
        bytes.extend_from_slice(&candidate.utility_delta_vs_baseline.raw().to_be_bytes());
        bytes.push(u8::from(candidate.eligible));
        bytes.push(u8::from(candidate.regression_free));
        bytes.push(u8::from(candidate.no_change));
    }
    match &decision {
        PlasticitySelectionDecisionV1::KeepBaseline { candidate_id } => {
            bytes.push(0);
            push_id(&mut bytes, candidate_id);
        }
        PlasticitySelectionDecisionV1::SelectUpdate {
            candidate_id,
            artifact_digest,
        } => {
            bytes.push(1);
            push_id(&mut bytes, candidate_id);
            bytes.extend_from_slice(artifact_digest.as_array());
        }
    }

    Ok(PlasticitySelectionReceiptV1 {
        selection_id: request.selection_id,
        proposal_digest: request.proposal_digest,
        decision,
        baseline_artifact_digest: request.current_artifact_digest,
        rollback_predecessor_digest: request.current_artifact_digest,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        future_window_digest,
        selector_id: request.selector_id,
        selection_digest: Digest32::of_bytes(&bytes),
        activation_forbidden: true,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }
    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }
    fn candidate(
        id_value: &str,
        artifact: Digest32,
        delta: i64,
        no_change: bool,
    ) -> PlasticitySelectionCandidateV1 {
        PlasticitySelectionCandidateV1 {
            candidate_id: id(id_value),
            artifact_digest: artifact,
            evaluation_digest: digest(&format!("evaluation:{id_value}")),
            future_window_digest: digest("future-window"),
            utility_delta_vs_baseline: FixedQ32::from_raw(delta),
            eligible: true,
            regression_free: true,
            no_change,
        }
    }

    fn request(update_delta: i64) -> PlasticitySelectionRequestV1 {
        let current = digest("current");
        PlasticitySelectionRequestV1 {
            selection_id: id("selection:1"),
            proposal_digest: digest("proposal"),
            current_artifact_digest: current,
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            generator_id: id("generator:1"),
            evaluator_id: id("evaluator:1"),
            selector_id: id("selector:1"),
            candidates: vec![
                candidate("candidate:baseline", current, 0, true),
                candidate("candidate:update", digest("update"), update_delta, false),
            ],
        }
    }

    #[test]
    fn selects_strictly_better_future_window_candidate() {
        let receipt = select_plasticity_candidate_v1(request(1)).expect("selection");
        assert!(matches!(
            receipt.decision,
            PlasticitySelectionDecisionV1::SelectUpdate { .. }
        ));
        assert_eq!(receipt.rollback_predecessor_digest, digest("current"));
        assert!(receipt.activation_forbidden);
    }

    #[test]
    fn no_change_baseline_wins_ties_and_regressions() {
        for delta in [0, -1] {
            let receipt = select_plasticity_candidate_v1(request(delta)).expect("selection");
            assert!(matches!(
                receipt.decision,
                PlasticitySelectionDecisionV1::KeepBaseline { .. }
            ));
        }
    }

    #[test]
    fn generator_evaluator_selector_roles_must_be_distinct() {
        let mut value = request(1);
        value.selector_id = value.generator_id.clone();
        assert_eq!(
            select_plasticity_candidate_v1(value),
            Err(PlasticitySelectionErrorV1::RoleCollision)
        );
    }

    #[test]
    fn no_change_baseline_is_mandatory() {
        let mut value = request(1);
        value.candidates.retain(|candidate| !candidate.no_change);
        assert_eq!(
            select_plasticity_candidate_v1(value),
            Err(PlasticitySelectionErrorV1::MissingNoChangeBaseline)
        );
    }
}
