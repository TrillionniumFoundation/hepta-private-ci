use std::collections::BTreeMap;
use std::collections::btree_map::Entry;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::OperationError;
use crate::OperationKey;
use crate::OperationRecord;
use crate::OperationState;
use crate::ReconciliationOutcome;
use crate::ReferenceAuthorityWitness;

pub const MAX_MODEL_OPERATION_RECORDS: usize = 16_384;

/// In-memory deterministic reference model of the target operation ledger.
///
/// Production storage must implement these transitions transactionally and
/// prove crash/reopen behavior independently. Cloning this value is not a
/// persistence test.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationLedger {
    records: BTreeMap<StableId, OperationRecord>,
    maximum_records: usize,
}

impl Default for OperationLedger {
    fn default() -> Self {
        Self::new(MAX_MODEL_OPERATION_RECORDS)
    }
}

impl OperationLedger {
    #[must_use]
    pub fn new(maximum_records: usize) -> Self {
        Self {
            records: BTreeMap::new(),
            maximum_records: maximum_records.min(MAX_MODEL_OPERATION_RECORDS),
        }
    }

    pub fn begin(
        &mut self,
        key: OperationKey,
        owner_generation: Generation,
    ) -> Result<&OperationRecord, OperationError> {
        key.validate()?;
        let id = key.id.clone();
        if !self.records.contains_key(&id) && self.records.len() >= self.maximum_records {
            return Err(OperationError::CapacityExceeded {
                resource: "reference operation ledger",
                maximum: self.maximum_records,
            });
        }
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
        witness: &ReferenceAuthorityWitness,
        now_unix_ms: u64,
    ) -> Result<&OperationRecord, OperationError> {
        let record = self.record_mut(operation_id)?;
        if !witness.validates(&record.key, now_unix_ms) {
            return Err(OperationError::AuthorityRejected);
        }
        match record.state.clone() {
            OperationState::Pending => {
                advance(record)?;
                record.state = OperationState::Authorized {
                    witness_digest: witness.witness_digest(),
                    authority_generation: witness.authority_generation(),
                };
                Ok(record)
            }
            OperationState::Authorized {
                witness_digest,
                authority_generation,
            } if witness_digest == witness.witness_digest()
                && authority_generation == witness.authority_generation() =>
            {
                Ok(record)
            }
            state if state.is_terminal() => Err(OperationError::Terminal),
            state => invalid(&state, "authorized"),
        }
    }

    pub fn record_dispatch(
        &mut self,
        operation_id: &StableId,
        dispatch_digest: Digest32,
    ) -> Result<&OperationRecord, OperationError> {
        if dispatch_digest.is_zero() {
            return Err(OperationError::InvalidDigest("dispatch"));
        }
        let record = self.record_mut(operation_id)?;
        match record.state.clone() {
            OperationState::Authorized { .. } => {
                advance(record)?;
                record.state = OperationState::Dispatched { dispatch_digest };
                Ok(record)
            }
            OperationState::Dispatched {
                dispatch_digest: existing,
            } if existing == dispatch_digest => Ok(record),
            state if state.is_terminal() => Err(OperationError::Terminal),
            state => invalid(&state, "dispatched"),
        }
    }

    pub fn mark_indeterminate(
        &mut self,
        operation_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<&OperationRecord, OperationError> {
        if reason_digest.is_zero() {
            return Err(OperationError::InvalidDigest("indeterminate reason"));
        }
        let record = self.record_mut(operation_id)?;
        match record.state.clone() {
            OperationState::Dispatched { .. } => {
                advance(record)?;
                record.state = OperationState::Indeterminate { reason_digest };
                Ok(record)
            }
            OperationState::Indeterminate {
                reason_digest: existing,
            } if existing == reason_digest => Ok(record),
            state if state.is_terminal() => Err(OperationError::Terminal),
            state => invalid(&state, "indeterminate"),
        }
    }

    pub fn observe_terminal(
        &mut self,
        operation_id: &StableId,
        outcome: ReconciliationOutcome,
        outcome_digest: Digest32,
        observer_generation: Generation,
    ) -> Result<&OperationRecord, OperationError> {
        if outcome_digest.is_zero() {
            return Err(OperationError::InvalidDigest("terminal outcome"));
        }
        let record = self.record_mut(operation_id)?;
        if observer_generation != record.owner_generation {
            return Err(OperationError::StaleGeneration);
        }
        if terminal_matches(&record.state, outcome, outcome_digest) {
            return Ok(record);
        }
        match record.state.clone() {
            OperationState::Dispatched { .. } | OperationState::Indeterminate { .. } => {
                advance(record)?;
                record.state = terminal_state(outcome, outcome_digest);
                Ok(record)
            }
            state if state.is_terminal() => Err(OperationError::Terminal),
            state => invalid(&state, "terminal_observation"),
        }
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

fn terminal_state(outcome: ReconciliationOutcome, digest: Digest32) -> OperationState {
    match outcome {
        ReconciliationOutcome::Applied => OperationState::Applied {
            outcome_digest: digest,
        },
        ReconciliationOutcome::NotApplied => OperationState::NotApplied {
            outcome_digest: digest,
        },
        ReconciliationOutcome::Quarantined => OperationState::Quarantined {
            reason_digest: digest,
        },
    }
}

fn terminal_matches(
    state: &OperationState,
    outcome: ReconciliationOutcome,
    digest: Digest32,
) -> bool {
    matches!(
        (state, outcome),
        (
            OperationState::Applied {
                outcome_digest: existing
            },
            ReconciliationOutcome::Applied
        ) if *existing == digest
    ) || matches!(
        (state, outcome),
        (
            OperationState::NotApplied {
                outcome_digest: existing
            },
            ReconciliationOutcome::NotApplied
        ) if *existing == digest
    ) || matches!(
        (state, outcome),
        (
            OperationState::Quarantined {
                reason_digest: existing
            },
            ReconciliationOutcome::Quarantined
        ) if *existing == digest
    )
}

fn first_revision() -> Revision {
    match Revision::new(/*value*/ 1) {
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
