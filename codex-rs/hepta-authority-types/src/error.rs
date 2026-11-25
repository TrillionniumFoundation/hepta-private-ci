use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseError;
use thiserror::Error;

#[derive(Debug, thiserror::Error)]
pub enum CognitiveStoreError {
    #[error("invalid cognitive record: {0}")]
    Invalid(String),
    #[error("cognitive scope denied: {0}")]
    AccessDenied(String),
    #[error("cognitive revision conflict: {0}")]
    Conflict(String),
    #[error("cognitive store is corrupt: {0}")]
    Corrupt(String),
    #[error("cognitive store is unavailable: {0}")]
    Unavailable(String),
}

#[derive(Debug, Error)]
pub enum LocalLeaseOutboxError {
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error("invalid local lease/outbox input: {0}")]
    Invalid(String),
    #[error("local lease/outbox access denied: {0}")]
    AccessDenied(String),
    #[error("local lease/outbox CAS conflict: {0}")]
    CasConflict(String),
    #[error("local lease/outbox stale fence: {0}")]
    StaleFence(String),
    #[error("local lease/outbox journal is corrupt: {0}")]
    Corrupt(String),
    #[error("local lease/outbox transition is invalid: {0}")]
    IllegalTransition(String),
    #[error("local lease/outbox transaction was rolled back: {0}")]
    TransactionAborted(String),
    #[error("local lease/outbox serialization failed: {0}")]
    Serialization(String),
    #[error("local lease/outbox clock failed: {0}")]
    Clock(String),
    #[error("{resource} capacity exceeded; maximum is {maximum}")]
    CapacityExceeded {
        resource: &'static str,
        maximum: usize,
    },
}

/// Errors returned by the production writer and dispatcher boundary.
#[derive(Debug, thiserror::Error)]
pub enum ProductionWriterError {
    #[error("the owner generation is fenced after uncertain checkpoint publication")]
    CheckpointFenced,
    #[error(transparent)]
    Local(#[from] LocalLeaseOutboxError),
    #[error("production authority rejected: {0}")]
    AuthorityRejected(String),
    #[error("production authority lease expired at {deadline}")]
    AuthorityExpired { deadline: u64 },
    #[error("production authority lease does not match Agent {0}")]
    AuthorityAgentMismatch(AgentId),
    #[error("production writer input is invalid: {0}")]
    Invalid(String),
    #[error("production writer durability precondition failed: {0}")]
    Durability(String),
    #[error("production writer receipt is stale or belongs to another authority")]
    StaleReceipt,
    #[error("production writer already has an active owner for this local lease")]
    WriterBusy,
    #[error("final-use authority rejected dispatch: {0}")]
    FinalUse(#[from] FinalUseError),
    #[error("production semantic mutation requires a retained live authority verifier")]
    LiveVerifierRequired,
}
