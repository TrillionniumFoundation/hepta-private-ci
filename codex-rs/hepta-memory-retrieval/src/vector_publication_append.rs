//! Fail-closed compare-and-publish semantics for durable vector publications.
//!
//! The durable store remains product-owned. This boundary validates the exact
//! tenant and predecessor, accepts an exact committed replay without a second
//! mutation, reconciles an uncertain compare-and-publish result by reloading the
//! current object, and confirms the exact committed publication after success.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::vector_publication::DurableVectorPublicationPortV1;
use crate::vector_publication::VectorIndexPublicationV1;
use crate::vector_publication::VectorPublicationErrorV1;

#[derive(Debug)]
pub enum DurableVectorPublicationAppendErrorV1<E> {
    Validation(VectorPublicationErrorV1),
    CurrentPublicationMismatch {
        expected: Option<Digest32>,
        actual: Option<Digest32>,
    },
    InvalidGenesisSequence {
        actual: u64,
    },
    Port(E),
    CommitOutcomeUnknown {
        publish_error: Option<E>,
        reconciliation_error: Option<E>,
        observed: Option<Digest32>,
    },
    CommittedPublicationMismatch {
        expected: Digest32,
        actual: Option<Digest32>,
    },
}

impl<E: fmt::Display> fmt::Display for DurableVectorPublicationAppendErrorV1<E> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Validation(error) => {
                write!(formatter, "durable vector publication refused: {error}")
            }
            Self::CurrentPublicationMismatch { expected, actual } => write!(
                formatter,
                "durable vector publication current object mismatch: expected {expected:?}, actual {actual:?}",
            ),
            Self::InvalidGenesisSequence { actual } => write!(
                formatter,
                "durable vector publication without a current object must use sequence 1, got {actual}",
            ),
            Self::Port(error) => {
                write!(
                    formatter,
                    "durable vector publication port failed before mutation: {error}"
                )
            }
            Self::CommitOutcomeUnknown {
                publish_error,
                reconciliation_error,
                observed,
            } => {
                write!(
                    formatter,
                    "durable vector publication commit outcome is unknown; observed {observed:?}",
                )?;
                if let Some(error) = publish_error {
                    write!(formatter, "; publish error: {error}")?;
                }
                if let Some(error) = reconciliation_error {
                    write!(formatter, "; reconciliation error: {error}")?;
                }
                Ok(())
            }
            Self::CommittedPublicationMismatch { expected, actual } => write!(
                formatter,
                "durable vector publication committed object mismatch: expected {expected}, actual {actual:?}",
            ),
        }
    }
}

impl<E: StdError + 'static> StdError for DurableVectorPublicationAppendErrorV1<E> {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Validation(error) => Some(error),
            Self::Port(error) => Some(error),
            Self::CommitOutcomeUnknown {
                publish_error,
                reconciliation_error,
                ..
            } => publish_error
                .as_ref()
                .map(|error| error as &(dyn StdError + 'static))
                .or_else(|| {
                    reconciliation_error
                        .as_ref()
                        .map(|error| error as &(dyn StdError + 'static))
                }),
            Self::CurrentPublicationMismatch { .. }
            | Self::InvalidGenesisSequence { .. }
            | Self::CommittedPublicationMismatch { .. } => None,
        }
    }
}

/// Validate and publish one immutable vector-index generation through the
/// selected durable owner.
///
/// `expected_current` is the exact publication digest observed by the caller.
/// The helper independently reloads the current object before mutating. An exact
/// `next` object already committed is acknowledged as an idempotent replay even
/// when the caller still names its predecessor. A failed compare-and-publish is
/// treated as an uncertain commit: the helper reloads the tenant and succeeds
/// only when the exact `next` object is now current. It never blindly publishes
/// a second object. A nominally successful mutation is also reloaded and must
/// equal `next` byte-for-byte at the typed-object level. When either path cannot
/// prove the exact committed object, the error is `CommitOutcomeUnknown` rather
/// than a retry-safe pre-mutation port failure.
pub fn append_vector_publication_checked_v1<P: DurableVectorPublicationPortV1>(
    port: &mut P,
    tenant_digest: Digest32,
    expected_current: Option<Digest32>,
    next: &VectorIndexPublicationV1,
) -> Result<Digest32, DurableVectorPublicationAppendErrorV1<P::Error>> {
    next.validate()
        .map_err(DurableVectorPublicationAppendErrorV1::Validation)?;
    if next.tenant_digest() != tenant_digest {
        return Err(DurableVectorPublicationAppendErrorV1::Validation(
            VectorPublicationErrorV1::TenantMismatch,
        ));
    }

    let current = port
        .load_current(tenant_digest)
        .map_err(DurableVectorPublicationAppendErrorV1::Port)?;
    if current.as_ref() == Some(next) {
        return Ok(next.publication_digest());
    }

    let actual_current = current
        .as_ref()
        .map(VectorIndexPublicationV1::publication_digest);
    if actual_current != expected_current {
        return Err(
            DurableVectorPublicationAppendErrorV1::CurrentPublicationMismatch {
                expected: expected_current,
                actual: actual_current,
            },
        );
    }

    match current.as_ref() {
        Some(current) => current
            .validate_successor(next)
            .map_err(DurableVectorPublicationAppendErrorV1::Validation)?,
        None if next.sequence() != 1 => {
            return Err(
                DurableVectorPublicationAppendErrorV1::InvalidGenesisSequence {
                    actual: next.sequence(),
                },
            );
        }
        None => {}
    }

    if let Err(publish_error) = port.compare_and_publish(tenant_digest, expected_current, next) {
        return match port.load_current(tenant_digest) {
            Ok(Some(committed)) if &committed == next => Ok(next.publication_digest()),
            Ok(observed) => Err(
                DurableVectorPublicationAppendErrorV1::CommitOutcomeUnknown {
                    publish_error: Some(publish_error),
                    reconciliation_error: None,
                    observed: observed
                        .as_ref()
                        .map(VectorIndexPublicationV1::publication_digest),
                },
            ),
            Err(reconciliation_error) => Err(
                DurableVectorPublicationAppendErrorV1::CommitOutcomeUnknown {
                    publish_error: Some(publish_error),
                    reconciliation_error: Some(reconciliation_error),
                    observed: None,
                },
            ),
        };
    }

    let committed = match port.load_current(tenant_digest) {
        Ok(committed) => committed,
        Err(reconciliation_error) => {
            return Err(
                DurableVectorPublicationAppendErrorV1::CommitOutcomeUnknown {
                    publish_error: None,
                    reconciliation_error: Some(reconciliation_error),
                    observed: None,
                },
            );
        }
    };
    if committed.as_ref() != Some(next) {
        return Err(
            DurableVectorPublicationAppendErrorV1::CommittedPublicationMismatch {
                expected: next.publication_digest(),
                actual: committed
                    .as_ref()
                    .map(VectorIndexPublicationV1::publication_digest),
            },
        );
    }
    Ok(next.publication_digest())
}
