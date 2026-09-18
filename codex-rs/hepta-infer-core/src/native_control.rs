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
pub struct NativeQuotaBinding {
    pub reservation_id: String,
    pub reservation_digest: String,
    pub reserved_requests: u64,
    pub reserved_tokens: u64,
    pub reserved_concurrency: u32,
    pub authority_epoch: u64,
    pub expires_at_unix_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeResourceBinding {
    pub resource_id: String,
    pub resource_digest: String,
    pub provider_id: String,
    pub model: String,
    pub generation: u64,
    pub expires_at_unix_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeAdmissionBinding {
    pub quota: NativeQuotaBinding,
    pub resource: NativeResourceBinding,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRequest {
    pub request_id: String,
    pub principal_id: String,
    pub worker_generation: u64,
    pub model: String,
    /// Binds the prompt, optional query, exact socket, execution timeout and policy evidence.
    pub payload_digest: String,
    /// Conservative per-request output-token hold. A later observed count can
    /// refine it; missing usage keeps the full hold.
    #[serde(default)]
    pub maximum_output_tokens: u64,
    /// Legacy native-v1 records omit this. Production provider dispatch must
    /// carry a quota/resource binding and a matching final-use witness.
    #[serde(default)]
    pub admission: Option<NativeAdmissionBinding>,
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

/// Final-use authority is independent from Agent health and provider
/// terminality. A claim is consumed before physical turn dispatch; only a
/// live revalidation at terminal publication can make a completed run
/// successful.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum NativeFinalUseAuthority {
    #[default]
    Unverified,
    Claimed {
        grant_id: String,
        authority_epoch: u64,
    },
    VerifiedAtTerminal {
        grant_id: String,
        authority_epoch: u64,
    },
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
    #[serde(default)]
    pub final_use_authority: NativeFinalUseAuthority,
}

impl NativeRunOutput {
    /// The CLI and callers must not infer authorized success from provider
    /// completion alone, including when replaying a historical observation.
    pub fn succeeded(&self) -> bool {
        self.terminal_observed
            && self.status == NativeRunStatus::Completed
            && self.owner_authority == NativeOwnerAuthority::ObservedReady
            && matches!(
                self.final_use_authority,
                NativeFinalUseAuthority::VerifiedAtTerminal { .. }
            )
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
pub struct NativeFinalUseWitness {
    pub grant_id: String,
    pub authority_epoch: u64,
    pub expires_at_unix_ms: u64,
    pub binding_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatch {
    pub thread_id: String,
    pub model_provider: String,
    /// Exact serialized additional context, including its owner snapshot.
    pub context_digest: String,
    /// Legacy records omit this. New production dispatches persist the
    /// independently verified single-use grant before turn/start.
    #[serde(default)]
    pub final_use: Option<NativeFinalUseWitness>,
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
    /// A locally proven pre-dispatch stop releases a slot without pretending
    /// to have observed a provider terminal event or zero token consumption.
    pub pre_dispatch_stop: Option<String>,
    pub observation: Option<NativeRunOutput>,
}

#[derive(Clone, Debug, Default)]
pub(super) struct NativeJournal {
    maximum_in_flight: Option<usize>,
    pub(super) records: BTreeMap<String, NativeRunRecord>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
    /// Compaction-only canonical record. Live mutation rejects this variant;
    /// replay validates the complete record before accepting it.
    Snapshot {
        record: NativeRunRecord,
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
        if self.records.len() + self.native.records.len() >= self.capacity {
            return Err(Error::CapacityExceeded);
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

    fn ensure_native_dispatch_space(&mut self) -> Result<(), Error> {
        // This exclusive owner serializes active calls. Before refusing a new
        // external execution because event history consumed the headroom,
        // compact native-v1 events under the same locked owner. The complete
        // predecessor remains in a bounded private content-addressed archive.
        let high_water =
            super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64;
        if self.journal_bytes > high_water {
            self.compact_native_journal(/*retain_archives*/ 4)?;
        }
        if self.journal_bytes > high_water {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }

    fn commit_native(&mut self, request_id: &str, event: Event) -> Result<NativeRunRecord, Error> {
        let mut next = self.native.clone();
        next.apply(event.clone(), /*replay*/ false)?;
        let json =
            serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("native encode"))?;
        let encoded = format!("{JOURNAL_PREFIX}{json}\n");
        let high_water =
            super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64;
        let next_bytes = self
            .journal_bytes
            .checked_add(encoded.len() as u64)
            .ok_or(Error::ArithmeticOverflow)?;
        if next_bytes > high_water {
            self.compact_native_journal(/*retain_archives*/ 4)?;
        }
        self.append(&encoded)?;
        self.native = next;
        self.native
            .records
            .get(request_id)
            .cloned()
            .ok_or(Error::RequestNotFound)
    }
}

impl NativeJournal {
    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        let event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("native decode"))?;
        self.apply(event, /*replay*/ true)
    }

    pub(super) fn snapshot_lines(&self) -> Result<Vec<String>, Error> {
        let Some(maximum_in_flight) = self.maximum_in_flight else {
            return if self.records.is_empty() {
                Ok(Vec::new())
            } else {
                Err(Error::CorruptJournal("native slot limit"))
            };
        };
        let mut replayed = NativeJournal::default();
        let mut lines = Vec::with_capacity(self.records.len());
        for record in self.records.values() {
            let event = Event::Snapshot {
                record: record.clone(),
                maximum_in_flight,
            };
            replayed.apply(event.clone(), /*replay*/ true)?;
            let json = serde_json::to_string(&event)
                .map_err(|_| Error::CorruptJournal("native encode"))?;
            lines.push(format!("{JOURNAL_PREFIX}{json}\n"));
        }
        if replayed.records != self.records
            || replayed.maximum_in_flight != self.maximum_in_flight
        {
            return Err(Error::CorruptJournal("native snapshot mismatch"));
        }
        Ok(lines)
    }

    fn apply(&mut self, event: Event, replay: bool) -> Result<(), Error> {
        if let Event::Snapshot {
            record,
            maximum_in_flight,
        } = event
        {
            if !replay {
                return Err(Error::InvalidTransition);
            }
            validate_snapshot_record(&record, maximum_in_flight)?;
            if self
                .maximum_in_flight
                .is_some_and(|limit| limit != maximum_in_flight)
                || self.records.contains_key(&record.request.request_id)
            {
                return Err(Error::Conflict);
            }
            self.maximum_in_flight = Some(maximum_in_flight);
            self.records.insert(record.request.request_id.clone(), record);
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
            validate_admission_binding(&request)?;
            if !replay {
                enforce_quota(&self.records, &request)?;
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
            Event::Snapshot { .. } | Event::Reserve { .. } => {
                return Err(Error::InvalidTransition);
            }
            Event::Dispatch { request_id, .. }
            | Event::Started { request_id, .. }
            | Event::Cancel { request_id }
            | Event::Stop { request_id, .. }
            | Event::Observe { request_id, .. } => request_id,
        };
        let record = self.records.get_mut(id).ok_or(Error::RequestNotFound)?;
        match event {
            Event::Snapshot { .. } | Event::Reserve { .. } => {
                return Err(Error::InvalidTransition);
            }
            Event::Dispatch { dispatch, .. } => {
                if record.state != NativeReservationState::Reserved {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&dispatch.thread_id, "native thread")?;
                validate_identity(&dispatch.model_provider, "native provider")?;
                validate_digest(&dispatch.context_digest, "native context")?;
                validate_dispatch_authority(record, &dispatch)?;
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
                if record.state != NativeReservationState::Reserved
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

fn validate_snapshot_record(
    record: &NativeRunRecord,
    maximum_in_flight: usize,
) -> Result<(), Error> {
    if !(1..=256).contains(&maximum_in_flight) || record.revision == 0 {
        return Err(Error::CapacityExceeded);
    }
    validate_identity(&record.request.request_id, "native request")?;
    validate_identity(&record.request.principal_id, "native principal")?;
    validate_digest(&record.request.payload_digest, "native payload")?;
    if record.request.worker_generation == 0
        || record.request.model.is_empty()
        || record.request.model.len() > 256
    {
        return Err(Error::InvalidIdentity("native worker/model"));
    }
    validate_admission_binding(&record.request)?;

    match record.state {
        NativeReservationState::Reserved => {
            if record.dispatch.is_some()
                || record.turn_id.is_some()
                || record.cancel_requested
                || record.pre_dispatch_stop.is_some()
                || record.observation.is_some()
            {
                return Err(Error::CorruptJournal("native reserved snapshot"));
            }
        }
        NativeReservationState::Dispatching => {
            if record.dispatch.is_none()
                || record.turn_id.is_some()
                || record.cancel_requested
                || record.pre_dispatch_stop.is_some()
                || record.observation.is_some()
            {
                return Err(Error::CorruptJournal("native dispatch snapshot"));
            }
        }
        NativeReservationState::Running => {
            if record.dispatch.is_none()
                || record.turn_id.is_none()
                || record.cancel_requested
                || record.pre_dispatch_stop.is_some()
                || record.observation.is_some()
            {
                return Err(Error::CorruptJournal("native running snapshot"));
            }
        }
        NativeReservationState::Cancelling => {
            if record.dispatch.is_none()
                || !record.cancel_requested
                || record.pre_dispatch_stop.is_some()
                || record.observation.is_some()
            {
                return Err(Error::CorruptJournal("native cancelling snapshot"));
            }
        }
        NativeReservationState::Indeterminate => {
            if record.dispatch.is_none()
                || record.pre_dispatch_stop.is_some()
                || record
                    .observation
                    .as_ref()
                    .is_none_or(|output| output.terminal_observed)
            {
                return Err(Error::CorruptJournal("native indeterminate snapshot"));
            }
        }
        NativeReservationState::Released => {
            let local_stop = record.pre_dispatch_stop.is_some()
                && record.dispatch.is_none()
                && record.observation.is_none();
            let terminal = record.pre_dispatch_stop.is_none()
                && record.dispatch.is_some()
                && record
                    .observation
                    .as_ref()
                    .is_some_and(|output| output.terminal_observed);
            if !local_stop && !terminal {
                return Err(Error::CorruptJournal("native released snapshot"));
            }
        }
    }

    if let Some(dispatch) = &record.dispatch {
        validate_identity(&dispatch.thread_id, "native thread")?;
        validate_identity(&dispatch.model_provider, "native provider")?;
        validate_digest(&dispatch.context_digest, "native context")?;
        validate_dispatch_authority(record, dispatch)?;
    }
    if let Some(turn_id) = &record.turn_id {
        validate_identity(turn_id, "native turn")?;
    }
    if let Some(reason) = &record.pre_dispatch_stop
        && (reason.is_empty() || reason.len() > 4096)
    {
        return Err(Error::CorruptJournal("native stop snapshot"));
    }
    if let Some(output) = &record.observation {
        let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
        if output.thread_id != dispatch.thread_id
            || output.model_provider != dispatch.model_provider
            || output.model != record.request.model
            || record
                .turn_id
                .as_ref()
                .is_some_and(|turn| turn != &output.turn_id)
            || output.output.len() > 1024 * 1024
            || output
                .stop_reason
                .as_ref()
                .is_some_and(|reason| reason.len() > 4096)
            || output.terminal_observed == (output.status == NativeRunStatus::Indeterminate)
        {
            return Err(Error::CorruptJournal("native observation snapshot"));
        }
        validate_final_use_observation(record, output)?;
    }
    Ok(())
}

fn validate_admission_binding(request: &NativeRequest) -> Result<(), Error> {
    match &request.admission {
        None => {
            if request.maximum_output_tokens != 0 {
                return Err(Error::InvalidTransition);
            }
            Ok(())
        }
        Some(binding) => {
            validate_identity(&binding.quota.reservation_id, "native quota reservation")?;
            validate_digest(&binding.quota.reservation_digest, "native quota reservation")?;
            validate_identity(&binding.resource.resource_id, "native resource")?;
            validate_digest(&binding.resource.resource_digest, "native resource")?;
            validate_identity(&binding.resource.provider_id, "native provider")?;
            if request.maximum_output_tokens == 0
                || binding.quota.reserved_requests == 0
                || binding.quota.reserved_tokens < request.maximum_output_tokens
                || binding.quota.reserved_concurrency == 0
                || binding.quota.authority_epoch == 0
                || binding.quota.expires_at_unix_seconds == 0
                || binding.resource.generation == 0
                || binding.resource.expires_at_unix_seconds == 0
                || binding.resource.generation != request.worker_generation
                || binding.resource.model != request.model
            {
                return Err(Error::InvalidTransition);
            }
            Ok(())
        }
    }
}

fn held_tokens(record: &NativeRunRecord) -> Result<u64, Error> {
    if record.pre_dispatch_stop.is_some() {
        return Ok(0);
    }
    Ok(record
        .observation
        .as_ref()
        .and_then(|output| output.observed_output_tokens)
        .unwrap_or(record.request.maximum_output_tokens))
}

fn enforce_quota(records: &BTreeMap<String, NativeRunRecord>, request: &NativeRequest) -> Result<(), Error> {
    let Some(binding) = &request.admission else {
        return Ok(());
    };
    let mut requests = 1_u64;
    let mut active = 1_u64;
    let mut tokens = request.maximum_output_tokens;
    for record in records.values() {
        let Some(existing) = &record.request.admission else {
            continue;
        };
        if existing.quota.reservation_id == binding.quota.reservation_id
            && existing.quota.reservation_digest != binding.quota.reservation_digest
        {
            return Err(Error::Conflict);
        }
        if existing.quota.reservation_digest != binding.quota.reservation_digest {
            continue;
        }
        if existing.resource != binding.resource {
            return Err(Error::Conflict);
        }
        requests = requests.checked_add(1).ok_or(Error::ArithmeticOverflow)?;
        if record.state != NativeReservationState::Released {
            active = active.checked_add(1).ok_or(Error::ArithmeticOverflow)?;
        }
        tokens = tokens
            .checked_add(held_tokens(record)?)
            .ok_or(Error::ArithmeticOverflow)?;
    }
    if requests > binding.quota.reserved_requests
        || active > u64::from(binding.quota.reserved_concurrency)
        || tokens > binding.quota.reserved_tokens
    {
        return Err(Error::CapacityExceeded);
    }
    Ok(())
}

fn validate_final_use_witness(witness: &NativeFinalUseWitness) -> Result<(), Error> {
    validate_identity(&witness.grant_id, "native final-use grant")?;
    validate_digest(&witness.binding_digest, "native final-use binding")?;
    if witness.authority_epoch == 0 || witness.expires_at_unix_ms == 0 {
        return Err(Error::InvalidTransition);
    }
    Ok(())
}

fn validate_dispatch_authority(record: &NativeRunRecord, dispatch: &NativeDispatch) -> Result<(), Error> {
    match &record.request.admission {
        None => {
            if dispatch.final_use.is_some() {
                return Err(Error::Conflict);
            }
        }
        Some(admission) => {
            if dispatch.model_provider != admission.resource.provider_id {
                return Err(Error::AssignmentMismatch);
            }
            let witness = dispatch.final_use.as_ref().ok_or(Error::InvalidTransition)?;
            validate_final_use_witness(witness)?;
            if witness.authority_epoch != admission.quota.authority_epoch {
                return Err(Error::AssignmentMismatch);
            }
        }
    }
    Ok(())
}

fn final_use_identity(authority: &NativeFinalUseAuthority) -> Option<(&str, u64)> {
    match authority {
        NativeFinalUseAuthority::Claimed {
            grant_id,
            authority_epoch,
        }
        | NativeFinalUseAuthority::VerifiedAtTerminal {
            grant_id,
            authority_epoch,
        } => Some((grant_id.as_str(), *authority_epoch)),
        NativeFinalUseAuthority::Unverified | NativeFinalUseAuthority::Lost { .. } => None,
    }
}

fn validate_final_use_observation(record: &NativeRunRecord, output: &NativeRunOutput) -> Result<(), Error> {
    if let NativeFinalUseAuthority::Lost { reason } = &output.final_use_authority
        && (reason.is_empty() || reason.len() > 4096)
    {
        return Err(Error::InvalidIdentity("final-use authority loss reason"));
    }
    if let Some(admission) = &record.request.admission {
        let witness = record
            .dispatch
            .as_ref()
            .and_then(|dispatch| dispatch.final_use.as_ref())
            .ok_or(Error::AssignmentMismatch)?;
        match &output.final_use_authority {
            NativeFinalUseAuthority::Claimed { .. }
            | NativeFinalUseAuthority::VerifiedAtTerminal { .. } => {
                let (grant_id, authority_epoch) =
                    final_use_identity(&output.final_use_authority).ok_or(Error::AssignmentMismatch)?;
                if grant_id != witness.grant_id
                    || authority_epoch != witness.authority_epoch
                    || authority_epoch != admission.quota.authority_epoch
                {
                    return Err(Error::AssignmentMismatch);
                }
            }
            NativeFinalUseAuthority::Lost { .. } => {}
            NativeFinalUseAuthority::Unverified => return Err(Error::AssignmentMismatch),
        }
        if matches!(
            output.final_use_authority,
            NativeFinalUseAuthority::VerifiedAtTerminal { .. }
        ) && !output.terminal_observed
        {
            return Err(Error::TerminalObservationMissing);
        }
    }

    if let Some(previous) = &record.observation {
        match (&previous.final_use_authority, &output.final_use_authority) {
            (NativeFinalUseAuthority::Lost { .. }, next)
                if next != &previous.final_use_authority =>
            {
                return Err(Error::Conflict);
            }
            (NativeFinalUseAuthority::VerifiedAtTerminal { .. }, next)
                if next != &previous.final_use_authority =>
            {
                return Err(Error::Conflict);
            }
            (NativeFinalUseAuthority::Unverified, NativeFinalUseAuthority::Unverified) => {}
            (NativeFinalUseAuthority::Unverified, _) => return Err(Error::Conflict),
            (
                NativeFinalUseAuthority::Claimed {
                    grant_id: previous_id,
                    authority_epoch: previous_epoch,
                },
                NativeFinalUseAuthority::Claimed {
                    grant_id: next_id,
                    authority_epoch: next_epoch,
                }
                | NativeFinalUseAuthority::VerifiedAtTerminal {
                    grant_id: next_id,
                    authority_epoch: next_epoch,
                },
            ) if previous_id == next_id && previous_epoch == next_epoch => {}
            (NativeFinalUseAuthority::Claimed { .. }, NativeFinalUseAuthority::Lost { .. }) => {}
            (NativeFinalUseAuthority::Claimed { .. }, _) => return Err(Error::Conflict),
            _ => {}
        }
    }
    Ok(())
}

fn apply_observation(record: &mut NativeRunRecord, output: NativeRunOutput) -> Result<(), Error> {
    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
    validate_final_use_observation(record, &output)?;
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
