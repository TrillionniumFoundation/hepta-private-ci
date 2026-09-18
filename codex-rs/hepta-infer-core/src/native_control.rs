//! Hosted runs share the control owner's journal and exclusive writer lock.
//! A reservation is one local in-flight slot, not a token or payment grant.
//! Unknown execution retains that slot; unknown token usage remains `None`.

use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
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
    /// Raw text exists only in the live call. Durable observations redact it.
    pub output: String,
    /// Digest of the complete observed output. Historical records may omit it.
    #[serde(default)]
    pub output_digest: Option<String>,
    /// False means the durable record intentionally retained only the digest.
    #[serde(default = "default_output_retained")]
    pub output_retained: bool,
    pub observed_output_tokens: Option<u64>,
    pub terminal_observed: bool,
    pub stop_reason: Option<String>,
    #[serde(default)]
    pub owner_authority: NativeOwnerAuthority,
    /// True only when the durable dispatch carries a final-use witness.
    #[serde(default)]
    pub final_use_authorized: bool,
}

const fn default_output_retained() -> bool {
    true
}

impl NativeRunOutput {
    /// Provider completion and owner health are observations, not effect authority.
    /// Success additionally requires a durable final-use admission witness.
    pub fn succeeded(&self) -> bool {
        self.terminal_observed
            && self.status == NativeRunStatus::Completed
            && self.owner_authority == NativeOwnerAuthority::ObservedReady
            && self.final_use_authorized
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
    pub signer_id: String,
    pub authority_epoch: u64,
    pub grant_id: String,
    pub expires_at_unix_ms: u64,
    /// Digest of the exact FinalUseBinding admitted by kernel.authority.
    pub binding_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatch {
    pub thread_id: String,
    pub model_provider: String,
    /// Exact serialized additional context, including its owner snapshot.
    pub context_digest: String,
    /// Public evidence that an opaque final-use token admitted this dispatch.
    /// This is not a serialized VerifiedUseToken and cannot grant authority.
    #[serde(default)]
    pub final_use_witness: Option<NativeFinalUseWitness>,
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
    output_history_redacted: bool,
    pub(super) records: BTreeMap<String, NativeRunRecord>,
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
    /// Marker written only by the atomic history rewrite. New observations after
    /// this marker are already digest-only, so subsequent opens can skip rescans.
    OutputHistoryRedacted,
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
        mut output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let authorized = record
            .dispatch
            .as_ref()
            .and_then(|dispatch| dispatch.final_use_witness.as_ref())
            .is_some();
        if output.final_use_authorized && !authorized {
            return Err(Error::Conflict);
        }
        output.final_use_authorized = authorized;
        let output = persisted_observation(output)?;
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

    /// Rewrite native observation history without raw provider text. The old
    /// journal remains locked until the fully-synced replacement is atomically
    /// installed and locked, so there is no second-writer admission window.
    pub fn redact_native_output_history(&mut self) -> Result<NativeOutputRedactionReceipt, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        if self.native.output_history_redacted {
            return Ok(NativeOutputRedactionReceipt {
                previous_journal_bytes: self.journal_bytes,
                rewritten_journal_bytes: self.journal_bytes,
                redacted_observations: 0,
            });
        }
        self.file.sync_all()?;
        let mut source = Vec::new();
        File::open(&self.path)?
            .take(super::MAX_JOURNAL_BYTES + 1)
            .read_to_end(&mut source)?;
        if source.len() as u64 > super::MAX_JOURNAL_BYTES {
            return Err(Error::CapacityExceeded);
        }
        if !source.is_empty() && source.last() != Some(&b'\n') {
            return Err(Error::CorruptJournal("incomplete line"));
        }
        let mut rewritten = Vec::with_capacity(source.len());
        let mut next_native = NativeJournal::default();
        let mut redacted_observations = 0_usize;
        let body = source.strip_suffix(b"\n").unwrap_or(source.as_slice());
        if !body.is_empty() {
            for raw_line in body.split(|byte| *byte == b'\n') {
                let line = raw_line.strip_suffix(b"\r").unwrap_or(raw_line);
                let text = std::str::from_utf8(line)
                    .map_err(|_| Error::CorruptJournal("utf8"))?;
                if let Some(json) = text.strip_prefix(JOURNAL_PREFIX) {
                    let mut event: Event = serde_json::from_str(json)
                        .map_err(|_| Error::CorruptJournal("native decode"))?;
                    if let Event::Observe { output, .. } = &mut event {
                        if output.output_retained {
                            redacted_observations = redacted_observations
                                .checked_add(1)
                                .ok_or(Error::ArithmeticOverflow)?;
                        }
                        *output = persisted_observation(output.clone())?;
                    }
                    next_native.apply(event.clone())?;
                    let json = serde_json::to_string(&event)
                        .map_err(|_| Error::CorruptJournal("native encode"))?;
                    rewritten.extend_from_slice(JOURNAL_PREFIX.as_bytes());
                    rewritten.extend_from_slice(json.as_bytes());
                    rewritten.push(b'\n');
                } else {
                    rewritten.extend_from_slice(raw_line);
                    rewritten.push(b'\n');
                }
            }
        }
        let marker = Event::OutputHistoryRedacted;
        next_native.apply(marker.clone())?;
        let marker_json = serde_json::to_string(&marker)
            .map_err(|_| Error::CorruptJournal("native encode"))?;
        rewritten.extend_from_slice(JOURNAL_PREFIX.as_bytes());
        rewritten.extend_from_slice(marker_json.as_bytes());
        rewritten.push(b'\n');
        if rewritten.len() as u64 > super::MAX_JOURNAL_BYTES {
            return Err(Error::CapacityExceeded);
        }

        let next_path = native_redaction_path(&self.path);
        let mut options = OpenOptions::new();
        options.create_new(true).append(true).read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut replacement = options.open(&next_path)?;
        replacement
            .try_lock()
            .map_err(|_| Error::WriterUnavailable)?;
        replacement.write_all(&rewritten)?;
        replacement.flush()?;
        replacement.sync_all()?;
        fs::rename(&next_path, &self.path)?;
        // The pathname now names the replacement inode. Switch the live locked
        // handle immediately so no later fallible durability step can leave this
        // owner holding only the unlinked predecessor lock.
        let old = std::mem::replace(&mut self.file, replacement);
        drop(old);
        let previous_journal_bytes = self.journal_bytes;
        self.journal_bytes = rewritten.len() as u64;
        self.native = next_native;
        #[cfg(unix)]
        {
            let parent = self
                .path
                .parent()
                .filter(|parent| !parent.as_os_str().is_empty())
                .unwrap_or_else(|| std::path::Path::new("."));
            if let Err(error) = File::open(parent).and_then(|directory| directory.sync_all()) {
                self.poisoned = true;
                return Err(error.into());
            }
        }
        Ok(NativeOutputRedactionReceipt {
            previous_journal_bytes,
            rewritten_journal_bytes: self.journal_bytes,
            redacted_observations,
        })
    }

    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    fn ensure_native_dispatch_space(&self) -> Result<(), Error> {
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
    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        let event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("native decode"))?;
        self.apply(event)
    }

