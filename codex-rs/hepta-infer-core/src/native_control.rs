//! Hosted runs share the control owner's journal and exclusive writer lock.
//! A reservation is one local in-flight slot, not a token or payment grant.
//! Unknown execution retains that slot; unknown token usage remains `None`.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

use super::DurableInferenceControl;
use super::Error;
use super::validate_digest;
use super::validate_identity;

pub(super) const JOURNAL_PREFIX: &str = "native-v1|";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRequest {
    pub request_id: String,
    pub principal_id: String,
    pub worker_generation: u64,
    pub model: String,
    /// Binds the prompt, optional query, exact socket and execution timeout.
    pub payload_digest: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRunStatus {
    Completed,
    Failed,
    Interrupted,
    Indeterminate,
}

/// Provider terminality and the owner's authority observation are independent.
/// Missing historical fields never establish that authority was checked.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum NativeOwnerAuthority {
    #[default]
    Unverified,
    /// The exact owner was ready at the last health check, not an atomic grant
    /// against revocation after that check.
    ObservedReady,
    Lost {
        reason: String,
    },
}

/// Fields observed by the native client, never a provider billing assertion.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunOutput {
    pub thread_id: String,
    pub turn_id: String,
    pub model: String,
    pub model_provider: String,
    pub status: NativeRunStatus,
    pub output: String,
    pub observed_output_tokens: Option<u64>,
    pub terminal_observed: bool,
    pub stop_reason: Option<String>,
    #[serde(default)]
    pub owner_authority: NativeOwnerAuthority,
}

impl NativeRunOutput {
    /// The CLI and callers must not infer authorized success from provider
    /// completion alone, including when replaying a historical observation.
    pub fn succeeded(&self) -> bool {
        self.terminal_observed
            && self.status == NativeRunStatus::Completed
            && self.owner_authority == NativeOwnerAuthority::ObservedReady
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeReservationState {
    Reserved,
    Dispatching,
    Running,
    Cancelling,
    Indeterminate,
    Released,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatch {
    pub thread_id: String,
    pub model_provider: String,
    /// Exact serialized additional context, including its owner snapshot.
    pub context_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunRecord {
    pub request: NativeRequest,
    pub revision: u64,
    pub state: NativeReservationState,
    pub dispatch: Option<NativeDispatch>,
    pub turn_id: Option<String>,
    pub cancel_requested: bool,
    /// A locally proven stop before provider `turn/start` releases a slot
    /// without pretending to have observed a provider terminal event or zero
    /// token consumption.
    pub pre_dispatch_stop: Option<String>,
    pub observation: Option<NativeRunOutput>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeArchivedTombstone {
    pub request: NativeRequest,
    pub final_state: NativeReservationState,
    pub archive_digest: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(super) struct NativeJournal {
    maximum_in_flight: Option<usize>,
    pub(super) records: BTreeMap<String, NativeRunRecord>,
    pub(super) tombstones: BTreeMap<String, NativeArchivedTombstone>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
    Policy {
        maximum_in_flight: usize,
    },
    Reserve {
        request: NativeRequest,
        maximum_in_flight: usize,
    },
    Dispatch {
        request_id: String,
        dispatch: NativeDispatch,
    },
    Started {
        request_id: String,
        turn_id: String,
    },
    Cancel {
        request_id: String,
    },
    Stop {
        request_id: String,
        reason: String,
    },
    Observe {
        request_id: String,
        output: NativeRunOutput,
    },
    Tombstone {
        request: NativeRequest,
        final_state: NativeReservationState,
        archive_digest: String,
    },
}

impl DurableInferenceControl {
    /// The first admission pins the local slot limit for this journal. A
    /// duplicate binds every request field and never reserves a second slot.
    pub fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> Result<NativeRunRecord, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if self.file.metadata()?.permissions().mode() & 0o077 != 0 {
                return Err(Error::InvalidIdentity("native journal must be owner-only"));
            }
        }
        if self
            .native
            .maximum_in_flight
            .is_some_and(|limit| limit != maximum_in_flight)
            || self.records.contains_key(&request.request_id)
        {
            return Err(Error::Conflict);
        }
        if let Some(record) = self.native.records.get(&request.request_id) {
            return if record.request == request {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        self.maybe_compact_native_history()?;
        if self.records.len() + self.native.active_count() >= self.capacity {
            return Err(Error::CapacityExceeded);
        }
        if let Some(tombstone) = self.native.tombstones.get(&request.request_id) {
            return if tombstone.request == request {
                Err(Error::ArchivedRequest)
            } else {
                Err(Error::Conflict)
            };
        }
        self.ensure_native_dispatch_space()?;
        let id = request.request_id.clone();
        self.commit_native(
            &id,
            Event::Reserve {
                request,
                maximum_in_flight,
            },
        )
    }

    /// Must commit before `turn/start`, including before awaiting its response.
    pub fn dispatch_native(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<NativeRunRecord, Error> {
        self.ensure_native_dispatch_space()?;
        self.commit_native(
            request_id,
            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
            },
        )
    }

    pub fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::Started {
                request_id: request_id.to_string(),
                turn_id,
            },
        )
    }

    /// This records intent only: an interrupt acknowledgement never frees a slot.
    pub fn cancel_native(&mut self, request_id: &str) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.cancel_requested {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Cancel {
                request_id: request_id.to_string(),
            },
        )
    }

    pub fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state != NativeReservationState::Reserved {
            return Err(Error::InvalidTransition);
        }
        self.commit_native(
            request_id,
            Event::Stop {
                request_id: request_id.to_string(),
                reason,
            },
        )
    }

    /// Release a synced dispatch intent only when the trusted host can prove it
    /// has not sent provider `turn/start` yet. This lets a final authority or
    /// cognitive-receipt check sit after durable dispatch and immediately before
    /// the external effect without leaking the local slot on a fail-closed stop.
    pub fn stop_native_before_turn_start(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state != NativeReservationState::Dispatching || record.turn_id.is_some() {
            return Err(Error::InvalidTransition);
        }
        self.commit_native(
            request_id,
            Event::Stop {
                request_id: request_id.to_string(),
                reason,
            },
        )
    }

    /// Trusted host port: validates exact assignment and monotonic observations.
    /// Only matching terminal observations release local execution capacity.
    /// Missing usage never becomes zero and unknown execution may later settle.
    pub fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.observation.as_ref() == Some(&output) {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Observe {
                request_id: request_id.to_string(),
                output,
            },
        )
    }

    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    pub fn native_archived_tombstone(
        &self,
        request_id: &str,
    ) -> Option<&NativeArchivedTombstone> {
        self.native.tombstones.get(request_id)
    }

    fn ensure_native_dispatch_space(&mut self) -> Result<(), Error> {
        // This exclusive owner serializes active calls. Leave room for bounded
        // dispatch/cancel metadata and the next maximal observed output before
        // admitting a new external execution. This is not an archival policy.
        if self.journal_bytes > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }

    fn commit_native(&mut self, request_id: &str, event: Event) -> Result<NativeRunRecord, Error> {
        let mut next = self.native.clone();
        next.apply(event.clone())?;
        let json =
            serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("native encode"))?;
        self.append(&format!("{JOURNAL_PREFIX}{json}\n"))?;
        self.native = next;
        self.native
            .records
            .get(request_id)
            .cloned()
            .ok_or(Error::RequestNotFound)
    }
}

