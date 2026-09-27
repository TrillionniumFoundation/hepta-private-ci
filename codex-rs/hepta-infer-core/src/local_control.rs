//! Local execution records in the existing inference.control journal.
//!
//! These are trusted-owner state transitions, not grant verification or device
//! attestation. A physical caller must additionally consume its kernel token.
//! Recovery never reconstructs a pre-effect permit and never issues execution.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

use super::DurableInferenceControl;
use super::Error;

#[path = "local_journal.rs"]
mod journal;

pub(super) const JOURNAL_PREFIX: &str = "local-v1|";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalOperationKind {
    Load,
    Run,
}

/// A device-lease budget pinned by the first reservation, across generations.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalResourcePolicy {
    pub maximum_memory_bytes: u64,
    pub maximum_models: u16,
    pub maximum_active_requests: u16,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalRequest {
    pub operation_id: String,
    pub kind: LocalOperationKind,
    pub worker_id: String,
    pub worker_generation: u64,
    pub device_lease_id: String,
    pub model_digest: String,
    pub model_tuple_digest: String,
    pub request_digest: String,
    pub payload_digest: String,
    pub runtime_digest: String,
    pub model_operation_id: Option<String>,
    pub reservation_bytes: u64,
    pub maximum_tokens: u32,
    pub deadline_unix_ms: u64,
    pub policy: LocalResourcePolicy,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalState {
    Reserved,
    Dispatching,
    Indeterminate,
    Resident,
    Unloading,
    Succeeded,
    Failed,
    Cancelled,
    Released,
}

impl LocalState {
    pub fn holds_resources(self) -> bool {
        matches!(
            self,
            Self::Reserved
                | Self::Dispatching
                | Self::Indeterminate
                | Self::Resident
                | Self::Unloading
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalDispatch {
    pub grant_id: String,
    pub authority_witness_digest: String,
    pub nonce_digest: String,
    pub physical_handle_id: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalTerminalStatus {
    Succeeded,
    Failed,
    Cancelled,
}

/// A terminal observation from the selected physical driver. Unknown usage is
/// optional, never encoded as zero. Correlation is bound before publication.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalObservation {
    pub status: LocalTerminalStatus,
    pub physical_handle_id: Option<String>,
    pub output: Option<String>,
    pub consumed_tokens: Option<u64>,
    pub observed_memory_bytes: u64,
    pub correlation_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalRecord {
    pub request: LocalRequest,
    pub revision: u64,
    pub state: LocalState,
    pub admitted_at_unix_ms: u64,
    pub first_indeterminate_at_unix_ms: Option<u64>,
    pub dispatch: Option<LocalDispatch>,
    pub observation: Option<LocalObservation>,
    pub cancellation_requested: bool,
    pub unload_observation_digest: Option<String>,
}

/// Single-use live-process proof. No public constructor, Clone, Deserialize or
/// recovery origin exists. It is consumed either by effect entry or by abort.
pub struct LocalDispatchPermit {
    operation_id: String,
    revision: u64,
    request_digest: String,
    authority_witness_digest: String,
}

impl LocalDispatchPermit {
    pub fn operation_id(&self) -> &str {
        &self.operation_id
    }

    pub fn request_digest(&self) -> &str {
        &self.request_digest
    }

    pub fn authority_witness_digest(&self) -> &str {
        &self.authority_witness_digest
    }
}

#[derive(Clone, Debug, Default)]
pub(super) struct LocalJournal {
    pub(super) records: BTreeMap<String, LocalRecord>,
    policies: BTreeMap<String, LocalResourcePolicy>,
    fenced: std::collections::BTreeSet<(String, u64)>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
    Reserve {
        request: LocalRequest,
        now: u64,
    },
    Prepare {
        id: String,
        dispatch: LocalDispatch,
    },
    Abort {
        id: String,
        revision: u64,
    },
    Cancel {
        id: String,
        now: u64,
    },
    Unknown {
        id: String,
        now: u64,
    },
    Observe {
        id: String,
        observation: LocalObservation,
    },
    BeginUnload {
        id: String,
    },
    Unloaded {
        id: String,
        observation_digest: String,
    },
    Fence {
        device: String,
        generation: u64,
    },
}

impl DurableInferenceControl {
    /// Identical completed or uncertain operations return the retained record.
    /// A changed deadline, model, resource policy or input conflicts on reuse.
    pub fn reserve_local(&mut self, request: LocalRequest, now: u64) -> Result<LocalRecord, Error> {
        if let Some(record) = self.local.records.get(&request.operation_id) {
            return if record.request == request {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        if self.records.contains_key(&request.operation_id)
            || self.native.records.contains_key(&request.operation_id)
        {
            return Err(Error::Conflict);
        }
        if self.records.len() + self.native.records.len() + self.local.records.len()
            >= self.capacity
        {
            return Err(Error::CapacityExceeded);
        }
        let id = request.operation_id.clone();
        self.commit_local(Event::Reserve { request, now })?;
        self.local_record(&id)
            .cloned()
            .ok_or(Error::RequestNotFound)
    }

    pub fn prepare_local(
        &mut self,
        id: &str,
        dispatch: LocalDispatch,
    ) -> Result<LocalDispatchPermit, Error> {
        if self.journal_bytes > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        self.commit_local(Event::Prepare {
            id: id.to_string(),
            dispatch,
        })?;
        let record = self.local_record(id).ok_or(Error::RequestNotFound)?;
        Ok(LocalDispatchPermit {
            operation_id: id.to_string(),
            revision: record.revision,
            request_digest: record.request.request_digest.clone(),
            authority_witness_digest: record
                .dispatch
                .as_ref()
                .ok_or(Error::InvalidTransition)?
                .authority_witness_digest
                .clone(),
        })
    }

    pub fn abort_local_before_effect(&mut self, permit: LocalDispatchPermit) -> Result<(), Error> {
        self.commit_local(Event::Abort {
            id: permit.operation_id,
            revision: permit.revision,
        })
    }

    pub fn cancel_local(&mut self, id: &str, now: u64) -> Result<(), Error> {
        let record = self.local_record(id).ok_or(Error::RequestNotFound)?;
        if record.cancellation_requested {
            return Ok(());
        }
        self.commit_local(Event::Cancel {
            id: id.to_string(),
            now,
        })
    }

    pub fn mark_local_indeterminate(&mut self, id: &str, now: u64) -> Result<(), Error> {
        let record = self.local_record(id).ok_or(Error::RequestNotFound)?;
        if record.state == LocalState::Indeterminate {
            return Ok(());
        }
        self.commit_local(Event::Unknown {
            id: id.to_string(),
            now,
        })
    }

    pub fn observe_local(&mut self, id: &str, observation: LocalObservation) -> Result<(), Error> {
        let record = self.local_record(id).ok_or(Error::RequestNotFound)?;
        if record.observation.as_ref() == Some(&observation) {
            return Ok(());
        }
        self.commit_local(Event::Observe {
            id: id.to_string(),
            observation,
        })
    }

    /// Cleanup is allowed after expiry, cancellation and generation fencing.
    /// The handle and its capacity remain journaled until terminal unload.
    pub fn begin_local_unload(&mut self, id: &str) -> Result<(), Error> {
        self.commit_local(Event::BeginUnload { id: id.to_string() })
    }

    pub fn observe_local_unloaded(
        &mut self,
        id: &str,
        observation_digest: String,
    ) -> Result<(), Error> {
        let record = self.local_record(id).ok_or(Error::RequestNotFound)?;
        if record.unload_observation_digest.as_ref() == Some(&observation_digest) {
            return Ok(());
        }
        self.commit_local(Event::Unloaded {
            id: id.to_string(),
            observation_digest,
        })
    }

    pub fn fence_local_generation(&mut self, device: &str, generation: u64) -> Result<(), Error> {
        if self
            .local
            .fenced
            .contains(&(device.to_string(), generation))
        {
            return Ok(());
        }
        self.commit_local(Event::Fence {
            device: device.to_string(),
            generation,
        })
    }

    pub fn local_generation_fenced(&self, device: &str, generation: u64) -> bool {
        self.local
            .fenced
            .contains(&(device.to_string(), generation))
    }

    pub fn local_record(&self, id: &str) -> Option<&LocalRecord> {
        self.local.records.get(id)
    }

    pub fn local_reserved_bytes(&self, device: &str) -> Result<u64, Error> {
        self.local
            .records
            .values()
            .filter(|record| {
                record.request.device_lease_id == device && record.state.holds_resources()
            })
            .try_fold(0_u64, |total, record| {
                total
                    .checked_add(record.request.reservation_bytes)
                    .ok_or(Error::ArithmeticOverflow)
            })
    }

    fn commit_local(&mut self, event: Event) -> Result<(), Error> {
        let mut next = self.local.clone();
        next.apply(event.clone())?;
        let json =
            serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("local encode"))?;
        self.append(&format!("{JOURNAL_PREFIX}{json}\n"))?;
        self.local = next;
        Ok(())
    }
}

#[cfg(test)]
#[path = "local_control_tests.rs"]
mod tests;
