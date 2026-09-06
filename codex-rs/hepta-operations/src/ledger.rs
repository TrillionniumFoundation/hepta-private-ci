use std::collections::BTreeMap;
use std::collections::btree_map::Entry;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::AuthorityWitness;
use crate::OperationError;
use crate::OperationKey;
use crate::OperationRecord;
use crate::OperationState;
use crate::ReconciliationOutcome;

/// In-memory deterministic model of the durable operation ledger.
///
/// Production storage implements the same transitions transactionally and can
/// restore this state from append-only records.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct OperationLedger {
    records: BTreeMap<StableId, OperationRecord>,
}

impl OperationLedger {
    pub fn begin(
        &mut self,
        key: OperationKey,
        owner_generation: Generation,
    ) -> Result<&OperationRecord, OperationError> {
        let id = key.id.clone();
        match self.records.entry(id.clone()) {
            Entry::Occupied(entry) => {
                let existing = entry.into_mut();
                if existing.key == key && existing.owner_generation == owner_generation {
                    Ok(existing)
                } else {
                    Err(OperationError::Conflict(id))
                }
            }
            Entry::Vacant(entry) => Ok(entry.insert(OperationRecord {
                key,
                owner_generation,
                revision: first_revision(),
                state: OperationState::Pending,
            })),
        }
    }

    pub fn authorize(
        &mut self,
        operation_id: &StableId,
        witness: &AuthorityWitness,
        now_unix_ms: u64,
    ) -> Result<&OperationRecord, OperationError> {
        let record = self.record_mut(operation_id)?;
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if !matches!(&record.state, OperationState::Pending) {
            return invalid(&record.state, "authorized");
        }
        if !witness.validates(&record.key, now_unix_ms) {
            return Err(OperationError::AuthorityRejected);
        }
        advance(record)?;
        record.state = OperationState::Authorized {
            witness_digest: witness.witness_digest,
            authority_generation: witness.authority_generation,
        };
        Ok(record)
    }

    pub fn record_dispatch(
        &mut self,
        operation_id: &StableId,
        dispatch_digest: Digest32,
    ) -> Result<&OperationRecord, OperationError> {
        if dispatch_digest.is_zero() {
            return Err(OperationError::Conflict(operation_id.clone()));
        }
        let record = self.record_mut(operation_id)?;
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if !matches!(&record.state, OperationState::Authorized { .. }) {
            return invalid(&record.state, "dispatched");
        }
        advance(record)?;
        record.state = OperationState::Dispatched { dispatch_digest };
        Ok(record)
    }

    pub fn mark_indeterminate(
        &mut self,
        operation_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<&OperationRecord, OperationError> {
        let record = self.record_mut(operation_id)?;
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if !matches!(&record.state, OperationState::Dispatched { .. }) {
            return invalid(&record.state, "indeterminate");
        }
        advance(record)?;
        record.state = OperationState::Indeterminate { reason_digest };
        Ok(record)
    }

    pub fn observe_terminal(
        &mut self,
        operation_id: &StableId,
        outcome: ReconciliationOutcome,
        outcome_digest: Digest32,
        observer_generation: Generation,
    ) -> Result<&OperationRecord, OperationError> {
        let record = self.record_mut(operation_id)?;
        if observer_generation != record.owner_generation {
            return Err(OperationError::StaleGeneration);
        }
        if record.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if !matches!(
            &record.state,
            OperationState::Dispatched { .. } | OperationState::Indeterminate { .. }
        ) {
            return invalid(&record.state, "terminal_observation");
        }
        advance(record)?;
        record.state = match outcome {
            ReconciliationOutcome::Applied => OperationState::Applied { outcome_digest },
            ReconciliationOutcome::NotApplied => OperationState::NotApplied { outcome_digest },
            ReconciliationOutcome::Quarantined => OperationState::Quarantined {
                reason_digest: outcome_digest,
            },
        };
        Ok(record)
    }

    pub fn get(&self, operation_id: &StableId) -> Option<&OperationRecord> {
        self.records.get(operation_id)
    }

    pub fn len(&self) -> usize {
        self.records.len()
    }

    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }

    fn record_mut(
        &mut self,
        operation_id: &StableId,
    ) -> Result<&mut OperationRecord, OperationError> {
        self.records
            .get_mut(operation_id)
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))
    }
}

fn first_revision() -> Revision {
    match Revision::new(1) {
        Ok(revision) => revision,
        Err(error) => unreachable!("constant first revision is invalid: {error}"),
    }
}

fn advance(record: &mut OperationRecord) -> Result<(), OperationError> {
    record.revision = record
        .revision
        .next()
        .map_err(|_| OperationError::Conflict(record.key.id.clone()))?;
    Ok(())
}

fn invalid<T>(state: &OperationState, to: &'static str) -> Result<T, OperationError> {
    Err(OperationError::InvalidTransition {
        from: state.label(),
        to,
    })
}

#[cfg(test)]
#[path = "ledger_tests.rs"]
mod tests;