impl NativeJournal {
    pub(super) fn active_count(&self) -> usize {
        self.records
            .values()
            .filter(|record| record.state != NativeReservationState::Released)
            .count()
    }

    pub(super) fn released_count(&self) -> usize {
        self.records.len().saturating_sub(self.active_count())
    }

    pub(super) fn compacted_lines(&self, archive_digest: &str) -> Result<String, Error> {
        validate_digest(archive_digest, "native archive")?;
        let mut events = Vec::new();
        if let Some(maximum_in_flight) = self.maximum_in_flight {
            events.push(Event::Policy { maximum_in_flight });
        }
        for tombstone in self.tombstones.values() {
            events.push(Event::Tombstone {
                request: tombstone.request.clone(),
                final_state: tombstone.final_state,
                archive_digest: tombstone.archive_digest.clone(),
            });
        }
        let maximum_in_flight = self.maximum_in_flight.unwrap_or(1);
        for record in self.records.values() {
            if record.state == NativeReservationState::Released {
                events.push(Event::Tombstone {
                    request: record.request.clone(),
                    final_state: NativeReservationState::Released,
                    archive_digest: archive_digest.to_string(),
                });
                continue;
            }
            events.push(Event::Reserve {
                request: record.request.clone(),
                maximum_in_flight,
            });
            if let Some(dispatch) = &record.dispatch {
                events.push(Event::Dispatch {
                    request_id: record.request.request_id.clone(),
                    dispatch: dispatch.clone(),
                });
            }
            if let Some(turn_id) = &record.turn_id {
                events.push(Event::Started {
                    request_id: record.request.request_id.clone(),
                    turn_id: turn_id.clone(),
                });
            }
            if record.cancel_requested {
                events.push(Event::Cancel {
                    request_id: record.request.request_id.clone(),
                });
            }
            if let Some(reason) = &record.pre_dispatch_stop {
                events.push(Event::Stop {
                    request_id: record.request.request_id.clone(),
                    reason: reason.clone(),
                });
            }
            if let Some(output) = &record.observation {
                events.push(Event::Observe {
                    request_id: record.request.request_id.clone(),
                    output: output.clone(),
                });
            }
        }

        let mut candidate = NativeJournal::default();
        let mut encoded = String::new();
        for event in events {
            candidate.apply(event.clone())?;
            let json =
                serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("native encode"))?;
            encoded.push_str(JOURNAL_PREFIX);
            encoded.push_str(&json);
            encoded.push('\n');
        }
        let expected_records = self
            .records
            .iter()
            .filter(|(_, record)| record.state != NativeReservationState::Released)
            .map(|(id, record)| (id.clone(), record.clone()))
            .collect::<BTreeMap<_, _>>();
        if candidate.records != expected_records
            || candidate.maximum_in_flight != self.maximum_in_flight
            || candidate.tombstones.len() != self.tombstones.len() + self.released_count()
        {
            return Err(Error::CorruptJournal("native compaction replay"));
        }
        Ok(encoded)
    }

    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        let event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("native decode"))?;
        self.apply(event)
    }

    fn apply(&mut self, event: Event) -> Result<(), Error> {
        if let Event::Policy { maximum_in_flight } = event {
            if !(1..=256).contains(&maximum_in_flight)
                || self
                    .maximum_in_flight
                    .is_some_and(|current| current != maximum_in_flight)
            {
                return Err(Error::Conflict);
            }
            self.maximum_in_flight = Some(maximum_in_flight);
            return Ok(());
        }
        if let Event::Tombstone {
            request,
            final_state,
            archive_digest,
        } = event
        {
            validate_identity(&request.request_id, "native request")?;
            validate_digest(&request.payload_digest, "native payload")?;
            validate_digest(&archive_digest, "native archive")?;
            if final_state != NativeReservationState::Released
                || self.records.contains_key(&request.request_id)
                || self.tombstones.contains_key(&request.request_id)
            {
                return Err(Error::Conflict);
            }
            self.tombstones.insert(
                request.request_id.clone(),
                NativeArchivedTombstone {
                    request,
                    final_state,
                    archive_digest,
                },
            );
            return Ok(());
        }
        if let Event::Reserve {
            request,
            maximum_in_flight,
        } = event
        {
            validate_identity(&request.request_id, "native request")?;
            validate_identity(&request.principal_id, "native principal")?;
            validate_digest(&request.payload_digest, "native payload")?;
            if request.worker_generation == 0
                || request.model.is_empty()
                || request.model.len() > 256
            {
                return Err(Error::InvalidIdentity("native worker/model"));
            }
            if !(1..=256).contains(&maximum_in_flight) {
                return Err(Error::CapacityExceeded);
            }
            if self
                .maximum_in_flight
                .is_some_and(|limit| limit != maximum_in_flight)
                || self.records.contains_key(&request.request_id)
            {
                return Err(Error::Conflict);
            }
            if let Some(tombstone) = self.tombstones.get(&request.request_id) {
                return if tombstone.request == request {
                    Err(Error::ArchivedRequest)
                } else {
                    Err(Error::Conflict)
                };
            }
            if self
                .records
                .values()
                .filter(|record| record.state != NativeReservationState::Released)
                .count()
                >= maximum_in_flight
            {
                return Err(Error::CapacityExceeded);
            }
            self.maximum_in_flight = Some(maximum_in_flight);
            self.records.insert(
                request.request_id.clone(),
                NativeRunRecord {
                    request,
                    revision: 1,
                    state: NativeReservationState::Reserved,
                    dispatch: None,
                    turn_id: None,
                    cancel_requested: false,
                    pre_dispatch_stop: None,
                    observation: None,
                },
            );
            return Ok(());
        }
        let id = match &event {
            Event::Policy { .. } | Event::Reserve { .. } | Event::Tombstone { .. } => {
                return Err(Error::InvalidTransition)
            }
            Event::Dispatch { request_id, .. }
            | Event::Started { request_id, .. }
            | Event::Cancel { request_id }
            | Event::Stop { request_id, .. }
            | Event::Observe { request_id, .. } => request_id,
        };
        let record = self.records.get_mut(id).ok_or(Error::RequestNotFound)?;
        match event {
            Event::Policy { .. } | Event::Reserve { .. } | Event::Tombstone { .. } => {
                return Err(Error::InvalidTransition)
            }
            Event::Dispatch { dispatch, .. } => {
                if record.state != NativeReservationState::Reserved {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&dispatch.thread_id, "native thread")?;
                validate_identity(&dispatch.model_provider, "native provider")?;
                validate_digest(&dispatch.context_digest, "native context")?;
                record.dispatch = Some(dispatch);
                record.state = NativeReservationState::Dispatching;
            }
            Event::Started { turn_id, .. } => {
                if record.state != NativeReservationState::Dispatching {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&turn_id, "native turn")?;
                record.turn_id = Some(turn_id);
                record.state = NativeReservationState::Running;
            }
            Event::Cancel { .. } => {
                if record.state == NativeReservationState::Released
                    || record.state == NativeReservationState::Reserved
                {
                    return Err(Error::InvalidTransition);
                }
                record.cancel_requested = true;
                record.state = NativeReservationState::Cancelling;
            }
            Event::Stop { reason, .. } => {
                if !matches!(
                    record.state,
                    NativeReservationState::Reserved | NativeReservationState::Dispatching
                ) || record.turn_id.is_some()
                    || reason.is_empty()
                    || reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = Some(reason);
                record.state = NativeReservationState::Released;
            }
            Event::Observe { output, .. } => {
                apply_observation(record, output)?;
            }
        }
        record.revision = record
            .revision
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        Ok(())
    }
}

