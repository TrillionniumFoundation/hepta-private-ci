//! Composition boundary for the smallest typed cognitive loop.
//!
//! This module does not execute a model, publish an artifact, activate a
//! route, or grant effect authority.  It verifies that receipts produced by
//! existing role owners form one ordered, replayable frontier:
//!
//! `Representation -> MemoryRead -> Predictor -> Value -> Decision -> Evaluator`
//!
//! The actual owners remain the existing neuron, retrieval, world-model,
//! value, intuition, and independent-evaluator modules.  The receipt is an
//! integration witness that a circuit composed those owners without silently
//! skipping a role or changing the scope/generation fence.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

pub const COGNITIVE_CLOSURE_SCHEMA_V1: &str = "hepta.cognitive-closure.v1";

/// The fixed role order of the minimum cognitive loop.
pub const COGNITIVE_CLOSURE_ROLES_V1: [CellRoleV1; 6] = [
    CellRoleV1::Representation,
    CellRoleV1::MemoryRead,
    CellRoleV1::Predictor,
    CellRoleV1::Value,
    CellRoleV1::Decision,
    CellRoleV1::Evaluator,
];

/// One immutable integration witness for a complete cognitive closure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveClosureReceiptV1 {
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub initial_frontier_digest: Digest32,
    pub final_frontier_digest: Digest32,
    pub step_receipt_digests: [Digest32; 6],
    pub closure_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CognitiveClosureReceiptV1 {
    pub fn validate(&self) -> Result<(), CognitiveClosureErrorV1> {
        for (label, digest) in [
            ("scope", self.scope_digest),
            ("initial frontier", self.initial_frontier_digest),
            ("final frontier", self.final_frontier_digest),
            ("closure", self.closure_digest),
        ] {
            if digest.is_zero() {
                return Err(CognitiveClosureErrorV1::EmptyDigest(label));
            }
        }
        if self
            .step_receipt_digests
            .iter()
            .any(|digest| digest.is_zero())
        {
            return Err(CognitiveClosureErrorV1::EmptyDigest("step receipt"));
        }
        if self.authority.grants_any() {
            return Err(CognitiveClosureErrorV1::AuthorityGrant);
        }
        Ok(())
    }
}

/// Fail-closed errors from cognitive-loop composition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CognitiveClosureErrorV1 {
    EmptyDigest(&'static str),
    AuthorityGrant,
    WrongStepCount,
    RoleMismatch {
        index: usize,
        expected: CellRoleV1,
        actual: CellRoleV1,
    },
    GenerationMismatch {
        index: usize,
        expected: Generation,
        actual: Generation,
    },
    ScopeMismatch {
        index: usize,
    },
    FrontierMismatch {
        index: usize,
        expected: Digest32,
        actual: Digest32,
    },
    FailedStep {
        index: usize,
        status: CellStepStatusV1,
    },
    InvalidReceipt {
        index: usize,
    },
}

impl fmt::Display for CognitiveClosureErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CognitiveClosureErrorV1 {}

