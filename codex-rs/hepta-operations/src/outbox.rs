use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::OperationError;

pub const MAX_MODEL_OUTBOX_RECORDS: usize = 16_384;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutboxIntent {
    pub intent_id: StableId,
    pub operation_id: StableId,
    pub destination: StableId,
    pub payload_digest: Digest32,
}

impl OutboxIntent {
    fn validate(&self) -> Result<(), OperationError> {
        if self.payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("outbox payload"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OutboxState {
    Pending,
    Claimed { owner_generation: Generation },
    Acknowledged { acknowledgement_digest: Digest32 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct OutboxRecord {
    intent: OutboxIntent,
    state: OutboxState,
}

/// Bounded in-memory outbox reference model.
///
/// Claims do not expire or survive process exit. A durable implementation must
/// add transactional persistence, claim leases and crash/reopen takeover.
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

    pub fn claim(
        &mut self,
        intent_id: &StableId,
        owner_generation: Generation,
    ) -> Result<&OutboxIntent, OperationError> {
        let record = self
            .records
            .get_mut(intent_id)
            .ok_or_else(|| OperationError::Missing(intent_id.clone()))?;
        match record.state {
            OutboxState::Pending => {
                record.state = OutboxState::Claimed { owner_generation };
            }
            OutboxState::Claimed {
                owner_generation: existing,
            } if existing == owner_generation => {}
            OutboxState::Claimed { .. } => return Err(OperationError::StaleGeneration),
            OutboxState::Acknowledged { .. } => return Err(OperationError::Terminal),
        }
        Ok(&record.intent)
    }

    pub fn acknowledge(
        &mut self,
        intent_id: &StableId,
        owner_generation: Generation,
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
                owner_generation: existing,
            } if existing == owner_generation => {
                record.state = OutboxState::Acknowledged {
                    acknowledgement_digest,
                };
                Ok(())
            }
            OutboxState::Claimed { .. } => Err(OperationError::StaleGeneration),
            OutboxState::Pending => Err(OperationError::NotClaimed),
            OutboxState::Acknowledged {
                acknowledgement_digest: existing,
            } if existing == acknowledgement_digest => Ok(()),
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
}

#[cfg(test)]
#[path = "outbox_tests.rs"]
mod tests;
