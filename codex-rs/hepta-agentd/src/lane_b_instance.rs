//! Private Unix qualification of identity under the original local single writer.
//! No wire protocol, authority, cross-Fleet recovery, rollback or clone witness.
use super::*;
use std::io::Read;
use std::path::Path;

const MAX_CREATION_OPERATIONS: usize = 1_024;

#[derive(Clone, Copy)]
pub(super) enum InstanceMode {
    Legacy,
    Protected,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct InstanceKey {
    pub(crate) lineage: String,
    pub(crate) sequence: u64,
    pub(crate) run_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct InstanceHandle {
    pub(crate) key: InstanceKey,
    pub(crate) activation: u64,
    pub(crate) revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct InstanceReceipt {
    pub(crate) handle: InstanceHandle,
    pub(crate) receipt: RunReceipt,
    pub(crate) released: bool,
}

pub(crate) enum InstanceMutation {
    Attach(Box<ContextAttachment>),
    Dispatch,
    Observe {
        phase: RunPhase,
        terminal_observed: bool,
    },
    Release,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Creation {
    snapshot: RunSnapshot,
    sequence: u64,
    issued_activation: u64,
    released: Option<RunRecord>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct InstanceBook {
    lineage: String,
    allocated: u64,
    activation: u64,
    operations: BTreeMap<String, Creation>,
    current: BTreeMap<String, u64>,
}

/// A private, nonserializable permit created only after exact owner validation.
#[derive(Debug)]
pub(super) struct InstancePermit {
    run_id: String,
    sequence: u64,
}

impl InstanceBook {
    fn fresh() -> Result<Self, AgentRunError> {
        let mut bytes = [0_u8; 32];
        std::fs::File::open("/dev/urandom")
            .and_then(|mut entropy| entropy.read_exact(&mut bytes))
            .map_err(|_| AgentRunError::PersistenceUnavailable)?;
        let lineage = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
        Ok(Self {
            lineage,
            allocated: 0,
            activation: 1,
            operations: BTreeMap::new(),
            current: BTreeMap::new(),
        })
    }

    pub(super) fn advance_activation(&mut self) -> Result<(), AgentRunError> {
        self.activation = self
            .activation
            .checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        Ok(())
    }

    pub(super) fn validate(&self, runs: &BTreeMap<String, RunRecord>) -> Result<(), AgentRunError> {
        validate_digest(&self.lineage, "owner lineage")?;
        if self.activation == 0
            || self.operations.len() > MAX_CREATION_OPERATIONS
            || self.current.len() != runs.len()
        {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        let mut sequences = std::collections::BTreeSet::new();
        for (operation, creation) in &self.operations {
            validate_identity(operation, "creation operation")?;
            validate_snapshot_fields(&creation.snapshot)?;
            if creation.issued_activation == 0
                || creation.issued_activation > self.activation
                || creation.sequence == 0
                || creation.sequence > self.allocated
                || !sequences.insert(creation.sequence)
            {
                return Err(AgentRunError::PersistenceUnavailable);
            }
            if let Some(retired) = &creation.released {
                super::journal::validate_record(&creation.snapshot.run_id, retired)?;
                if retired.snapshot != creation.snapshot || !retired.phase.closed() {
                    return Err(AgentRunError::PersistenceUnavailable);
                }
            } else if self.current.get(&creation.snapshot.run_id) != Some(&creation.sequence)
                || runs
                    .get(&creation.snapshot.run_id)
                    .is_none_or(|run| run.snapshot != creation.snapshot)
            {
                return Err(AgentRunError::PersistenceUnavailable);
            }
        }
        // No eviction is implemented. Full history must cover the whole high-water range.
        if u64::try_from(sequences.len()).map_err(|_| AgentRunError::ArithmeticOverflow)?
            != self.allocated
        {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        for (run_id, sequence) in &self.current {
            if !self.operations.values().any(|creation| {
                creation.sequence == *sequence
                    && creation.snapshot.run_id == *run_id
                    && creation.released.is_none()
            }) {
                return Err(AgentRunError::PersistenceUnavailable);
            }
        }
        Ok(())
    }
}

impl AgentRunCoordinator {
    pub(crate) fn open_instance_journaled(
        composition: RuntimeComposition,
        path: &Path,
        mode: JournalOpenMode,
    ) -> Result<Self, AgentRunError> {
        Self::open_journaled_with_instances(composition, path, mode, InstanceMode::Protected)
    }

    pub(super) fn initialize_instances(&mut self, mode: InstanceMode) -> Result<(), AgentRunError> {
        self.instances = match mode {
            InstanceMode::Legacy => None,
            InstanceMode::Protected => Some(InstanceBook::fresh()?),
        };
        Ok(())
    }

    pub(super) fn check_instance_mode(&self, mode: InstanceMode) -> Result<(), AgentRunError> {
        if matches!(
            (mode, &self.instances),
            (InstanceMode::Protected, Some(_)) | (InstanceMode::Legacy, None)
        ) {
            Ok(())
        } else {
            Err(AgentRunError::InstanceRequired)
        }
    }

    pub(super) fn require_instance_access(&self, run_id: &str) -> Result<(), AgentRunError> {
        if let Some(book) = &self.instances {
            let permit = self
                .instance_permit
                .as_ref()
                .ok_or(AgentRunError::InstanceRequired)?;
            if permit.run_id != run_id || book.current.get(run_id) != Some(&permit.sequence) {
                return Err(AgentRunError::StaleInstance);
            }
        }
        Ok(())
    }

    pub(crate) fn start_instance(
        &mut self,
        now_ms: u64,
        operation: &str,
        snapshot: RunSnapshot,
    ) -> Result<InstanceReceipt, AgentRunError> {
        validate_identity(operation, "creation operation")?;
        self.transact(|staged| {
            let book = staged
                .instances
                .as_ref()
                .ok_or(AgentRunError::InstanceRequired)?;
            if let Some(prior) = book.operations.get(operation) {
                if prior.snapshot != snapshot {
                    return Err(AgentRunError::Conflict);
                }
                let key = InstanceKey {
                    lineage: book.lineage.clone(),
                    sequence: prior.sequence,
                    run_id: prior.snapshot.run_id.clone(),
                };
                let mut result = staged.reconcile_instance(&key)?;
                // Creation retry recovers identity, not a fresh control activation.
                // Current phase/revision is observational; only explicit reconciliation
                // can issue a handle for this serving activation after reopen.
                result.handle.activation = prior.issued_activation;
                result.receipt.idempotent = true;
                return Ok(result);
            }
            if book.operations.len() >= MAX_CREATION_OPERATIONS {
                return Err(AgentRunError::CapacityExceeded);
            }
            if staged.runs.contains_key(&snapshot.run_id) {
                return Err(AgentRunError::Conflict);
            }
            let sequence = book
                .allocated
                .checked_add(1)
                .ok_or(AgentRunError::ArithmeticOverflow)?;
            let book = staged
                .instances
                .as_mut()
                .ok_or(AgentRunError::InstanceRequired)?;
            book.allocated = sequence;
            book.current.insert(snapshot.run_id.clone(), sequence);
            book.operations.insert(
                operation.to_string(),
                Creation {
                    snapshot: snapshot.clone(),
                    sequence,
                    issued_activation: book.activation,
                    released: None,
                },
            );
            let key = InstanceKey {
                lineage: book.lineage.clone(),
                sequence,
                run_id: snapshot.run_id.clone(),
            };
            staged.instance_permit = Some(InstancePermit {
                run_id: snapshot.run_id.clone(),
                sequence,
            });
            let result = staged.start_run(now_ms, snapshot)?;
            staged.instance_permit = None;
            let mut bound = staged.reconcile_instance(&key)?;
            bound.receipt = result;
            Ok(bound)
        })
    }

    pub(crate) fn reconcile_instance(
        &self,
        key: &InstanceKey,
    ) -> Result<InstanceReceipt, AgentRunError> {
        if self
            .journal
            .as_ref()
            .is_some_and(|journal| journal.poisoned)
        {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        let book = self
            .instances
            .as_ref()
            .ok_or(AgentRunError::InstanceRequired)?;
        if book.lineage != key.lineage {
            return Err(AgentRunError::StaleInstance);
        }
        let creation = book
            .operations
            .values()
            .find(|creation| {
                creation.sequence == key.sequence && creation.snapshot.run_id == key.run_id
            })
            .ok_or(AgentRunError::StaleInstance)?;
        let (record, released) = if let Some(record) = &creation.released {
            (record, true)
        } else {
            (
                self.runs
                    .get(&key.run_id)
                    .ok_or(AgentRunError::StaleInstance)?,
                false,
            )
        };
        Ok(InstanceReceipt {
            handle: InstanceHandle {
                key: key.clone(),
                activation: book.activation,
                revision: record.revision,
            },
            receipt: receipt(record, /*idempotent*/ false),
            released,
        })
    }

    pub(crate) fn mutate_instance(
        &mut self,
        handle: &InstanceHandle,
        now_ms: u64,
        mutation: InstanceMutation,
    ) -> Result<(RunReceipt, InstanceReceipt), AgentRunError> {
        self.mutate_instance_outcome(handle, |staged| {
            match mutation {
                InstanceMutation::Attach(attachment) => {
                    staged.attach_context(now_ms, handle.revision, *attachment)
                }
                InstanceMutation::Dispatch => {
                    staged.mark_dispatched(now_ms, &handle.key.run_id, handle.revision)
                }
                InstanceMutation::Observe {
                    phase,
                    terminal_observed,
                } => staged.observe_terminal(
                    &handle.key.run_id,
                    handle.revision,
                    phase,
                    terminal_observed,
                ),
                InstanceMutation::Release => {
                    staged.remove_closed_run(&handle.key.run_id, handle.revision)
                }
            }
            .map(Ok)
        })
        .map(|(receipt, mut bound)| {
            bound.receipt = receipt.clone();
            (receipt, bound)
        })
    }

    pub(crate) fn cancel_instance(
        &mut self,
        handle: &InstanceHandle,
        now_ms: u64,
        reason: &str,
    ) -> Result<((CancellationDisposition, RunReceipt), InstanceReceipt), AgentRunError> {
        self.mutate_instance_outcome(handle, |staged| {
            let timeout_due = staged.runs.get(&handle.key.run_id).is_some_and(|record| {
                record.phase == RunPhase::Cancelling
                    && record
                        .cancel_ack_deadline_ms
                        .is_some_and(|deadline| deadline <= now_ms)
            });
            let result = staged.cancel_run(now_ms, &handle.key.run_id, handle.revision, reason);
            if timeout_due && result == Err(AgentRunError::InvalidTransition) {
                Ok(result)
            } else {
                result.map(Ok)
            }
        })
        .map(|((disposition, receipt), mut bound)| {
            bound.receipt = receipt.clone();
            ((disposition, receipt), bound)
        })
    }

    fn mutate_instance_outcome<T>(
        &mut self,
        handle: &InstanceHandle,
        operation: impl FnOnce(&mut Self) -> Result<Result<T, AgentRunError>, AgentRunError>,
    ) -> Result<(T, InstanceReceipt), AgentRunError> {
        let (result, bound) = self.transact(|staged| {
            let current = staged.reconcile_instance(&handle.key)?;
            if current.released {
                return Err(AgentRunError::StaleInstance);
            }
            if current.handle.activation != handle.activation {
                return Err(AgentRunError::StaleActivation);
            }
            if current.handle.revision != handle.revision {
                return Err(AgentRunError::StaleRevision);
            }
            staged.instance_permit = Some(InstancePermit {
                run_id: handle.key.run_id.clone(),
                sequence: handle.key.sequence,
            });
            let value = operation(staged)?;
            staged.instance_permit = None;
            let bound = staged.reconcile_instance(&handle.key)?;
            Ok((value, bound))
        })?;
        result.map(|value| (value, bound))
    }

    pub(super) fn retain_released_instance(&mut self, run_id: &str) -> Result<(), AgentRunError> {
        let Some(book) = &mut self.instances else {
            return Ok(());
        };
        let sequence = *book
            .current
            .get(run_id)
            .ok_or(AgentRunError::StaleInstance)?;
        let record = self
            .runs
            .get(run_id)
            .ok_or(AgentRunError::RunNotFound)?
            .clone();
        let creation = book
            .operations
            .values_mut()
            .find(|creation| creation.sequence == sequence)
            .ok_or(AgentRunError::StaleInstance)?;
        creation.released = Some(record);
        book.current.remove(run_id);
        Ok(())
    }
}
