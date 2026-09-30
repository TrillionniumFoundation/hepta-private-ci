//! Fail-closed validation and append semantics for durable retrieval lifecycle facts.
//!
//! The storage port remains product-owned. This module prevents a caller from
//! using that port to regress an exact execution identity, reuse a stale writer
//! fence, append at the wrong global frontier, or turn an unknown external
//! outcome back into a safely replayable prepared request.

use std::error::Error as StdError;
use std::fmt;

use crate::DurableDecisionPortV1;
use crate::DurableDecisionRecordV1;
use crate::LifecycleErrorV1;
use crate::QuarantinedUnknownOutcomeV1;
use crate::RetrievalLifecyclePhaseV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableDecisionTransitionErrorV1 {
    InvalidRecord(LifecycleErrorV1),
    FrontierExhausted,
    FrontierMismatch {
        expected: u64,
        actual: u64,
    },
    LatestFrontierAhead {
        latest: u64,
        expected: u64,
    },
    IdentityMismatch,
    StaleWriterFence {
        latest: u64,
        next: u64,
    },
    MissingQuarantineEvidence,
    UnexpectedQuarantineEvidence,
    QuarantineIdentityMismatch,
    InvalidPhaseTransition {
        previous: RetrievalLifecyclePhaseV1,
        next: RetrievalLifecyclePhaseV1,
    },
}

impl fmt::Display for DurableDecisionTransitionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurableDecisionTransitionErrorV1 {}

#[derive(Debug)]
pub enum DurableDecisionAppendErrorV1<E> {
    Transition(DurableDecisionTransitionErrorV1),
    Port(E),
    CommittedFrontierMismatch {
        expected: u64,
        actual: u64,
    },
}

impl<E: fmt::Display> fmt::Display for DurableDecisionAppendErrorV1<E> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Transition(error) => {
                write!(formatter, "durable lifecycle transition refused: {error}")
            }
            Self::Port(error) => write!(formatter, "durable lifecycle port failed: {error}"),
            Self::CommittedFrontierMismatch { expected, actual } => write!(
                formatter,
                "durable lifecycle port committed frontier {actual}, expected {expected}",
            ),
        }
    }
}

impl<E: StdError + 'static> StdError for DurableDecisionAppendErrorV1<E> {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Transition(error) => Some(error),
            Self::Port(error) => Some(error),
            Self::CommittedFrontierMismatch { .. } => None,
        }
    }
}

/// Validate one append against the latest fact for the same exact execution
/// identity and the caller's current global compare-and-append frontier.
///
/// `latest` may have a smaller frontier than `expected_frontier` because other
/// execution identities can append to the same durable journal between two
/// facts for this identity. It may never be ahead of the caller's current
/// frontier. Phase skips are allowed only in the forward direction because a
/// stronger durable native observation can establish an intermediate fact that
/// was not separately materialized.
pub fn validate_durable_decision_append_v1(
    latest: Option<&DurableDecisionRecordV1>,
    expected_frontier: u64,
    next: &DurableDecisionRecordV1,
    quarantine: Option<&QuarantinedUnknownOutcomeV1>,
) -> Result<(), DurableDecisionTransitionErrorV1> {
    validate_record_and_quarantine(next, quarantine)?;

    let required_frontier = expected_frontier
        .checked_add(1)
        .ok_or(DurableDecisionTransitionErrorV1::FrontierExhausted)?;
    if next.frontier != required_frontier {
        return Err(DurableDecisionTransitionErrorV1::FrontierMismatch {
            expected: required_frontier,
            actual: next.frontier,
        });
    }

    let Some(latest) = latest else {
        return Ok(());
    };
    latest
        .validate()
        .map_err(DurableDecisionTransitionErrorV1::InvalidRecord)?;
    if latest.frontier > expected_frontier {
        return Err(DurableDecisionTransitionErrorV1::LatestFrontierAhead {
            latest: latest.frontier,
            expected: expected_frontier,
        });
    }
    if latest.identity != next.identity {
        return Err(DurableDecisionTransitionErrorV1::IdentityMismatch);
    }
    if next.writer_fence < latest.writer_fence {
        return Err(DurableDecisionTransitionErrorV1::StaleWriterFence {
            latest: latest.writer_fence,
            next: next.writer_fence,
        });
    }
    if !phase_transition_allowed(latest.phase, next.phase) {
        return Err(
            DurableDecisionTransitionErrorV1::InvalidPhaseTransition {
                previous: latest.phase,
                next: next.phase,
            },
        );
    }
    Ok(())
}