fn apply_observation(record: &mut NativeRunRecord, output: NativeRunOutput) -> Result<(), Error> {
    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
    if output.thread_id != dispatch.thread_id
        || output.model_provider != dispatch.model_provider
        || output.model != record.request.model
        || record
            .turn_id
            .as_ref()
            .is_some_and(|turn| turn != &output.turn_id)
    {
        return Err(Error::AssignmentMismatch);
    }
    if output.output.len() > 1024 * 1024
        || output
            .stop_reason
            .as_ref()
            .is_some_and(|reason| reason.len() > 4096)
    {
        return Err(Error::CapacityExceeded);
    }
    if let NativeOwnerAuthority::Lost { reason } = &output.owner_authority
        && (reason.is_empty() || reason.len() > 4096)
    {
        return Err(Error::InvalidIdentity("owner authority loss reason"));
    }
    if output.terminal_observed == (output.status == NativeRunStatus::Indeterminate)
        || (output.turn_id.is_empty()
            && (output.terminal_observed
                || output.observed_output_tokens.is_some()
                || !output.output.is_empty()))
    {
        return Err(Error::TerminalObservationMissing);
    }
    if let Some(previous) = &record.observation {
        // A late provider completion or usage refinement cannot erase a lost
        // owner, or retroactively authorize an unverified historical terminal.
        if (matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. })
            && previous.owner_authority != output.owner_authority)
            || (previous.terminal_observed
                && previous.owner_authority == NativeOwnerAuthority::Unverified
                && output.owner_authority == NativeOwnerAuthority::ObservedReady)
        {
            return Err(Error::Conflict);
        }
        if previous.terminal_observed
            && (previous.status != output.status
                || !output.terminal_observed
                || previous.output != output.output)
        {
            return Err(Error::Conflict);
        }
        if previous.observed_output_tokens.is_some_and(|tokens| {
            output
                .observed_output_tokens
                .is_none_or(|next| next < tokens)
        }) {
            return Err(Error::Conflict);
        }
    }
    if !output.turn_id.is_empty() {
        validate_identity(&output.turn_id, "native turn")?;
        record.turn_id = Some(output.turn_id.clone());
    }
    record.state = if output.terminal_observed {
        NativeReservationState::Released
    } else {
        NativeReservationState::Indeterminate
    };
    record.observation = Some(output);
    Ok(())
}

