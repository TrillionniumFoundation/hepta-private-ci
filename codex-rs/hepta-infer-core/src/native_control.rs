//! Hosted runs share the control owner's journal with short durable writer
//! transactions. Model/provider execution never holds the journal writer lock.
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
pub(super) const CHECKPOINT_PREFIX: &str = "checkpoint-native-v1|";

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

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NativeJournal {
    maximum_in_flight: Option<usize>,
    /// Derived during replay. Never trusted from a checkpoint or wire payload.
    #[serde(skip)]
    active_count: usize,
    pub(super) records: BTreeMap<String, NativeRunRecord>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct NativeCheckpointV1 {
    maximum_in_flight: Option<usize>,
    record: NativeRunRecord,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
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
        let id = request.request_id.clone();
        if let Some(record) = self.archived_native_record(&id)? {
            return if record.request == request {
                Ok(record)
            } else {
                Err(Error::Conflict)
            };
        }

        // Released runs are cold idempotence facts, not live scheduling state.
        // Before failing a new admission on hot-record or journal capacity,
        // move them to the owner-only released archive and publish a compact
        // active journal. commit_native() still reloads and validates under the
        // writer fence, so a peer mutation between maintenance and admission
        // cannot bypass the exact-current check.
        if self.records.len() + self.native.records.len() >= self.capacity
            || self.needs_compaction()
        {
            self.archive_released_native()?;
        }

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

    fn ensure_native_dispatch_space(&self) -> Result<(), Error> {
        // A short writer transaction serializes mutations. Leave room for bounded
        // dispatch/cancel metadata and the next maximal observed output before
        // admitting a new external execution. This is not an archival policy.
        if self.journal_bytes > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }

    fn commit_native(&mut self, request_id: &str, event: Event) -> Result<NativeRunRecord, Error> {
        let _writer_fence = self.reload_locked()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if self.file.metadata()?.permissions().mode() & 0o077 != 0 {
                return Err(Error::InvalidIdentity("native journal must be owner-only"));
            }
        }
        if let Some(existing) = self.validate_latest_native_event(&event)? {
            return Ok(existing);
        }
        // Headroom protects NEW dispatches. Terminal/cancel/reconciliation
        // writes must still be allowed to use that reserved space.
        if matches!(event, Event::Reserve { .. } | Event::Dispatch { .. }) {
            self.ensure_native_dispatch_space()?;
        }
        let mut next = NativeJournal {
            maximum_in_flight: self.native.maximum_in_flight,
            active_count: self.native.active_count,
            records: BTreeMap::new(),
        };
        if let Some(record) = self.native.records.get(request_id) {
            next.records.insert(request_id.to_string(), record.clone());
        }
        next.apply(event.clone())?;
        let record = next
            .records
            .remove(request_id)
            .ok_or(Error::RequestNotFound)?;
        let json =
            serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("native encode"))?;
        self.append(&format!("{JOURNAL_PREFIX}{json}\n"))?;
        self.native.maximum_in_flight = next.maximum_in_flight;
        self.native.active_count = next.active_count;
        self.native
            .records
            .insert(request_id.to_string(), record.clone());
        Ok(record)
    }

    fn validate_latest_native_event(
        &self,
        event: &Event,
    ) -> Result<Option<NativeRunRecord>, Error> {
        match event {
            Event::Reserve {
                request,
                maximum_in_flight,
            } => {
                if !(1..=256).contains(maximum_in_flight) {
                    return Err(Error::CapacityExceeded);
                }
                if self.records.contains_key(&request.request_id)
                    || self
                        .native
                        .maximum_in_flight
                        .is_some_and(|limit| limit != *maximum_in_flight)
                {
                    return Err(Error::Conflict);
                }
                if let Some(record) = self.native.records.get(&request.request_id) {
                    return if record.request == *request {
                        Ok(Some(record.clone()))
                    } else {
                        Err(Error::Conflict)
                    };
                }
                if let Some(record) = self.archived_native_record(&request.request_id)? {
                    return if record.request == *request {
                        Ok(Some(record))
                    } else {
                        Err(Error::Conflict)
                    };
                }
                if self.records.len() + self.native.records.len() >= self.capacity {
                    return Err(Error::CapacityExceeded);
                }
            }
            // Dispatch is an execution claim, not a repeatable observation.
            // A second successful claim could let a second caller send the
            // same external effect. The state machine admits Reserved once.
            Event::Dispatch { .. } => {}
            Event::Started {
                request_id,
                turn_id,
            } => {
                if let Some(record) = self.native.records.get(request_id) {
                    if record.state == NativeReservationState::Running
                        && record.turn_id.as_ref() == Some(turn_id)
                    {
                        return Ok(Some(record.clone()));
                    }
                }
            }
            Event::Cancel { request_id } => {
                let record = self
                    .native
                    .records
                    .get(request_id)
                    .ok_or(Error::RequestNotFound)?;
                if record.cancel_requested {
                    return Ok(Some(record.clone()));
                }
            }
            Event::Stop { request_id, reason } => {
                let record = self
                    .native
                    .records
                    .get(request_id)
                    .ok_or(Error::RequestNotFound)?;
                if record.state == NativeReservationState::Released
                    && record.pre_dispatch_stop.as_ref() == Some(reason)
                {
                    return Ok(Some(record.clone()));
                }
            }
            Event::Observe { request_id, output } => {
                let record = self
                    .native
                    .records
                    .get(request_id)
                    .ok_or(Error::RequestNotFound)?;
                if record.observation.as_ref() == Some(output) {
                    return Ok(Some(record.clone()));
                }
            }
        }
        Ok(None)
    }
}

