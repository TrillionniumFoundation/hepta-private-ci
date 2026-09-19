//! Native, authority-free records for governed self-iteration.
//!
//! These records make the documented candidate boundary executable without
//! granting a generator sandbox, evaluator, selector, merge or release power.
//! The artifact registry remains the durable owner of accepted candidate
//! manifests; this module owns only bounded iteration identity and transitions.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const MAX_ITERATION_CANDIDATES: u16 = 32;
pub const MAX_ITERATION_FILES: u16 = 100;
pub const MAX_ITERATION_DIFF_BYTES: u64 = 1024 * 1024;
pub const MAX_ITERATION_SANDBOXES: u8 = 8;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationEnvelopeV1 {
    pub envelope_id: StableId,
    pub base_commit: Digest32,
    pub base_tree: Digest32,
    pub objective_digest: Digest32,
    pub grammar_digest: Digest32,
    pub maximum_files: u16,
    pub maximum_diff_bytes: u64,
    pub maximum_candidates: u16,
    pub maximum_parallel_sandboxes: u8,
    pub expiry_unix_seconds: u64,
}

impl IterationEnvelopeV1 {
    pub fn validate(&self) -> Result<(), String> {
        if self.base_commit.is_zero()
            || self.base_tree.is_zero()
            || self.objective_digest.is_zero()
            || self.grammar_digest.is_zero()
        {
            return Err("iteration envelope digests must be non-zero".to_string());
        }
        if self.maximum_files == 0 || self.maximum_files > MAX_ITERATION_FILES {
            return Err("iteration file budget is outside the bounded range".to_string());
        }
        if self.maximum_diff_bytes == 0 || self.maximum_diff_bytes > MAX_ITERATION_DIFF_BYTES {
            return Err("iteration diff budget is outside the bounded range".to_string());
        }
        if self.maximum_candidates == 0 || self.maximum_candidates > MAX_ITERATION_CANDIDATES {
            return Err("iteration candidate budget is outside the bounded range".to_string());
        }
        if self.maximum_parallel_sandboxes == 0
            || self.maximum_parallel_sandboxes > MAX_ITERATION_SANDBOXES
        {
            return Err("iteration sandbox budget is outside the bounded range".to_string());
        }
        if self.expiry_unix_seconds == 0 {
            return Err("iteration envelope expiry must be non-zero".to_string());
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IterationCandidateStateV1 {
    Drafted,
    StaticallyValidated,
    SandboxTested,
    IndependentlyEvaluated,
    ReviewRequested,
    AcceptedCandidate,
    Selected,
    Promoted,
    Released,
    Rejected,
    Quarantined,
    Superseded,
}

impl IterationCandidateStateV1 {
    fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Released | Self::Rejected | Self::Quarantined | Self::Superseded
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationCandidateV1 {
    pub candidate_id: StableId,
    pub envelope_id: StableId,
    pub generator_identity: StableId,
    pub semantic_diff_digest: Digest32,
    pub test_plan_digest: Digest32,
    pub rollback_digest: Digest32,
    pub predecessor: Option<StableId>,
    pub state: IterationCandidateStateV1,
}

impl IterationCandidateV1 {
    pub fn validate(&self, envelope: &IterationEnvelopeV1) -> Result<(), String> {
        envelope.validate()?;
        if self.envelope_id != envelope.envelope_id {
            return Err("candidate envelope identity does not match".to_string());
        }
        if self.semantic_diff_digest.is_zero()
            || self.test_plan_digest.is_zero()
            || self.rollback_digest.is_zero()
        {
            return Err("candidate digests must be non-zero".to_string());
        }
        if self.state != IterationCandidateStateV1::Drafted && self.predecessor.is_none() {
            return Err("candidate state requires an exact rollback predecessor".to_string());
        }
        Ok(())
    }

    pub fn transition(
        &mut self,
        envelope: &IterationEnvelopeV1,
        next: IterationCandidateStateV1,
    ) -> Result<(), String> {
        self.validate(envelope)?;
        validate_iteration_transition(self.state, next)?;
        // Validate the proposed state before committing it. A valid Drafted
        // record may lack a predecessor; that does not make a later state valid.
        // Failure must leave the entire candidate, not just its enum, unchanged.
        let mut proposed = self.clone();
        proposed.state = next;
        proposed.validate(envelope)?;
        *self = proposed;
        Ok(())
    }
}

/// Validate a monotonic candidate transition. No transition grants selection,
/// promotion or release authority; those states require external decisions.
pub fn validate_iteration_transition(
    from: IterationCandidateStateV1,
    to: IterationCandidateStateV1,
) -> Result<(), String> {
    if from.is_terminal() {
        return Err("terminal iteration candidate cannot transition".to_string());
    }
    let valid = matches!(
        (from, to),
        (
            IterationCandidateStateV1::Drafted,
            IterationCandidateStateV1::StaticallyValidated
        ) | (
            IterationCandidateStateV1::StaticallyValidated,
            IterationCandidateStateV1::SandboxTested,
        ) | (
            IterationCandidateStateV1::SandboxTested,
            IterationCandidateStateV1::IndependentlyEvaluated,
        ) | (
            IterationCandidateStateV1::IndependentlyEvaluated,
            IterationCandidateStateV1::ReviewRequested,
        ) | (
            IterationCandidateStateV1::ReviewRequested,
            IterationCandidateStateV1::AcceptedCandidate,
        ) | (
            IterationCandidateStateV1::AcceptedCandidate,
            IterationCandidateStateV1::Selected,
        ) | (
            IterationCandidateStateV1::Selected,
            IterationCandidateStateV1::Promoted
        ) | (
            IterationCandidateStateV1::Promoted,
            IterationCandidateStateV1::Released
        ) | (_, IterationCandidateStateV1::Rejected)
            | (_, IterationCandidateStateV1::Quarantined)
            | (_, IterationCandidateStateV1::Superseded)
    );
    valid
        .then_some(())
        .ok_or_else(|| "invalid iteration candidate transition".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::from_array([value; 32])
    }

    fn envelope() -> IterationEnvelopeV1 {
        IterationEnvelopeV1 {
            envelope_id: id("envelope-1"),
            base_commit: digest(1),
            base_tree: digest(2),
            objective_digest: digest(3),
            grammar_digest: digest(4),
            maximum_files: 10,
            maximum_diff_bytes: 1024,
            maximum_candidates: 4,
            maximum_parallel_sandboxes: 2,
            expiry_unix_seconds: 1,
        }
    }

    #[test]
    fn candidate_requires_predecessor_after_draft() {
        let candidate = IterationCandidateV1 {
            candidate_id: id("candidate-1"),
            envelope_id: id("envelope-1"),
            generator_identity: id("generator-1"),
            semantic_diff_digest: digest(5),
            test_plan_digest: digest(6),
            rollback_digest: digest(7),
            predecessor: None,
            state: IterationCandidateStateV1::SandboxTested,
        };
        assert!(candidate.validate(&envelope()).is_err());
    }

    #[test]
    fn transitions_are_monotonic_and_terminal() {
        assert!(
            validate_iteration_transition(
                IterationCandidateStateV1::Drafted,
                IterationCandidateStateV1::StaticallyValidated,
            )
            .is_ok()
        );
        assert!(
            validate_iteration_transition(
                IterationCandidateStateV1::Drafted,
                IterationCandidateStateV1::Promoted,
            )
            .is_err()
        );
        assert!(
            validate_iteration_transition(
                IterationCandidateStateV1::Released,
                IterationCandidateStateV1::Rejected,
            )
            .is_err()
        );
    }

    fn candidate(state: IterationCandidateStateV1, predecessor: bool) -> IterationCandidateV1 {
        IterationCandidateV1 {
            candidate_id: id("candidate-1"),
            envelope_id: id("envelope-1"),
            generator_identity: id("generator-1"),
            semantic_diff_digest: digest(5),
            test_plan_digest: digest(6),
            rollback_digest: digest(7),
            predecessor: predecessor.then(|| id("predecessor-1")),
            state,
        }
    }

    #[test]
    fn failed_draft_promotion_does_not_mutate_the_candidate() {
        let mut value = candidate(IterationCandidateStateV1::Drafted, false);
        let before = value.clone();
        assert!(value.validate(&envelope()).is_ok());
        assert!(value.transition(&envelope(), IterationCandidateStateV1::StaticallyValidated).is_err());
        assert_eq!(value, before);
    }

    #[test]
    fn every_successful_transition_preserves_the_candidate_invariant() {
        use IterationCandidateStateV1::*;
        let states = [
            Drafted, StaticallyValidated, SandboxTested, IndependentlyEvaluated,
            ReviewRequested, AcceptedCandidate, Selected, Promoted, Released,
            Rejected, Quarantined, Superseded,
        ];
        for from in states {
            for to in states {
                for predecessor in [false, true] {
                    let mut value = candidate(from, predecessor);
                    let before = value.clone();
                    match value.transition(&envelope(), to) {
                        Ok(()) => {
                            assert_eq!(value.state, to);
                            assert!(value.validate(&envelope()).is_ok());
                        }
                        Err(_) => assert_eq!(value, before),
                    }
                }
            }
        }
    }

    #[test]
    fn bound_candidate_traverses_the_complete_recorded_path() {
        use IterationCandidateStateV1::*;
        let mut value = candidate(Drafted, true);
        for next in [
            StaticallyValidated, SandboxTested, IndependentlyEvaluated,
            ReviewRequested, AcceptedCandidate, Selected, Promoted, Released,
        ] {
            value.transition(&envelope(), next).expect("valid recorded transition");
            value.validate(&envelope()).expect("preserved invariant");
        }
        let before = value.clone();
        assert!(value.transition(&envelope(), Rejected).is_err());
        assert_eq!(value, before);
    }
}
