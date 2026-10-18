//! Observed feature retirement uses inference.control's existing fsync log.
//! A single intent reserves cold bytes before any archive file is written.
use std::time::Duration;
use std::time::Instant;

use serde::Deserialize;
use serde::Serialize;

use super::DurableInferenceControl;
use super::Error;
use super::FeatureJournal;
use super::FeatureOperationStateV1;
use super::archive_store;

pub(in crate::durable_control) const JOURNAL_PREFIX: &str = "feature-history-v1|";
pub const DEFAULT_FEATURE_COLD_BYTE_LIMIT: u64 = 64 * 1024 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Intent {
    request_id: String,
    record_digest: String,
    delta_bytes: u64,
    temporary_bytes: u64,
}

#[cfg(test)]
#[path = "feature_archive_tests.rs"]
mod tests;
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(in crate::durable_control) struct Frontier {
    cold_limit: Option<u64>,
    cold_bytes: u64,
    cold_records: u64,
    last_record: Option<(String, String)>,
    pending: Option<Intent>,
    #[serde(skip)]
    pub(in crate::durable_control) compaction_pending: bool,
}
#[derive(Deserialize, Serialize)]
#[serde(tag = "event", rename_all = "snake_case", deny_unknown_fields)]
enum Event {
    Pin {
        limit: u64,
    },
    Intent {
        intent: Intent,
    },
    Commit {
        request_id: String,
        record_digest: String,
    },
    Snapshot {
        frontier: Frontier,
    },
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureHistoryMaintenanceReceipt {
    pub archived_records: usize,
    pub resident_feature_records: usize,
    pub cold_records: u64,
    pub cold_bytes: u64,
    pub journal_bytes: u64,
    pub journal_compacted: bool,
}

impl Frontier {
    fn checked(
        &self,
        features: &FeatureJournal,
        path: &std::path::Path,
        event: &Event,
    ) -> Result<(Self, Option<String>), Error> {
        let mut next = self.clone();
        let mut remove = None;
        match event {
            Event::Pin { limit } => {
                if *limit == 0
                    || *limit > 1024 * DEFAULT_FEATURE_COLD_BYTE_LIMIT
                    || self.cold_limit.is_some_and(|prior| prior != *limit)
                {
                    return Err(Error::Conflict);
                }
                next.cold_limit = Some(*limit);
                next.compaction_pending = true;
            }
            Event::Intent { intent } => {
                if self.pending.is_some() {
                    return Err(Error::InvalidTransition);
                }
                let limit = self.cold_limit.ok_or(Error::InvalidTransition)?;
                let record = features
                    .records
                    .get(&intent.request_id)
                    .ok_or(Error::RequestNotFound)?;
                if intent.delta_bytes == 0
                    || intent.temporary_bytes > 8 * 1024 * 1024
                    || archive_store::record_digest(record)? != intent.record_digest
                {
                    return Err(Error::Conflict);
                }
                if self
                    .cold_bytes
                    .checked_add(intent.delta_bytes)
                    .and_then(|value| value.checked_add(intent.temporary_bytes))
                    .is_none_or(|value| value > limit)
                {
                    return Err(Error::CapacityExceeded);
                }
                next.pending = Some(intent.clone());
                next.compaction_pending = true;
            }
            Event::Commit {
                request_id,
                record_digest,
            } => {
                let intent = self.pending.as_ref().ok_or(Error::InvalidTransition)?;
                if &intent.request_id != request_id || &intent.record_digest != record_digest {
                    return Err(Error::Conflict);
                }
                let hot = features
                    .records
                    .get(request_id)
                    .ok_or(Error::RequestNotFound)?;
                let cold = archive_store::lookup(path, request_id)?
                    .ok_or(Error::CorruptJournal("cold feature commit lost receipt"))?;
                if hot != &cold || archive_store::record_digest(&cold)? != *record_digest {
                    return Err(Error::CorruptJournal("cold feature commit changed receipt"));
                }
                next.cold_bytes = self
                    .cold_bytes
                    .checked_add(intent.delta_bytes)
                    .ok_or(Error::CapacityExceeded)?;
                next.cold_records = self
                    .cold_records
                    .checked_add(1)
                    .ok_or(Error::CapacityExceeded)?;
                next.last_record = Some((request_id.clone(), record_digest.clone()));
                next.pending = None;
                next.compaction_pending = true;
                remove = Some(request_id.clone());
            }
            Event::Snapshot { frontier } => {
                if self.cold_limit.is_some()
                    || self.cold_bytes != 0
                    || self.pending.is_some()
                    || self.cold_records != 0
                    || self.last_record.is_some()
                {
                    return Err(Error::CorruptJournal("duplicate feature cold frontier"));
                }
                let limit = frontier
                    .cold_limit
                    .ok_or(Error::CorruptJournal("feature cold limit"))?;
                if limit == 0
                    || limit > 1024 * DEFAULT_FEATURE_COLD_BYTE_LIMIT
                    || frontier.cold_bytes > limit
                    || (frontier.cold_records == 0) != frontier.last_record.is_none()
                {
                    return Err(Error::CorruptJournal("feature cold frontier bounds"));
                }
                if let Some((id, digest)) = &frontier.last_record {
                    let record = archive_store::lookup(path, id)?
                        .ok_or(Error::CorruptJournal("feature cold frontier lost receipt"))?;
                    if archive_store::record_digest(&record)? != *digest {
                        return Err(Error::CorruptJournal("feature cold frontier digest"));
                    }
                }
                next = frontier.clone();
            }
        }
        Ok((next, remove))
    }

