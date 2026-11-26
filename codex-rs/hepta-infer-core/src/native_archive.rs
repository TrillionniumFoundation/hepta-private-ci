//! Bounded maintenance of settled native executions under the control writer.

use std::time::Duration;
use std::time::Instant;

use super::DurableInferenceControl;
use super::Error;
use super::archive_store;
use super::native::Event;
use super::native::NativeReservationState;
use super::native::NativeRunRecord;

/// Counts describe work actually committed in this maintenance call. History
/// receipts remain queryable and their identities can never be re-admitted.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeHistoryMaintenanceReceipt {
    pub archived_records: usize,
    pub resident_native_records: usize,
    pub journal_bytes: u64,
    pub journal_compacted: bool,
}

pub(super) fn eligible(record: &NativeRunRecord) -> bool {
    record.state == NativeReservationState::Released
        && record
            .terminal_publication
            .as_ref()
            .is_none_or(|entry| !entry.pending())
        && (record.terminal_owner.is_none()
            || record.pre_dispatch_stop.is_some()
            || record.terminal_publication.is_some())
}

pub(super) fn validate_replay_archive(path: &std::path::Path, json: &str) -> Result<(), Error> {
    let event: Event = serde_json::from_str(json)
        .map_err(|_| Error::CorruptJournal("native archive event decode"))?;
    if let Event::Archive {
        request_id,
        record_sha256,
    } = event
    {
        let record = archive_store::lookup(path, &request_id)?
            .ok_or(Error::CorruptJournal("native archive event lost receipt"))?;
        if archive_store::record_digest(&record)? != record_sha256 {
            return Err(Error::CorruptJournal(
                "native archive event receipt mismatch",
            ));
        }
    }
    Ok(())
}

impl DurableInferenceControl {
    /// Query the precise current or immutable archived native receipt. Unlike
    /// `native_record`, this reads history and reports missing/corrupt receipts
    /// as an error; a tombstone without its receipt never means a new request.
    pub fn native_record_resolved(
        &self,
        request_id: &str,
    ) -> Result<Option<NativeRunRecord>, Error> {
        if let Some(record) = self.native.records.get(request_id) {
            return Ok(Some(record.clone()));
        }
        archive_store::lookup(&self.path, request_id)
    }

    /// Move only released, fully acknowledged executions to immutable history.
    /// An unresolved execution or an outbox awaiting its owner stays resident.
    /// Budgets are checked between bounded I/O units; filesystem fsync latency
    /// is determined by the host. Compaction can be resumed on a later call.
    pub fn maintain_native_history(
        &mut self,
        maximum_records: usize,
        budget: Duration,
    ) -> Result<NativeHistoryMaintenanceReceipt, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        if maximum_records == 0 || maximum_records > super::MAX_RECORDS || budget.is_zero() {
            return Err(Error::CapacityExceeded);
        }
        let started = Instant::now();
        let active_owners: std::collections::BTreeSet<_> = self
            .native
            .records
            .values()
            .filter(|record| record.state != NativeReservationState::Released)
            .filter_map(|record| {
                record.terminal_owner.as_ref().map(|owner| {
                    (
                        record.request.principal_id.as_str(),
                        record.request.worker_generation,
                        owner.run_id.as_str(),
                    )
                })
            })
            .collect();
        let candidates: Vec<_> = self
            .native
            .records
            .values()
            .filter(|record| eligible(record))
            .filter(|record| {
                record.terminal_owner.as_ref().is_none_or(|owner| {
                    !active_owners.contains(&(
                        record.request.principal_id.as_str(),
                        record.request.worker_generation,
                        owner.run_id.as_str(),
                    ))
                })
            })
            .take(maximum_records.min(self.capacity))
            .cloned()
            .collect();
        let mut archived_records = 0;
        for record in candidates {
            if started.elapsed() >= budget {
                break;
            }
            let digest = archive_store::persist(&self.path, &record)?;
            self.commit_native_archive(&record.request.request_id, digest)?;
            archived_records += 1;
        }
        let journal_compacted = self.compact_native_history(started, budget)?;
        Ok(NativeHistoryMaintenanceReceipt {
            archived_records,
            resident_native_records: self.native.records.len(),
            journal_bytes: self.journal_bytes,
            journal_compacted,
        })
    }
}

#[cfg(test)]
#[path = "native_archive_tests.rs"]
mod tests;
