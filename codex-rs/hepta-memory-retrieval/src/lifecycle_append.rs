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
    /// The initial exact-identity read failed before any mutation was attempted.
    Port(E),
    /// A mutating call or its confirmation could not prove the exact record.
    /// Callers must reconcile the exact execution identity; blind retry is not
    /// safe because the durable effect may already have occurred.
    CommitOutcomeUnknown {
        append_error: Option<E>,
        reconciliation_error: Option<E>,
        observed_frontier: Option<u64>,
        observed_phase: Option<RetrievalLifecyclePhaseV1>,
    },
    CommittedFrontierMismatch {
        expected: u64,
        actual: u64,
    },
    /// The port reported success and the expected frontier, but the required
    /// exact-identity readback did not return the exact candidate record.
    CommittedRecordMismatch {
        expected_frontier: u64,
        actual_frontier: Option<u64>,
        actual_phase: Option<RetrievalLifecyclePhaseV1>,
    },
}

impl<E: fmt::Display> fmt::Display for DurableDecisionAppendErrorV1<E> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Transition(error) => {
                write!(formatter, "durable lifecycle transition refused: {error}")
            }
            Self::Port(error) => {
                write!(formatter, "durable lifecycle port failed before mutation: {error}")
            }
            Self::CommitOutcomeUnknown {
                append_error,
                reconciliation_error,
                observed_frontier,
                observed_phase,
            } => {
                write!(
                    formatter,
                    "durable lifecycle commit outcome is unknown; observed frontier {observed_frontier:?}, phase {observed_phase:?}",
                )?;
                if let Some(error) = append_error {
                    write!(formatter, "; append error: {error}")?;
                }
                if let Some(error) = reconciliation_error {
                    write!(formatter, "; reconciliation error: {error}")?;
                }
                Ok(())
            }
            Self::CommittedFrontierMismatch { expected, actual } => write!(
                formatter,
                "durable lifecycle port committed frontier {actual}, expected {expected}",
            ),
            Self::CommittedRecordMismatch {
                expected_frontier,
                actual_frontier,
                actual_phase,
            } => write!(
                formatter,
                "durable lifecycle exact readback mismatch: expected frontier {expected_frontier}, observed frontier {actual_frontier:?}, phase {actual_phase:?}",
            ),
        }
    }
}

impl<E: StdError + 'static> StdError for DurableDecisionAppendErrorV1<E> {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Transition(error) => Some(error),
            Self::Port(error) => Some(error),
            Self::CommitOutcomeUnknown {
                append_error,
                reconciliation_error,
                ..
            } => append_error
                .as_ref()
                .map(|error| error as &(dyn StdError + 'static))
                .or_else(|| {
                    reconciliation_error
                        .as_ref()
                        .map(|error| error as &(dyn StdError + 'static))
                }),
            Self::CommittedFrontierMismatch { .. }
            | Self::CommittedRecordMismatch { .. } => None,
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
///
/// Every attempted mutation is reconciled through an exact-identity read. A
/// mutating port error succeeds only when that read proves the exact candidate
/// record, covering acknowledgement loss without a second write. A successful
/// port return is also confirmed byte-for-byte at the typed-record level. Any
/// result that cannot prove the exact record is typed as commit-outcome unknown
/// or committed-record mismatch and must never trigger a blind retry.
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

    let append = match quarantine {
        Some(outcome) => port.quarantine_unknown_outcome(
            expected_frontier,
            outcome,
            next.writer_fence,
            &next.payload_digest,
        ),
        None => port.compare_and_append(expected_frontier, next),
    };

    let committed_frontier = match append {
        Ok(frontier) => frontier,
        Err(append_error) => {
            return match port.load_latest(&next.identity) {
                Ok(Some(committed)) if &committed == next => Ok(next.frontier),
                Ok(observed) => {
                    let (observed_frontier, observed_phase) = observed_identity(&observed);
                    Err(DurableDecisionAppendErrorV1::CommitOutcomeUnknown {
                        append_error: Some(append_error),
                        reconciliation_error: None,
                        observed_frontier,
                        observed_phase,
                    })
                }
                Err(reconciliation_error) => {
                    Err(DurableDecisionAppendErrorV1::CommitOutcomeUnknown {
                        append_error: Some(append_error),
                        reconciliation_error: Some(reconciliation_error),
                        observed_frontier: None,
                        observed_phase: None,
                    })
                }
            };
        }
    };

    if committed_frontier != next.frontier {
        return Err(DurableDecisionAppendErrorV1::CommittedFrontierMismatch {
            expected: next.frontier,
            actual: committed_frontier,
        });
    }

    let observed = match port.load_latest(&next.identity) {
        Ok(observed) => observed,
        Err(reconciliation_error) => {
            return Err(DurableDecisionAppendErrorV1::CommitOutcomeUnknown {
                append_error: None,
                reconciliation_error: Some(reconciliation_error),
                observed_frontier: None,
                observed_phase: None,
            });
        }
    };
    if observed.as_ref() != Some(next) {
        let (actual_frontier, actual_phase) = observed_identity(&observed);
        return Err(DurableDecisionAppendErrorV1::CommittedRecordMismatch {
            expected_frontier: next.frontier,
            actual_frontier,
            actual_phase,
        });
    }
    Ok(committed_frontier)
}

fn observed_identity(
    observed: &Option<DurableDecisionRecordV1>,
) -> (Option<u64>, Option<RetrievalLifecyclePhaseV1>) {
    observed
        .as_ref()
        .map_or((None, None), |record| (Some(record.frontier), Some(record.phase)))
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