#[cfg(test)]
#[path = "native_control_tests.rs"]
mod tests;

#[cfg(test)]
mod pre_turn_stop_tests {
    use super::*;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    #[test]
    fn synced_dispatch_can_stop_before_turn_start_and_release_slot() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("hepta-native-pre-turn-stop-{nonce}.journal"));
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        control
            .reserve_native(
                NativeRequest {
                    request_id: "r1".to_string(),
                    principal_id: "agent-1".to_string(),
                    worker_generation: 4,
                    model: "actual-model".to_string(),
                    payload_digest: "a".repeat(64),
                },
                1,
            )
            .unwrap();
        control
            .dispatch_native(
                "r1",
                NativeDispatch {
                    thread_id: "thread-1".to_string(),
                    model_provider: "provider".to_string(),
                    context_digest: "b".repeat(64),
                },
            )
            .unwrap();
        let stopped = control
            .stop_native_before_turn_start("r1", "stale cognitive receipt".to_string())
            .unwrap();
        assert_eq!(stopped.state, NativeReservationState::Released);
        assert_eq!(stopped.turn_id, None);
        assert_eq!(
            stopped.pre_dispatch_stop.as_deref(),
            Some("stale cognitive receipt")
        );
        assert_eq!(stopped.observation, None);
        assert!(stopped.dispatch.is_some());
        assert_eq!(
            control.native_started("r1", "turn-1".to_string()),
            Err(Error::InvalidTransition)
        );
        drop(control);
        let reopened = DurableInferenceControl::open(&path, 8).unwrap();
        assert_eq!(reopened.native_record("r1"), Some(&stopped));
        drop(reopened);
        std::fs::remove_file(path).unwrap();
    }
}
