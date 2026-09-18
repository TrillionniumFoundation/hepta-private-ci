use std::error::Error;
use std::fmt;

use codex_hepta_contracts::FinalUseError;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperationError {
    Missing(StableId),
    Conflict(StableId),
    InvalidDigest(&'static str),
    InvalidRequest(&'static str),
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
    Authority(FinalUseError),
    StaleGeneration,
    StaleAuthorityEpoch,
    StaleLease,
    Terminal,
    NotClaimed,
    Unavailable,
    DispatchAlreadyStarted,
    Storage(String),
    Corrupt(String),
}

impl fmt::Display for OperationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Missing(id) => write!(formatter, "operation is missing: {id}"),
            Self::Conflict(id) => write!(formatter, "operation binding conflict: {id}"),
            Self::InvalidDigest(field) => write!(formatter, "{field} digest must be nonzero"),
            Self::InvalidRequest(message) => write!(formatter, "invalid operation request: {message}"),
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
            Self::Authority(error) => write!(formatter, "final-use authority rejected: {error}"),
            Self::StaleGeneration => formatter.write_str("operation generation fence is stale"),
            Self::StaleAuthorityEpoch => formatter.write_str("operation authority epoch is stale"),
            Self::StaleLease => formatter.write_str("operation outbox lease or fence is stale"),
            Self::Terminal => formatter.write_str("operation is already terminal"),
            Self::NotClaimed => formatter.write_str("outbox intent is not claimed"),
            Self::Unavailable => formatter.write_str("operation is not currently dispatchable"),
            Self::DispatchAlreadyStarted => formatter.write_str(
                "dispatch already crossed the durable no-blind-retry boundary; reconcile instead",
            ),
            Self::Storage(message) => write!(formatter, "operation storage unavailable: {message}"),
            Self::Corrupt(message) => write!(formatter, "operation storage is corrupt: {message}"),
        }
    }
}

impl Error for OperationError {}
