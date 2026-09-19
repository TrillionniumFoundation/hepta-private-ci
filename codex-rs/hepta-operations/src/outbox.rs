use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::OperationError;
use crate::OperationIntent;
use crate::OperationRecord;

pub const MAX_MODEL_OUTBOX_RECORDS: usize = 16_384;
pub const MAX_MODEL_OUTBOX_ATTEMPTS: u32 = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutboxIntent {
    pub intent_id: StableId,
    pub operation_id: StableId,
    pub destination: StableId,
    pub payload_digest: Digest32,
    /// Canonical digest of the complete bound `OperationIntent`.
    pub operation_digest: Digest32,
}

impl OutboxIntent {
    pub fn for_operation(intent_id: StableId, operation: &OperationIntent) -> Self {
        Self {
            intent_id,
            operation_id: operation.key.id.clone(),
            destination: operation.destination.clone(),
            payload_digest: operation.key.payload_digest,
            operation_digest: operation.semantic_digest(),
        }
    }

    fn validate(&self) -> Result<(), OperationError> {
        if self.payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox payload"));
        }
        if self.operation_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox operation"));
        }
        Ok(())
    }

    fn matches_operation(&self, record: &OperationRecord) -> bool {
        let Some(operation) = record.intent.as_ref() else {
            return false;
        };
        self.operation_id == record.key.id
            && self.destination == operation.destination
            && self.payload_digest == record.key.payload_digest
            && self.operation_digest == operation.semantic_digest()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OutboxState {
    Pending,
    Claimed {
        owner_generation: Generation,
        attempt: u32,
        lease_expires_at_unix_ms: u64,
    },
    Acknowledged {
        owner_generation: Generation,
        attempt: u32,
        acknowledgement_digest: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct OutboxRecord {
    intent: OutboxIntent,
    state: OutboxState,
}

/// Bounded in-memory outbox reference model.
///
/// Leased claims model bounded expiry/takeover semantics, but nothing in this
/// value survives process exit. The durable owner must persist the equivalent
/// transition and prove crash/reopen behavior.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Outbox {
    records: BTreeMap<StableId, OutboxRecord>,
    maximum_records: usize,
}

impl Default for Outbox {
    fn default() -> Self {
        Self::new(MAX_MODEL_OUTBOX_RECORDS)
    }
}

impl Outbox {
    #[must_use]
    pub fn new(maximum_records: usize) -> Self {
        Self {
            records: BTreeMap::new(),
            maximum_records: maximum_records.min(MAX_MODEL_OUTBOX_RECORDS),
        }
    }

    pub fn enqueue(&mut self, intent: OutboxIntent) -> Result<(), OperationError> {
        intent.validate()?;
        if let Some(existing) = self.records.get(&intent.intent_id) {
            if existing.intent == intent {
                return Ok(());
            }
            return Err(OperationError::Conflict(intent.intent_id));
        }
        if self.records.len() >= self.maximum_records {
            return Err(OperationError::CapacityExceeded {
                resource: "reference outbox",
                maximum: self.maximum_records,
            });
        }
        self.records.insert(
            intent.intent_id.clone(),
            OutboxRecord {
                intent,
                state: OutboxState::Pending,
            },
        );
        Ok(())
    }

    /// Enqueue only when the outbox row is bound to the exact prepared
    /// operation semantics. Legacy ledger records cannot pass this check.
    pub fn enqueue_for_operation(
        &mut self,
        operation: &OperationRecord,
        intent: OutboxIntent,
    ) -> Result<(), OperationError> {
        intent.validate()?;
        if !intent.matches_operation(operation) {
            return Err(OperationError::OperationBindingMismatch(
                intent.intent_id.clone(),
            ));
        }
        self.enqueue(intent)
    }

    /// Compatibility claim with a non-expiring in-memory lease.
    ///
    /// Durable/product code must use a real persisted lease. This method is
    /// retained so existing reference-model callers keep their old semantics.
    pub fn claim(
        &mut self,
        intent_id: &StableId,
        owner_generation: Generation,
    ) -> Result<&OutboxIntent, OperationError> {
        self.claim_until(intent_id, owner_generation, 1, u64::MAX)
    }

    /// Claim or take over an expired outbox lease.
    ///
    /// Exact replay is idempotent only for the same generation and exact lease
    /// deadline. A different generation may take over only after expiry and
    /// must be strictly newer than the previous generation.
    pub fn claim_with_lease(
        &mut self,
        intent_id: &StableId,
        owner_generation: Generation,
        now_unix_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<&OutboxIntent, OperationError> {
        if lease_duration_ms == 0 {
            return Err(OperationError::InvalidLease);
        }
        let lease_expires_at_unix_ms = now_unix_ms
            .checked_add(lease_duration_ms)
            .ok_or(OperationError::InvalidLease)?;
        let (attempt, existing_state) = {
            let record = self
                .records
                .get(intent_id)
                .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
            let attempt = match record.state {
                OutboxState::Pending => 1,
                OutboxState::Claimed {
                    owner_generation: existing_generation,
                    attempt,
                    lease_expires_at_unix_ms: existing_expiry,
                } => {
                    if existing_generation == owner_generation {
                        if now_unix_ms >= existing_expiry {
                            return Err(OperationError::LeaseExpired);
                        }
                        if existing_expiry != lease_expires_at_unix_ms {
                            return Err(OperationError::Conflict(intent_id.clone()));
                        }
                        attempt
                    } else {
                        if now_unix_ms < existing_expiry || owner_generation <= existing_generation {
                            return Err(OperationError::StaleGeneration);
                        }
                        attempt
                            .checked_add(1)
                            .filter(|value| *value <= MAX_MODEL_OUTBOX_ATTEMPTS)
                            .ok_or(OperationError::AttemptLimitExceeded)?
                    }
                }
                OutboxState::Acknowledged { .. } => return Err(OperationError::Terminal),
            };
            (attempt, record.state)
        };
        if matches!(
            existing_state,
            OutboxState::Claimed {
                owner_generation: existing_generation,
                attempt: existing_attempt,
                lease_expires_at_unix_ms: existing_expiry,
            } if existing_generation == owner_generation
                && existing_attempt == attempt
                && existing_expiry == lease_expires_at_unix_ms
        ) {
            return self
                .records
                .get(intent_id)
                .map(|record| &record.intent)
                .ok_or_else(|| OperationError::Missing(intent_id.clone()));
        }
        let record = self
            .records
            .get_mut(intent_id)
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
        if matches!(record.state, OutboxState::Acknowledged { .. }) {
            return Err(OperationError::Terminal);
        }
        record.state = OutboxState::Claimed {
            owner_generation,
            attempt,
            lease_expires_at_unix_ms,
        };
        Ok(&record.intent)
    }

    pub fn renew_claim(
        &mut self,
        intent_id: &StableId,
        owner_generation: Generation,
        attempt: u32,
        now_unix_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<&OutboxIntent, OperationError> {
        if lease_duration_ms == 0 {
            return Err(OperationError::InvalidLease);
        }
        let new_expiry = now_unix_ms
            .checked_add(lease_duration_ms)
            .ok_or(OperationError::InvalidLease)?;
        let record = self
            .records
            .get_mut(intent_id)
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
        match record.state {
            OutboxState::Claimed {
                owner_generation: existing_generation,
                attempt: existing_attempt,
                lease_expires_at_unix_ms: existing_expiry,
            } => {
                if existing_generation != owner_generation {
                    return Err(OperationError::StaleGeneration);
                }
                if existing_attempt != attempt {
                    return Err(OperationError::StaleClaim);
                }
                if now_unix_ms >= existing_expiry {
                    return Err(OperationError::LeaseExpired);
                }
                if new_expiry <= existing_expiry {
                    return Err(OperationError::InvalidLease);
                }
                record.state = OutboxState::Claimed {
                    owner_generation,
                    attempt,
                    lease_expires_at_unix_ms: new_expiry,
                };
                Ok(&record.intent)
            }
            OutboxState::Pending => Err(OperationError::NotClaimed),
            OutboxState::Acknowledged { .. } => Err(OperationError::Terminal),
        }
    }

    pub fn acknowledge(
        &mut self,
        intent_id: &StableId,
        owner_generation: Generation,
        acknowledgement_digest: Digest32,
    ) -> Result<(), OperationError> {
        let attempt = match self
            .records
            .get(intent_id)
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?
            .state
        {
            OutboxState::Claimed {
                owner_generation: existing_generation,
                attempt,
                lease_expires_at_unix_ms: u64::MAX,
            } if existing_generation == owner_generation => attempt,
            OutboxState::Claimed {
                owner_generation: existing_generation,
                ..
            } if existing_generation != owner_generation => {
                return Err(OperationError::StaleGeneration);
            }
            OutboxState::Claimed { .. } => return Err(OperationError::LeaseTimeRequired),
            OutboxState::Pending => return Err(OperationError::NotClaimed),
            OutboxState::Acknowledged {
                owner_generation: existing_generation,
                attempt,
                acknowledgement_digest: existing_digest,
            } if existing_generation == owner_generation
                && existing_digest == acknowledgement_digest =>
            {
                return Ok(());
            }
            OutboxState::Acknowledged {
                owner_generation: existing_generation,
                ..
            } if existing_generation != owner_generation => {
                return Err(OperationError::StaleGeneration);
            }
            OutboxState::Acknowledged { .. } => {
                return Err(OperationError::Conflict(intent_id.clone()));
            }
        };
        self.acknowledge_claim(
            intent_id,
            owner_generation,
            attempt,
            0,
            acknowledgement_digest,
        )
    }

    pub fn acknowledge_claim(
        &mut self,
        intent_id: &StableId,
        owner_generation: Generation,
        attempt: u32,
        now_unix_ms: u64,
        acknowledgement_digest: Digest32,
    ) -> Result<(), OperationError> {
        if acknowledgement_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox acknowledgement"));
        }
        let record = self
            .records
            .get_mut(intent_id)
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
        match record.state {
            OutboxState::Claimed {
                owner_generation: existing_generation,
                attempt: existing_attempt,
                lease_expires_at_unix_ms,
            } if existing_generation == owner_generation && existing_attempt == attempt => {
                if now_unix_ms >= lease_expires_at_unix_ms {
                    return Err(OperationError::LeaseExpired);
                }
                record.state = OutboxState::Acknowledged {
                    owner_generation,
                    attempt,
                    acknowledgement_digest,
                };
                Ok(())
            }
            OutboxState::Claimed {
                owner_generation: existing_generation,
                ..
            } if existing_generation != owner_generation => Err(OperationError::StaleGeneration),
            OutboxState::Claimed { .. } => Err(OperationError::StaleClaim),
            OutboxState::Pending => Err(OperationError::NotClaimed),
            OutboxState::Acknowledged {
                owner_generation: existing_generation,
                attempt: existing_attempt,
                acknowledgement_digest: existing_digest,
            } if existing_generation == owner_generation
                && existing_attempt == attempt
                && existing_digest == acknowledgement_digest =>
            {
                Ok(())
            }
            OutboxState::Acknowledged {
                owner_generation: existing_generation,
                ..
            } if existing_generation != owner_generation => Err(OperationError::StaleGeneration),
            OutboxState::Acknowledged {
                attempt: existing_attempt,
                ..
            } if existing_attempt != attempt => Err(OperationError::StaleClaim),
            OutboxState::Acknowledged { .. } => Err(OperationError::Conflict(intent_id.clone())),
        }
    }

    pub fn state(&self, intent_id: &StableId) -> Option<&OutboxState> {
        self.records.get(intent_id).map(|record| &record.state)
    }

    pub fn len(&self) -> usize {
        self.records.len()
    }

    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }

    fn claim_until(
        &mut self,
        intent_id: &StableId,
        owner_generation: Generation,
        attempt: u32,
        lease_expires_at_unix_ms: u64,
    ) -> Result<&OutboxIntent, OperationError> {
        let record = self
            .records
            .get_mut(intent_id)
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
        match record.state {
            OutboxState::Pending => {
                record.state = OutboxState::Claimed {
                    owner_generation,
                    attempt,
                    lease_expires_at_unix_ms,
                };
            }
            OutboxState::Claimed {
                owner_generation: existing_generation,
                attempt: existing_attempt,
                lease_expires_at_unix_ms: existing_expiry,
            } if existing_generation == owner_generation
                && existing_attempt == attempt
                && existing_expiry == lease_expires_at_unix_ms => {}
            OutboxState::Claimed { .. } => return Err(OperationError::StaleClaim),
            OutboxState::Acknowledged { .. } => return Err(OperationError::Terminal),
        }
        Ok(&record.intent)
    }
}

#[cfg(test)]
#[path = "outbox_tests.rs"]
mod tests;