/// Validate and append through one existing durable owner. Unknown outcomes use
/// the port's quarantine operation; all other phases use compare-and-append.
/// An exact record already returned by `load_latest` is acknowledged as an
/// idempotent committed replay without calling the mutating port operation.
/// A port error is an uncertain commit result and must be reconciled by loading
/// the exact execution identity before any retry.
pub fn append_durable_decision_checked_v1<P: DurableDecisionPortV1>(
    port: &mut P,
    expected_frontier: u64,
    next: &DurableDecisionRecordV1,
    quarantine: Option<&QuarantinedUnknownOutcomeV1>,
) -> Result<u64, DurableDecisionAppendErrorV1<P::Error>> {
    validate_record_and_quarantine(next, quarantine)
        .map_err(DurableDecisionAppendErrorV1::Transition)?;
    let latest = port
        .load_latest(&next.identity)
        .map_err(DurableDecisionAppendErrorV1::Port)?;
    if latest.as_ref() == Some(next) {
        return Ok(next.frontier);
    }
    validate_durable_decision_append_v1(latest.as_ref(), expected_frontier, next, quarantine)
        .map_err(DurableDecisionAppendErrorV1::Transition)?;

    let committed = match quarantine {
        Some(outcome) => port.quarantine_unknown_outcome(
            expected_frontier,
            outcome,
            next.writer_fence,
            &next.payload_digest,
        ),
        None => port.compare_and_append(expected_frontier, next),
    }
    .map_err(DurableDecisionAppendErrorV1::Port)?;

    if committed != next.frontier {
        return Err(DurableDecisionAppendErrorV1::CommittedFrontierMismatch {
            expected: next.frontier,
            actual: committed,
        });
    }
    Ok(committed)
}

fn validate_record_and_quarantine(
    next: &DurableDecisionRecordV1,
    quarantine: Option<&QuarantinedUnknownOutcomeV1>,
) -> Result<(), DurableDecisionTransitionErrorV1> {
    next.validate()
        .map_err(DurableDecisionTransitionErrorV1::InvalidRecord)?;
    match (next.phase, quarantine) {
        (RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome, None) => {
            Err(DurableDecisionTransitionErrorV1::MissingQuarantineEvidence)
        }
        (RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome, Some(outcome)) => {
            if outcome.identity() == &next.identity {
                Ok(())
            } else {
                Err(DurableDecisionTransitionErrorV1::QuarantineIdentityMismatch)
            }
        }
        (_, Some(_)) => Err(DurableDecisionTransitionErrorV1::UnexpectedQuarantineEvidence),
        (_, None) => Ok(()),
    }
}

fn phase_transition_allowed(
    previous: RetrievalLifecyclePhaseV1,
    next: RetrievalLifecyclePhaseV1,
) -> bool {
    use RetrievalLifecyclePhaseV1 as Phase;

    if previous == Phase::AcknowledgedRetrieval || previous == next {
        return false;
    }
    if previous == Phase::QuarantinedUnknownOutcome {
        return matches!(
            next,
            Phase::PublishedRetrieval
                | Phase::ConsumedRetrieval
                | Phase::AcknowledgedRetrieval
        );
    }
    if next == Phase::QuarantinedUnknownOutcome {
        return matches!(
            previous,
            Phase::QualifiedDecision | Phase::PublishedRetrieval | Phase::ConsumedRetrieval
        );
    }
    phase_rank(next) > phase_rank(previous)
}

fn phase_rank(phase: RetrievalLifecyclePhaseV1) -> u8 {
    use RetrievalLifecyclePhaseV1 as Phase;

    match phase {
        Phase::ValidatedRequest => 0,
        Phase::TenantBoundExecution => 1,
        Phase::SealedSnapshot => 2,
        Phase::QualifiedDecision => 3,
        Phase::PublishedRetrieval => 4,
        Phase::ConsumedRetrieval => 5,
        Phase::AcknowledgedRetrieval => 6,
        Phase::QuarantinedUnknownOutcome => 7,
    }
}
