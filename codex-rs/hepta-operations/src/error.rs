use std::error::Error;
use std::fmt;

use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperationError {
    Missing(StableId),
    Conflict(StableId),
    OperationBindingMismatch(StableId),
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
    Terminal,
    NotClaimed,
    InvalidLease,
    LeaseExpired,
    LeaseTimeRequired,
    StaleClaim,
    AttemptLimitExceeded,
}

impl fmt::Display for OperationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Missing(id) => write!(formatter, "operation is missing: {id}"),
            Self::Conflict(id) => write!(formatter, "operation binding conflict: {id}"),
            Self::OperationBindingMismatch(id) => {
                write!(formatter, "outbox intent is not bound to prepared operation: {id}")
            }
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
                formatter.write_str("reference operation authority witness rejected")
            }
            Self::StaleGeneration => formatter.write_str("operation generation fence is stale"),
            Self::Terminal => formatter.write_str("operation is already terminal"),
            Self::NotClaimed => formatter.write_str("outbox intent is not claimed"),
            Self::InvalidLease => formatter.write_str("outbox lease is invalid"),
            Self::LeaseExpired => formatter.write_str("outbox lease has expired"),
            Self::LeaseTimeRequired => {
                formatter.write_str("leased outbox acknowledgement requires current time")
            }
            Self::StaleClaim => formatter.write_str("outbox claim attempt is stale"),
            Self::AttemptLimitExceeded => {
                formatter.write_str("outbox claim attempt limit exceeded")
            }
        }
    }
}

impl Error for OperationError {}
