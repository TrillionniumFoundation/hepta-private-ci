use std::error::Error;
use std::fmt;

use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperationError {
    Missing(StableId),
    Conflict(StableId),
    InvalidDigest(&'static str),
    AuthorityWitnessDigestMismatch,
    CapacityExceeded {
        resource: &'static str,
        maximum: usize,
    },
    InvalidTransition {
        from: &'static str,
        to: &'static str,
    },
    AuthorityRejected,
    StaleGeneration,
    StaleLease,
    LeaseUnavailable,
    Terminal,
    TerminalPruned(StableId),
    NotClaimed,
    Storage(String),
    Corrupt(String),
    Unavailable(String),
}

impl fmt::Display for OperationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Missing(id) => write!(formatter, "operation is missing: {id}"),
            Self::Conflict(id) => write!(formatter, "operation binding conflict: {id}"),
            Self::InvalidDigest(field) => write!(formatter, "{field} digest must be nonzero"),
            Self::AuthorityWitnessDigestMismatch => {
                formatter.write_str("reference authority witness semantic digest mismatch")
            }
            Self::CapacityExceeded { resource, maximum } => {
                write!(
                    formatter,
                    "{resource} capacity exceeded; maximum is {maximum}"
                )
            }
            Self::InvalidTransition { from, to } => {
                write!(
                    formatter,
                    "invalid operation transition from {from} to {to}"
                )
            }
            Self::AuthorityRejected => {
                formatter.write_str("operation authority rejected")
            }
            Self::StaleGeneration => formatter.write_str("operation generation fence is stale"),
            Self::StaleLease => formatter.write_str("outbox lease fence is stale"),
            Self::LeaseUnavailable => formatter.write_str("outbox lease is not currently available"),
            Self::Terminal => formatter.write_str("operation is already terminal"),
            Self::TerminalPruned(id) => {
                write!(formatter, "operation terminal identity was retained after pruning: {id}")
            }
            Self::NotClaimed => formatter.write_str("outbox intent is not claimed"),
            Self::Storage(message) => write!(formatter, "durable operation storage error: {message}"),
            Self::Corrupt(message) => write!(formatter, "durable operation store is corrupt: {message}"),
            Self::Unavailable(message) => write!(formatter, "durable operation service unavailable: {message}"),
        }
    }
}

impl Error for OperationError {}