/// Compose the six typed role receipts into one deterministic closure.
///
/// The first receipt must consume `initial_frontier`. Every subsequent role
/// must consume the previous role's output digest. This makes a circuit replay
/// detect dropped, reordered, or stale steps without requiring a new runtime.
pub fn compose_cognitive_closure_v1(
    initial_frontier: Digest32,
    steps: &[CellStepReceiptV1],
) -> Result<CognitiveClosureReceiptV1, CognitiveClosureErrorV1> {
    if initial_frontier.is_zero() {
        return Err(CognitiveClosureErrorV1::EmptyDigest("initial frontier"));
    }
    if steps.len() != COGNITIVE_CLOSURE_ROLES_V1.len() {
        return Err(CognitiveClosureErrorV1::WrongStepCount);
    }

    let first = steps
        .first()
        .ok_or(CognitiveClosureErrorV1::WrongStepCount)?;
    let generation = first.generation;
    let scope_digest = first.scope_digest;
    let mut expected_frontier = initial_frontier;
    let mut step_receipt_digests = [Digest32::ZERO; 6];

    for (index, (step, expected_role)) in steps.iter().zip(COGNITIVE_CLOSURE_ROLES_V1).enumerate() {
        step.validate()
            .map_err(|_| CognitiveClosureErrorV1::InvalidReceipt { index })?;
        if step.role != expected_role {
            return Err(CognitiveClosureErrorV1::RoleMismatch {
                index,
                expected: expected_role,
                actual: step.role,
            });
        }
        if step.generation != generation {
            return Err(CognitiveClosureErrorV1::GenerationMismatch {
                index,
                expected: generation,
                actual: step.generation,
            });
        }
        if step.scope_digest != scope_digest {
            return Err(CognitiveClosureErrorV1::ScopeMismatch { index });
        }
        if step.input_frontier_digest != expected_frontier {
            return Err(CognitiveClosureErrorV1::FrontierMismatch {
                index,
                expected: expected_frontier,
                actual: step.input_frontier_digest,
            });
        }
        if matches!(
            step.status,
            CellStepStatusV1::Rejected | CellStepStatusV1::Failed
        ) {
            return Err(CognitiveClosureErrorV1::FailedStep {
                index,
                status: step.status,
            });
        }
        step_receipt_digests[index] = step
            .content_digest()
            .map_err(|_| CognitiveClosureErrorV1::InvalidReceipt { index })?;
        expected_frontier = step.output_digest;
    }

    let mut bytes = COGNITIVE_CLOSURE_SCHEMA_V1.as_bytes().to_vec();
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(scope_digest.as_array());
    bytes.extend_from_slice(initial_frontier.as_array());
    bytes.extend_from_slice(expected_frontier.as_array());
    for digest in step_receipt_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    let receipt = CognitiveClosureReceiptV1 {
        generation,
        scope_digest,
        initial_frontier_digest: initial_frontier,
        final_frontier_digest: expected_frontier,
        step_receipt_digests,
        closure_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    Ok(receipt)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::StableId;

    fn digest(byte: u8) -> Digest32 {
        Digest32::of_bytes(&[byte])
    }

    fn step(
        role: CellRoleV1,
        input: Digest32,
        output: Digest32,
        scope: Digest32,
    ) -> CellStepReceiptV1 {
        CellStepReceiptV1 {
            cell_id: StableId::new(format!("cell:{}", role.as_str())).expect("cell id"),
            generation: Generation::new(3).expect("generation"),
            scope_digest: scope,
            role,
            capability_digest: digest(30),
            input_frontier_digest: input,
            state_predecessor_digest: digest(31),
            state_successor_digest: digest(32),
            output_digest: output,
            uncertainty_ppm: 0,
            ood_ppm: 0,
            resource_receipt_digest: digest(33),
            evidence_digest: digest(34),
            status: CellStepStatusV1::Accepted,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn complete_steps() -> Vec<CellStepReceiptV1> {
        let scope = digest(20);
        let mut frontier = digest(10);
        let mut steps = Vec::new();
        for (index, role) in COGNITIVE_CLOSURE_ROLES_V1.into_iter().enumerate() {
            let output = digest((40 + index) as u8);
            steps.push(step(role, frontier, output, scope));
            frontier = output;
        }
        steps
    }

    #[test]
    fn composes_ordered_cognitive_closure() {
        let steps = complete_steps();
        let receipt = compose_cognitive_closure_v1(digest(10), &steps).expect("closure");
        assert_eq!(receipt.final_frontier_digest, digest(45));
        assert_eq!(receipt.step_receipt_digests.len(), 6);
        assert!(!receipt.closure_digest.is_zero());
    }

    #[test]
    fn rejects_reordered_or_dropped_steps() {
        let mut steps = complete_steps();
        steps.swap(1, 2);
        assert!(matches!(
            compose_cognitive_closure_v1(digest(10), &steps),
            Err(CognitiveClosureErrorV1::RoleMismatch { .. })
                | Err(CognitiveClosureErrorV1::FrontierMismatch { .. })
        ));
        let steps = complete_steps();
        assert_eq!(
            compose_cognitive_closure_v1(digest(10), &steps[..5]),
            Err(CognitiveClosureErrorV1::WrongStepCount)
        );
    }

    #[test]
    fn rejects_stale_frontier_and_failed_step() {
        let mut steps = complete_steps();
        steps[3].input_frontier_digest = digest(99);
        assert!(matches!(
            compose_cognitive_closure_v1(digest(10), &steps),
            Err(CognitiveClosureErrorV1::FrontierMismatch { index: 3, .. })
        ));

        let mut steps = complete_steps();
        steps[4].status = CellStepStatusV1::Failed;
        assert_eq!(
            compose_cognitive_closure_v1(digest(10), &steps),
            Err(CognitiveClosureErrorV1::FailedStep {
                index: 4,
                status: CellStepStatusV1::Failed,
            })
        );
    }
}