impl NativeJournal {
    pub(super) fn checkpoint_lines(&self) -> impl Iterator<Item = Result<String, Error>> + '_ {
        self.records.values().map(|record| {
            let checkpoint = NativeCheckpointV1 {
                maximum_in_flight: self.maximum_in_flight,
                record: record.clone(),
            };
            let json = serde_json::to_string(&checkpoint)
                .map_err(|_| Error::CorruptJournal("native checkpoint encode"))?;
            Ok(format!("{CHECKPOINT_PREFIX}{json}\n"))
        })
    }

    pub(super) fn replay_checkpoint(&mut self, json: &str) -> Result<(), Error> {
        let checkpoint: NativeCheckpointV1 = serde_json::from_str(json)
            .map_err(|_| Error::CorruptJournal("native checkpoint decode"))?;
        if checkpoint
            .maximum_in_flight
            .is_some_and(|limit| !(1..=256).contains(&limit))
        {
            return Err(Error::CorruptJournal("native checkpoint capacity"));
        }
        if self
            .maximum_in_flight
            .zip(checkpoint.maximum_in_flight)
            .is_some_and(|(left, right)| left != right)
        {
            return Err(Error::CorruptJournal("native checkpoint capacity drift"));
        }
        validate_checkpoint(&checkpoint.record)?;
        let is_active = checkpoint.record.state != NativeReservationState::Released;
        if self
            .records
            .insert(
                checkpoint.record.request.request_id.clone(),
                checkpoint.record,
            )
            .is_some()
        {
            return Err(Error::CorruptJournal("duplicate native checkpoint"));
        }
        self.maximum_in_flight = checkpoint.maximum_in_flight.or(self.maximum_in_flight);
        self.active_count += usize::from(is_active);
        if self
            .maximum_in_flight
            .is_none_or(|limit| self.active_count > limit)
        {
            return Err(Error::CorruptJournal(
                "native checkpoint in-flight capacity",
            ));
        }
        Ok(())
    }

    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        let event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("native decode"))?;
        self.apply(event)
    }

    fn apply(&mut self, event: Event) -> Result<(), Error> {
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
            if self.active_count >= maximum_in_flight {
                return Err(Error::CapacityExceeded);
            }
            self.maximum_in_flight = Some(maximum_in_flight);
            self.active_count += 1;
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
            Event::Reserve { .. } => return Err(Error::InvalidTransition),
            Event::Dispatch { request_id, .. }
            | Event::Started { request_id, .. }
            | Event::Cancel { request_id }
            | Event::Stop { request_id, .. }
            | Event::Observe { request_id, .. } => request_id,
        };
        let record = self.records.get_mut(id).ok_or(Error::RequestNotFound)?;
        let was_active = record.state != NativeReservationState::Released;
        match event {
            Event::Reserve { .. } => return Err(Error::InvalidTransition),
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
        let is_active = record.state != NativeReservationState::Released;
        if was_active && !is_active {
            self.active_count = self
                .active_count
                .checked_sub(1)
                .ok_or(Error::ArithmeticOverflow)?;
        } else if !was_active && is_active {
            self.active_count = self
                .active_count
                .checked_add(1)
                .ok_or(Error::ArithmeticOverflow)?;
            if self
                .maximum_in_flight
                .is_none_or(|limit| self.active_count > limit)
            {
                return Err(Error::CapacityExceeded);
            }
        }
        Ok(())
    }
}