    fn apply(&mut self, event: Event) -> Result<(), Error> {
        if matches!(&event, Event::OutputHistoryRedacted) {
            self.output_history_redacted = true;
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
            Event::Reserve { .. } | Event::OutputHistoryRedacted => {
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
            Event::Reserve { .. } | Event::OutputHistoryRedacted => {
                return Err(Error::InvalidTransition);
            }
            Event::Dispatch { dispatch, .. } => {
                if record.state != NativeReservationState::Reserved {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&dispatch.thread_id, "native thread")?;
                validate_identity(&dispatch.model_provider, "native provider")?;
                validate_digest(&dispatch.context_digest, "native context")?;
                if let Some(witness) = &dispatch.final_use_witness {
                    validate_final_use_identity(&witness.signer_id, "native final-use signer")?;
                    validate_final_use_identity(&witness.grant_id, "native final-use grant")?;
                    validate_digest(&witness.binding_digest, "native final-use binding")?;
                    if witness.authority_epoch == 0 || witness.expires_at_unix_ms == 0 {
                        return Err(Error::InvalidTime);
                    }
                }
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

fn apply_observation(record: &mut NativeRunRecord, output: NativeRunOutput) -> Result<(), Error> {
    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
    if output.final_use_authorized != dispatch.final_use_witness.is_some() {
        return Err(Error::Conflict);
    }
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
    let output_identity = observation_output_digest(&output)?;
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
        if previous.final_use_authorized != output.final_use_authorized
            || (!previous.output_retained && output.output_retained)
        {
            return Err(Error::Conflict);
        }
        if previous.terminal_observed
            && (previous.status != output.status
                || !output.terminal_observed
                || observation_output_digest(previous)? != output_identity)
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

fn persisted_observation(mut output: NativeRunOutput) -> Result<NativeRunOutput, Error> {
    if output.output_retained {
        let digest = Digest32::of_bytes(output.output.as_bytes()).to_string();
        if output
            .output_digest
            .as_ref()
            .is_some_and(|existing| existing != &digest)
        {
            return Err(Error::Conflict);
        }
        output.output_digest = Some(digest);
        output.output.clear();
        output.output_retained = false;
    } else {
        if !output.output.is_empty() || output.output_digest.is_none() {
            return Err(Error::CorruptJournal("redacted native output"));
        }
        validate_digest(
            output.output_digest.as_deref().unwrap_or_default(),
            "native output",
        )?;
    }
    Ok(output)
}

fn observation_output_digest(output: &NativeRunOutput) -> Result<String, Error> {
    if let Some(digest) = &output.output_digest {
        validate_digest(digest, "native output")?;
        if output.output_retained {
            let observed = Digest32::of_bytes(output.output.as_bytes()).to_string();
            if observed != *digest {
                return Err(Error::Conflict);
            }
        } else if !output.output.is_empty() {
            return Err(Error::CorruptJournal("redacted native output"));
        }
        return Ok(digest.clone());
    }
    if output.output_retained {
        return Ok(Digest32::of_bytes(output.output.as_bytes()).to_string());
    }
    Err(Error::CorruptJournal("missing native output digest"))
}

fn validate_final_use_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn native_redaction_path(path: &std::path::Path) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(".redact-next");
    PathBuf::from(value)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeOutputRedactionReceipt {
    pub previous_journal_bytes: u64,
    pub rewritten_journal_bytes: u64,
    pub redacted_observations: usize,
}

#[cfg(test)]
#[path = "native_control_tests.rs"]
mod tests;
