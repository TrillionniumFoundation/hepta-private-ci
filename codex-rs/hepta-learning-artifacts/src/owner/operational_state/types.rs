// Explicit in-process projection of persisted owner control state.

use codex_hepta_types::StableId;

use super::LearningArtifactOwnerServiceError;

#[derive(Clone, Debug, Eq, PartialEq)]
enum PersistenceState {
    Durable,
    Persisting { since: u64 },
    Unknown { since: u64 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum DrainState {
    Active,
    VolatileRequested { since: u64 },
    Persisting { since: u64 },
    DurableRequested { since: u64 },
    Unknown { since: u64 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum RecoveryState {
    Clear,
    Required { operation_id: StableId, since: u64 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum RequestIdentityState {
    Clear,
    Persisting { operation_id: StableId, since: u64 },
    Unknown { operation_id: StableId, since: u64 },
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(super) struct OwnerOperationalGauges {
    pub(super) recovery_since: Option<u64>,
    pub(super) request_identity_unknown_since: Option<u64>,
    pub(super) withdrawal_blocked_since: Option<u64>,
    pub(super) drain_started_at: Option<u64>,
    pub(super) drain_durable: bool,
}

#[derive(Debug)]
pub(super) struct OwnerOperationalState {
    withdrawal: PersistenceState,
    drain: DrainState,
    recovery: RecoveryState,
    request_identity: RequestIdentityState,
}
