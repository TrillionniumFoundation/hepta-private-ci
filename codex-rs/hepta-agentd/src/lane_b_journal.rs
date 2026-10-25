//! Qualification-only snapshot transactions for the original coordinator, not an authority
//! service, instance allocator or durable operation-id ledger. Production still
//! uses the unchanged in-memory constructor until the full owner path qualifies.

use super::*;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Snapshot {
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    accepting_runs: bool,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Document {
    schema: u32,
    sequence: u64,
    snapshot: Snapshot,
    checksum: String,
}

#[derive(Debug)]
pub(super) struct LifecycleJournal {
    path: PathBuf,
    _lock: File,
    sequence: u64,
    committed: Option<Snapshot>,
    poisoned: bool,
    #[cfg(test)]
    fail_before_publish: bool,
    #[cfg(test)]
    fail_after_publish: bool,
}

impl AgentRunCoordinator {
    /// Qualification-only constructor for the original coordinator's actual
    /// mutation path. It grants no authority and is not wired into startup.
    pub(crate) fn open_journaled(
        composition: RuntimeComposition,
        path: &Path,
        mode: JournalOpenMode,
    ) -> Result<Self, AgentRunError> {
        let mut owner = Self::compose_runtime(composition)?;
        let (mut journal, stored) = LifecycleJournal::open(path, mode)?;
        if let Some(snapshot) = stored {
            if snapshot.composition != owner.composition {
                return Err(AgentRunError::PersistenceUnavailable);
            }
            validate_stored(&snapshot)?;
            owner.runs = snapshot.runs;
            owner.accepting_runs = snapshot.accepting_runs;
        } else {
            journal.commit(owner.snapshot())?;
        }
        owner.journal = Some(journal);
        // Preserve pre-dispatch states. Possible dispatch is never replayable;
        // persist that recovery transition before returning the owner.
        owner.mark_unresolved_indeterminate("coordinator_reopened")?;
        Ok(owner)
    }

    fn snapshot(&self) -> Snapshot {
        Snapshot {
            composition: self.composition.clone(),
            runs: self.runs.clone(),
            accepting_runs: self.accepting_runs,
        }
    }

    /// Plan with the existing state machine, persist, then install. No second
    /// FSM or mutable authority is introduced by the persistence adapter.
    pub(super) fn transact<T>(
        &mut self,
        operation: impl FnOnce(&mut Self) -> Result<T, AgentRunError>,
    ) -> Result<T, AgentRunError> {
        if self
            .journal
            .as_ref()
            .is_some_and(|journal| journal.poisoned)
        {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        let mut staged = Self {
            composition: self.composition.clone(),
            runs: self.runs.clone(),
            accepting_runs: self.accepting_runs,
            max_active_runs: self.max_active_runs,
            journal: None,
        };
        let result = operation(&mut staged)?;
        let next = staged.snapshot();
        if self
            .journal
            .as_ref()
            .and_then(|journal| journal.committed.as_ref())
            != Some(&next)
        {
            let journal = self
                .journal
                .as_mut()
                .ok_or(AgentRunError::PersistenceUnavailable)?;
            if let Err(error) = journal.commit(next) {
                // Any failed commit is closed until reopen, including a lost
                // acknowledgement after rename. Never retry from stale memory.
                journal.poisoned = true;
                self.accepting_runs = false;
                return Err(error);
            }
            self.runs = staged.runs;
            self.accepting_runs = staged.accepting_runs;
        }
        Ok(result)
    }
}

fn validate_stored(snapshot: &Snapshot) -> Result<(), AgentRunError> {
    if snapshot.runs.len() > MAX_RETAINED_RUNS
        || snapshot
            .runs
            .values()
            .filter(|record| !record.phase.closed())
            .count()
            > snapshot.composition.max_active_runs
    {
        return Err(AgentRunError::PersistenceUnavailable);
    }
    for (key, record) in &snapshot.runs {
        validate_snapshot_fields(&record.snapshot)?;
        if key != &record.snapshot.run_id || record.revision == 0 {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        if (record.phase == RunPhase::Admitted
            && (record.context_digest.is_some() || record.revision != 1))
            || (matches!(
                record.phase,
                RunPhase::Admitted | RunPhase::ContextAttached | RunPhase::Dispatched
            ) && record.cancel_reason.is_some())
            || (record.phase == RunPhase::Cancelling && record.cancel_reason.is_none())
            || (record.phase == RunPhase::Cancelled
                && record.context_digest.is_none()
                && record.cancel_reason.is_none())
            || record.cancel_ack_deadline_ms == Some(0)
        {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        match (&record.context_digest, &record.compilation_receipt_digest) {
            (Some(context), Some(compilation)) => {
                validate_digest(context, "context")?;
                validate_digest(compilation, "compilation receipt")?;
            }
            (None, None) if matches!(record.phase, RunPhase::Admitted | RunPhase::Cancelled) => {}
            _ => return Err(AgentRunError::PersistenceUnavailable),
        }
        if let Some(reason) = &record.cancel_reason {
            validate_cancel_reason(reason)?;
        }
        if record.cancel_ack_deadline_ms.is_some() != (record.phase == RunPhase::Cancelling) {
            return Err(AgentRunError::PersistenceUnavailable);
        }
    }
    Ok(())
}

#[path = "lane_b_journal_file.rs"]
mod file;

#[cfg(test)]
#[path = "lane_b_journal_tests.rs"]
mod tests;