    pub(in crate::durable_control) fn validate_pending(
        &self,
        features: &FeatureJournal,
        path: &std::path::Path,
    ) -> Result<(), Error> {
        if let Some(intent) = &self.pending {
            let record = features
                .records
                .get(&intent.request_id)
                .ok_or(Error::RequestNotFound)?;
            if archive_store::record_digest(record)? != intent.record_digest
                || intent.delta_bytes == 0
                || intent.temporary_bytes > 8 * 1024 * 1024
                || self.cold_limit.is_none_or(|limit| {
                    self.cold_bytes
                        .checked_add(intent.delta_bytes)
                        .and_then(|value| value.checked_add(intent.temporary_bytes))
                        .is_none_or(|value| value > limit)
                })
            {
                return Err(Error::CorruptJournal("feature cold pending intent"));
            }
        }
        for record in features.records.values() {
            // An intent's exact hot receipt remains authoritative at a cut
            // between receipt and index files. Maintenance repairs those files
            // before commit; no new dispatch can consume this Observed record.
            if self
                .pending
                .as_ref()
                .is_some_and(|intent| intent.request_id == record.request.request_id.as_str())
            {
                continue;
            }
            if archive_store::lookup(path, record.request.request_id.as_str())?.is_some() {
                return Err(Error::CorruptJournal("cold feature identity re-admitted"));
            }
        }
        Ok(())
    }
}

pub(in crate::durable_control) fn replay(
    features: &mut FeatureJournal,
    path: &std::path::Path,
    json: &str,
) -> Result<(), Error> {
    let event: Event = serde_json::from_str(json)
        .map_err(|_| Error::CorruptJournal("feature cold event decode"))?;
    let (next, remove) = features.history.checked(features, path, &event)?;
    if let Some(id) = remove {
        features.records.remove(&id);
    }
    features.history = next;
    Ok(())
}

pub(in crate::durable_control) fn snapshot(
    features: &FeatureJournal,
) -> Result<Option<String>, Error> {
    if features.history.cold_limit.is_none() {
        return Ok(None);
    }
    let value = serde_json::to_string(&Event::Snapshot {
        frontier: features.history.clone(),
    })
    .map_err(|_| Error::CorruptJournal("feature cold snapshot encode"))?;
    Ok(Some(format!("{JOURNAL_PREFIX}{value}\n")))
}

impl DurableInferenceControl {
    pub fn resident_feature_records(&self) -> usize {
        self.features.records.len()
    }
    pub fn resident_record_capacity(&self) -> usize {
        self.capacity
    }
    pub fn feature_history_cold_byte_limit(&self) -> Option<u64> {
        self.features.history.cold_limit
    }

    /// Retire only verified terminal observations. Reserved and dispatched
    /// operations stay resident, including every unknown execution.
    pub fn maintain_feature_history(
        &mut self,
        maximum_records: usize,
        cold_limit_bytes: u64,
        budget: Duration,
    ) -> Result<FeatureHistoryMaintenanceReceipt, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        if maximum_records == 0 || maximum_records > super::super::MAX_RECORDS || budget.is_zero() {
            return Err(Error::CapacityExceeded);
        }
        let started = Instant::now();
        let mut journal_compacted = self.compact_native_history(started, budget)?;
        if self.features.history.cold_limit.is_none() {
            self.commit_feature_history(Event::Pin {
                limit: cold_limit_bytes,
            })?;
        } else if self.features.history.cold_limit != Some(cold_limit_bytes) {
            return Err(Error::Conflict);
        }
        let pending = self
            .features
            .history
            .pending
            .as_ref()
            .map(|value| value.request_id.clone());
        let mut candidates = Vec::new();
        if let Some(id) = &pending {
            candidates.push(id.clone());
        }
        candidates.extend(
            self.features
                .records
                .values()
                .filter(|record| matches!(record.state, FeatureOperationStateV1::Observed(_)))
                .filter(|record| {
                    pending
                        .as_ref()
                        .is_none_or(|id| id != record.request.request_id.as_str())
                })
                .take(maximum_records)
                .map(|record| record.request.request_id.to_string()),
        );
        candidates.truncate(maximum_records);
        let mut archived_records = 0;
        for id in candidates {
            if started.elapsed() >= budget {
                break;
            }
            let record = self
                .features
                .records
                .get(&id)
                .ok_or(Error::RequestNotFound)?;
            let prepared = archive_store::prepare(&self.path, record)?;
            let intent = Intent {
                request_id: id.clone(),
                record_digest: prepared.digest.clone(),
                delta_bytes: prepared.delta_bytes,
                temporary_bytes: prepared.temporary_bytes,
            };
            match self.features.history.pending.as_ref() {
                Some(prior) if prior != &intent => return Err(Error::Conflict),
                Some(_) => {}
                None => self.commit_feature_history(Event::Intent {
                    intent: intent.clone(),
                })?,
            }
            prepared.persist()?;
            self.commit_feature_history(Event::Commit {
                request_id: id,
                record_digest: intent.record_digest,
            })?;
            archived_records += 1;
        }
        journal_compacted |= self.compact_native_history(started, budget)?;
        Ok(FeatureHistoryMaintenanceReceipt {
            archived_records,
            resident_feature_records: self.features.records.len(),
            cold_records: self.features.history.cold_records,
            cold_bytes: self.features.history.cold_bytes,
            journal_bytes: self.journal_bytes,
            journal_compacted,
        })
    }

    fn commit_feature_history(&mut self, event: Event) -> Result<(), Error> {
        let (next, remove) = self
            .features
            .history
            .checked(&self.features, &self.path, &event)?;
        let encoded = serde_json::to_string(&event)
            .map_err(|_| Error::CorruptJournal("feature cold event encode"))?;
        self.append(&format!("{JOURNAL_PREFIX}{encoded}\n"))?;
        if let Some(id) = remove {
            self.features.records.remove(&id);
        }
        self.features.history = next;
        Ok(())
    }
}
