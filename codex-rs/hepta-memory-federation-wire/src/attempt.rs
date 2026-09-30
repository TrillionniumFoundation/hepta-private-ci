use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::protocol::FederationCancelAckMessageV1;
use crate::protocol::FederationCancelMessageV1;
use crate::protocol::FederationCancellationDispositionV1;
use crate::protocol::FederationCancellationReasonV1;

pub const MAX_FEDERATION_ATTEMPTS: usize = 16_384;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct AttemptIdentity {
    query_id: StableId,
    query_binding_digest: [u8; 32],
}

impl AttemptIdentity {
    fn new(query_id: &StableId, query_binding_digest: Digest32) -> Self {
        Self {
            query_id: query_id.clone(),
            query_binding_digest: *query_binding_digest.as_array(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum AttemptState {
    Pending,
    Cancelled {
        cancellation_id: StableId,
        reason: FederationCancellationReasonV1,
        observed_unix_ms: u64,
    },
    Terminal {
        terminal_digest: Digest32,
        observed_unix_ms: u64,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct AttemptEntry {
    began_unix_ms: u64,
    expires_unix_ms: u64,
    state: AttemptState,
}

/// Bounded peer-side state for cancellation acknowledgement and late-terminal
/// fencing. This registry is transport-neutral; a production host must persist
/// it when restart-surviving cancellation semantics are required by its threat
/// model.
pub struct FederationAttemptRegistryV1 {
    capacity: usize,
    attempts: BTreeMap<AttemptIdentity, AttemptEntry>,
}

impl FederationAttemptRegistryV1 {
    pub fn new(capacity: usize) -> Result<Self, AttemptRegistryError> {
        if capacity == 0 || capacity > MAX_FEDERATION_ATTEMPTS {
            return Err(AttemptRegistryError::InvalidCapacity(capacity));
        }
        Ok(Self {
            capacity,
            attempts: BTreeMap::new(),
        })
    }

    pub fn begin(
        &mut self,
        query_id: &StableId,
        query_binding_digest: Digest32,
        expires_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<(), AttemptRegistryError> {
        require_digest(query_binding_digest)?;
        if now_unix_ms == 0 {
            return Err(AttemptRegistryError::ZeroObservationTime);
        }
        if expires_unix_ms <= now_unix_ms {
            return Err(AttemptRegistryError::Expired);
        }
        self.purge_expired(now_unix_ms);
        let identity = AttemptIdentity::new(query_id, query_binding_digest);
        if self.attempts.contains_key(&identity) {
            return Err(AttemptRegistryError::DuplicateAttempt);
        }
        if self.attempts.len() >= self.capacity {
            return Err(AttemptRegistryError::CapacityExhausted);
        }
        self.attempts.insert(
            identity,
            AttemptEntry {
                began_unix_ms: now_unix_ms,
                expires_unix_ms,
                state: AttemptState::Pending,
            },
        );
        Ok(())
    }

    pub fn observe_terminal(
        &mut self,
        query_id: &StableId,
        query_binding_digest: Digest32,
        terminal_digest: Digest32,
        observed_unix_ms: u64,
    ) -> Result<(), AttemptRegistryError> {
        require_digest(query_binding_digest)?;
        require_digest(terminal_digest)?;
        if observed_unix_ms == 0 {
            return Err(AttemptRegistryError::ZeroObservationTime);
        }
        let identity = AttemptIdentity::new(query_id, query_binding_digest);
        let entry = self
            .attempts
            .get_mut(&identity)
            .ok_or(AttemptRegistryError::UnknownAttempt)?;
        require_monotonic_time(entry.began_unix_ms, observed_unix_ms)?;
        if observed_unix_ms >= entry.expires_unix_ms {
            return Err(AttemptRegistryError::Expired);
        }
        match &entry.state {
            AttemptState::Pending => {
                entry.state = AttemptState::Terminal {
                    terminal_digest,
                    observed_unix_ms,
                };
                Ok(())
            }
            AttemptState::Cancelled { .. } => Err(AttemptRegistryError::Cancelled),
            AttemptState::Terminal {
                terminal_digest: current,
                observed_unix_ms: current_observed,
            } if current == &terminal_digest => {
                require_monotonic_time(*current_observed, observed_unix_ms)
            }
            AttemptState::Terminal { .. } => Err(AttemptRegistryError::ConflictingTerminal),
        }
    }

    pub fn observe_cancel(
        &mut self,
        request: &FederationCancelMessageV1,
        observed_unix_ms: u64,
    ) -> Result<FederationCancelAckMessageV1, AttemptRegistryError> {
        require_digest(request.query_binding_digest)?;
        if observed_unix_ms == 0 {
            return Err(AttemptRegistryError::ZeroObservationTime);
        }
        let identity = AttemptIdentity::new(&request.query_id, request.query_binding_digest);
        if let Some(entry) = self.attempts.get(&identity) {
            require_monotonic_time(entry.began_unix_ms, observed_unix_ms)?;
            if observed_unix_ms >= entry.expires_unix_ms {
                self.attempts.remove(&identity);
            }
        }
        let (disposition, acknowledged_unix_ms) = match self.attempts.get_mut(&identity) {
            None => (
                FederationCancellationDispositionV1::UnknownAttempt,
                observed_unix_ms,
            ),
            Some(entry) => match &entry.state {
                AttemptState::Pending => {
                    entry.state = AttemptState::Cancelled {
                        cancellation_id: request.cancellation_id.clone(),
                        reason: request.reason,
                        observed_unix_ms,
                    };
                    (
                        FederationCancellationDispositionV1::ObservedBeforeTerminal,
                        observed_unix_ms,
                    )
                }
                AttemptState::Cancelled {
                    cancellation_id,
                    reason,
                    observed_unix_ms: first_observed,
                } if cancellation_id == &request.cancellation_id && reason == &request.reason => {
                    require_monotonic_time(*first_observed, observed_unix_ms)?;
                    (
                        FederationCancellationDispositionV1::ObservedBeforeTerminal,
                        *first_observed,
                    )
                }
                AttemptState::Cancelled { .. } => {
                    return Err(AttemptRegistryError::ConflictingCancellation);
                }
                AttemptState::Terminal {
                    observed_unix_ms: terminal_observed,
                    ..
                } => {
                    require_monotonic_time(*terminal_observed, observed_unix_ms)?;
                    (
                        FederationCancellationDispositionV1::TerminalAlreadyObserved,
                        observed_unix_ms,
                    )
                }
            },
        };
        Ok(FederationCancelAckMessageV1 {
            query_id: request.query_id.clone(),
            query_binding_digest: request.query_binding_digest,
            cancellation_id: request.cancellation_id.clone(),
            disposition,
            observed_unix_ms: acknowledged_unix_ms,
        })
    }

    pub fn is_cancelled(&self, query_id: &StableId, query_binding_digest: Digest32) -> bool {
        let identity = AttemptIdentity::new(query_id, query_binding_digest);
        self.attempts
            .get(&identity)
            .is_some_and(|entry| matches!(entry.state, AttemptState::Cancelled { .. }))
    }

    pub fn len(&self) -> usize {
        self.attempts.len()
    }

    pub fn is_empty(&self) -> bool {
        self.attempts.is_empty()
    }

    pub fn purge_expired(&mut self, now_unix_ms: u64) {
        self.attempts
            .retain(|_, entry| entry.expires_unix_ms > now_unix_ms);
    }
}

fn require_digest(digest: Digest32) -> Result<(), AttemptRegistryError> {
    if digest.is_zero() {
        return Err(AttemptRegistryError::EmptyDigest);
    }
    Ok(())
}

fn require_monotonic_time(
    earlier_unix_ms: u64,
    observed_unix_ms: u64,
) -> Result<(), AttemptRegistryError> {
    if observed_unix_ms < earlier_unix_ms {
        return Err(AttemptRegistryError::ClockRegression);
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AttemptRegistryError {
    InvalidCapacity(usize),
    EmptyDigest,
    ZeroObservationTime,
    ClockRegression,
    Expired,
    DuplicateAttempt,
    UnknownAttempt,
    Cancelled,
    ConflictingTerminal,
    ConflictingCancellation,
    CapacityExhausted,
}

impl fmt::Display for AttemptRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidCapacity(value) => write!(formatter, "invalid attempt capacity {value}"),
            Self::EmptyDigest => formatter.write_str("attempt digest cannot be zero"),
            Self::ZeroObservationTime => {
                formatter.write_str("attempt observation time cannot be zero")
            }
            Self::ClockRegression => formatter.write_str("attempt observation time regressed"),
            Self::Expired => formatter.write_str("attempt is expired"),
            Self::DuplicateAttempt => formatter.write_str("attempt identity already exists"),
            Self::UnknownAttempt => formatter.write_str("attempt identity is unknown"),
            Self::Cancelled => formatter.write_str("attempt was cancelled before terminal result"),
            Self::ConflictingTerminal => {
                formatter.write_str("attempt already has a different terminal result")
            }
            Self::ConflictingCancellation => formatter
                .write_str("attempt already has a different cancellation identity or reason"),
            Self::CapacityExhausted => {
                formatter.write_str("attempt registry is full with live entries")
            }
        }
    }
}

impl Error for AttemptRegistryError {}
