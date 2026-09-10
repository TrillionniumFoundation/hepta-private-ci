use std::error::Error;
use std::fmt;

use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperationError {
    Missing(StableId),
    Conflict(StableId),
    InvalidDigest(&'static str),
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
    Terminal,
    NotClaimed,
}

impl fmt::Display for OperationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Missing(id) => write!(formatter, "operation is missing: {id}"),
            Self::Conflict(id) => write!(formatter, "operation binding conflict: {id}"),
            Self::InvalidDigest(field) => write!(formatter, "{field} digest must be nonzero"),
            Self::CapacityExceeded { resource, maximum } => {
                write!(formatter, "{resource} capacity exceeded; maximum is {maximum}")
            }
            Self::InvalidTransition { from, to } => {
                write!(
                    formatter,
                    "invalid operation transition from {from} to {to}"
                )
            }
            Self::AuthorityRejected => {
                formatter.write_str("reference operation authority witness rejected")
            }
            Self::StaleGeneration => formatter.write_str("operation generation fence is stale"),
            Self::Terminal => formatter.write_str("operation is already terminal"),
            Self::NotClaimed => formatter.write_str("outbox intent is not claimed"),
        }
    }
}

impl Error for OperationError {}