pub(super) fn validate_checkpoint(record: &NativeRunRecord) -> Result<(), Error> {
    validate_identity(&record.request.request_id, "native request")?;
    validate_identity(&record.request.principal_id, "native principal")?;
    validate_digest(&record.request.payload_digest, "native payload")?;
    if record.request.worker_generation == 0
        || record.request.model.is_empty()
        || record.request.model.len() > 256
        || record.revision == 0
    {
        return Err(Error::CorruptJournal("native checkpoint request"));
    }
    if let Some(dispatch) = &record.dispatch {
        validate_identity(&dispatch.thread_id, "native thread")?;
        validate_identity(&dispatch.model_provider, "native provider")?;
        validate_digest(&dispatch.context_digest, "native context")?;
    }
    if let Some(turn_id) = &record.turn_id {
        validate_identity(turn_id, "native turn")?;
    }
    if record
        .pre_dispatch_stop
        .as_ref()
        .is_some_and(|reason| reason.is_empty() || reason.len() > 4096)
    {
        return Err(Error::CorruptJournal("native checkpoint stop"));
    }
    match record.state {
        NativeReservationState::Reserved => {
            if record.dispatch.is_some()
                || record.turn_id.is_some()
                || record.pre_dispatch_stop.is_some()
                || record.observation.is_some()
            {
                return Err(Error::CorruptJournal("native checkpoint reserved state"));
            }
        }
        NativeReservationState::Dispatching => {
            if record.dispatch.is_none()
                || record.turn_id.is_some()
                || record.pre_dispatch_stop.is_some()
                || record.observation.is_some()
            {
                return Err(Error::CorruptJournal("native checkpoint dispatching state"));
            }
        }
        NativeReservationState::Running => {
            if record.dispatch.is_none()
                || record.turn_id.is_none()
                || record.pre_dispatch_stop.is_some()
                || record.observation.is_some()
            {
                return Err(Error::CorruptJournal("native checkpoint running state"));
            }
        }
        NativeReservationState::Cancelling => {
            if record.dispatch.is_none() || !record.cancel_requested {
                return Err(Error::CorruptJournal("native checkpoint cancelling state"));
            }
        }
        NativeReservationState::Indeterminate => {
            if record.dispatch.is_none()
                || record
                    .observation
                    .as_ref()
                    .is_none_or(|output| output.terminal_observed)
            {
                return Err(Error::CorruptJournal(
                    "native checkpoint indeterminate state",
                ));
            }
        }
        NativeReservationState::Released => {
            let stopped = record.pre_dispatch_stop.is_some() && record.observation.is_none();
            let terminal = record
                .observation
                .as_ref()
                .is_some_and(|output| output.terminal_observed);
            if !stopped && !terminal {
                return Err(Error::CorruptJournal("native checkpoint released state"));
            }
        }
    }
    if let Some(output) = &record.observation {
        let mut candidate = record.clone();
        candidate.observation = None;
        apply_observation(&mut candidate, output.clone())?;
        if candidate.state != record.state {
            return Err(Error::CorruptJournal("native checkpoint observation state"));
        }
    }
    Ok(())
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
