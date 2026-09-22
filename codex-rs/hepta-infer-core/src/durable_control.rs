#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

#[path = "native_control.rs"]
pub mod native;

const MAX_RECORDS: usize = 16_384;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_JOURNAL_LINE_BYTES: usize = 8 * 1024 * 1024;
const MAX_TOKENS: u32 = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RequestState {
    Pending,
    Reserved,
    Assigned,
    Cancelling,
    Completed,
    Failed,
    Cancelled,
    Indeterminate,
}

impl RequestState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Reserved => "reserved",
            Self::Assigned => "assigned",
            Self::Cancelling => "cancelling",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::Indeterminate => "indeterminate",
        }
    }

    fn parse(value: &str) -> Result<Self, Error> {
        match value {
            "pending" => Ok(Self::Pending),
            "reserved" => Ok(Self::Reserved),
            "assigned" => Ok(Self::Assigned),
            "cancelling" => Ok(Self::Cancelling),
            "completed" => Ok(Self::Completed),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            "indeterminate" => Ok(Self::Indeterminate),
            _ => Err(Error::CorruptJournal("request state")),
        }
    }

    fn terminal(self) -> bool {
        matches!(
            self,
            Self::Completed | Self::Failed | Self::Cancelled | Self::Indeterminate
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceRequest {
    pub request_id: String,
    pub principal_id: String,
    pub model_digest: String,
    pub payload_digest: String,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Reservation {
    pub reservation_id: String,
    pub quota_units: u64,
    pub maximum_tokens: u32,
    pub authority_epoch: u64,
    pub valid_until_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Assignment {
    pub worker_id: String,
    pub worker_generation: u64,
    pub assignment_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TerminalObservation {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub model_digest: String,
    pub payload_digest: String,
    pub terminal_observed: bool,
    pub terminal_status: Option<RequestState>,
    pub output_digest: Option<String>,
    pub consumed_tokens: u32,
    pub usage_units: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RequestRecord {
    pub request: InferenceRequest,
    pub revision: u64,
    pub state: RequestState,
    pub reservation: Option<Reservation>,
    pub assignment: Option<Assignment>,
    pub terminal_observation_digest: Option<String>,
    pub consumed_tokens: u32,
    pub usage_units: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlReceipt {
    pub request_id: String,
    pub revision: u64,
    pub state: RequestState,
    pub idempotent: bool,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidTime,
    InvalidTokens,
    CapacityExceeded,
    RequestNotFound,
    Conflict,
    InvalidTransition,
    StaleRevision,
    ReservationMismatch,
    AssignmentMismatch,
    UsageExceeded,
    TerminalObservationMissing,
    CorruptJournal(&'static str),
    Io(String),
    ArithmeticOverflow,
    WriterUnavailable,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

impl From<std::io::Error> for Error {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.to_string())
    }
}

#[derive(Debug)]
pub struct DurableInferenceControl {
    path: PathBuf,
    file: File,
    records: BTreeMap<String, RequestRecord>,
    native: native::NativeJournal,
    capacity: usize,
    journal_bytes: u64,
    poisoned: bool,
}

impl DurableInferenceControl {
    pub fn open(path: impl AsRef<Path>, capacity: usize) -> Result<Self, Error> {
        if capacity == 0 || capacity > MAX_RECORDS {
            return Err(Error::CapacityExceeded);
        }
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut options = OpenOptions::new();
        options.create(true).append(true).read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = options.open(&path)?;
        // Lock before replay: two owners must never admit from the same stale cut.
        file.try_lock().map_err(|_| Error::WriterUnavailable)?;
        let mut records = BTreeMap::new();
        let mut native = native::NativeJournal::default();
        let mut reader = BufReader::new(file.try_clone()?);
        let mut journal_bytes = 0_u64;
        let mut line = Vec::new();
        loop {
            line.clear();
            // Bound actual reads and allocation, including files whose metadata
            // races with open. One extra byte distinguishes EOF from overflow.
            let remaining = MAX_JOURNAL_BYTES.saturating_sub(journal_bytes) + 1;
            let limit = remaining.min(MAX_JOURNAL_LINE_BYTES as u64 + 1);
            let count = (&mut reader).take(limit).read_until(b'\n', &mut line)?;
            if count == 0 {
                break;
            }
            journal_bytes += count as u64;
            if count > MAX_JOURNAL_LINE_BYTES || journal_bytes > MAX_JOURNAL_BYTES {
                return Err(Error::CapacityExceeded);
            }
            if line.pop() != Some(b'\n') {
                return Err(Error::CorruptJournal("incomplete line"));
            }
            if line.last() == Some(&b'\r') {
                line.pop();
            }
            let line = std::str::from_utf8(&line).map_err(|_| Error::CorruptJournal("utf8"))?;
            if line.is_empty() {
                continue;
            }
            if let Some(json) = line.strip_prefix(native::JOURNAL_PREFIX) {
                native.replay(json)?;
            } else {
                apply_event(&mut records, &decode_event(line)?, /*replay*/ true)?;
            }
            if records.len() + native.records.len() > capacity
                || records.keys().any(|id| native.records.contains_key(id))
            {
                return Err(Error::CapacityExceeded);
            }
        }
        #[cfg(unix)]
        {
            let parent = path
                .parent()
                .filter(|parent| !parent.as_os_str().is_empty())
                .unwrap_or_else(|| Path::new("."));
            File::open(parent)?.sync_all()?;
        }
        Ok(Self {
            path,
            file,
            records,
            native,
            capacity,
            journal_bytes,
            poisoned: false,
        })
    }

    pub fn submit(
        &mut self,
        now_ms: u64,
        request: InferenceRequest,
    ) -> Result<ControlReceipt, Error> {
        validate_request(now_ms, &request)?;
        if let Some(current) = self.records.get(&request.request_id) {
            if current.request == request {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(Error::Conflict);
        }
        if self.native.records.contains_key(&request.request_id) {
            return Err(Error::Conflict);
        }
        if self.records.len() + self.native.records.len() >= self.capacity {
            return Err(Error::CapacityExceeded);
        }
        let event = Event::Submit(request);
        self.commit(event)
    }

    pub fn reserve(
        &mut self,
        now_ms: u64,
        request_id: &str,
        expected_revision: u64,
        reservation: Reservation,
    ) -> Result<ControlReceipt, Error> {
        validate_identity(request_id, "request")?;
        validate_reservation(now_ms, &reservation)?;
        let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
        if record.revision != expected_revision {
            return Err(Error::StaleRevision);
        }
        if record.state == RequestState::Reserved
            && record.reservation.as_ref() == Some(&reservation)
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        if record.state != RequestState::Pending {
            return Err(Error::InvalidTransition);
        }
        if reservation.maximum_tokens < record.request.maximum_tokens {
            return Err(Error::UsageExceeded);
        }
        self.commit(Event::Reserve {
            request_id: request_id.to_string(),
            expected_revision,
            reservation,
        })
    }

    pub fn assign(
        &mut self,
        request_id: &str,
        expected_revision: u64,
        assignment: Assignment,
    ) -> Result<ControlReceipt, Error> {
        validate_identity(request_id, "request")?;
        validate_assignment(&assignment)?;
        let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
        if record.revision != expected_revision {
            return Err(Error::StaleRevision);
        }
        if record.state == RequestState::Assigned && record.assignment.as_ref() == Some(&assignment)
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        if record.state != RequestState::Reserved {
            return Err(Error::InvalidTransition);
        }
        self.commit(Event::Assign {
            request_id: request_id.to_string(),
            expected_revision,
            assignment,
        })
    }

    pub fn cancel(
        &mut self,
        request_id: &str,
        expected_revision: u64,
    ) -> Result<ControlReceipt, Error> {
        validate_identity(request_id, "request")?;
        let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
        if record.revision != expected_revision {
            return Err(Error::StaleRevision);
        }
        if record.state == RequestState::Cancelled || record.state == RequestState::Cancelling {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        if record.state.terminal() {
            return Err(Error::InvalidTransition);
        }
        self.commit(Event::Cancel {
            request_id: request_id.to_string(),
            expected_revision,
        })
    }

    pub fn settle(
        &mut self,
        request_id: &str,
        expected_revision: u64,
        observation_digest: String,
        observation: TerminalObservation,
    ) -> Result<ControlReceipt, Error> {
        validate_identity(request_id, "request")?;
        validate_digest(&observation_digest, "observation")?;
        validate_observation(&observation)?;
        let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
        if record.revision != expected_revision {
            return Err(Error::StaleRevision);
        }
        if record.terminal_observation_digest.as_ref() == Some(&observation_digest) {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        if record.state.terminal() {
            return Err(Error::Conflict);
        }
        let reservation = record
            .reservation
            .as_ref()
            .ok_or(Error::ReservationMismatch)?;
        let assignment = record
            .assignment
            .as_ref()
            .ok_or(Error::AssignmentMismatch)?;
        if observation.request_id != record.request.request_id
            || observation.reservation_id != reservation.reservation_id
            || observation.worker_id != assignment.worker_id
            || observation.worker_generation != assignment.worker_generation
            || observation.model_digest != record.request.model_digest
            || observation.payload_digest != record.request.payload_digest
        {
            return Err(Error::AssignmentMismatch);
        }
        if observation.consumed_tokens > reservation.maximum_tokens {
            return Err(Error::UsageExceeded);
        }
        if observation.terminal_observed {
            let status = observation
                .terminal_status
                .ok_or(Error::TerminalObservationMissing)?;
            if !matches!(
                status,
                RequestState::Completed | RequestState::Failed | RequestState::Cancelled
            ) {
                return Err(Error::InvalidTransition);
            }
            if matches!(status, RequestState::Completed) && observation.output_digest.is_none() {
                return Err(Error::TerminalObservationMissing);
            }
        } else if observation.terminal_status.is_some() || observation.output_digest.is_some() {
            return Err(Error::TerminalObservationMissing);
        }
        self.commit(Event::Settle {
            request_id: request_id.to_string(),
            expected_revision,
            observation_digest,
            observation,
        })
    }

    pub fn get(&self, request_id: &str) -> Option<&RequestRecord> {
        self.records.get(request_id)
    }

    pub fn journal_path(&self) -> &Path {
        &self.path
    }

    fn commit(&mut self, event: Event) -> Result<ControlReceipt, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        // Reject invalid transitions before durable append; a rejected command
        // must not poison the next reopen with an invalid journal event.
        let mut next = self.records.clone();
        apply_event(&mut next, &event, /*replay*/ false)?;
        let encoded = format!("{}\n", encode_event(&event));
        self.append(&encoded)?;
        let request_id = event.request_id().to_string();
        self.records = next;
        let record = self
            .records
            .get(&request_id)
            .ok_or(Error::RequestNotFound)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    fn append(&mut self, encoded: &str) -> Result<(), Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let next_bytes = self
            .journal_bytes
            .checked_add(encoded.len() as u64)
            .ok_or(Error::ArithmeticOverflow)?;
        if encoded.len() > MAX_JOURNAL_LINE_BYTES || next_bytes > MAX_JOURNAL_BYTES {
            return Err(Error::CapacityExceeded);
        }
        let persisted = self
            .file
            .write_all(encoded.as_bytes())
            .and_then(|()| self.file.flush())
            .and_then(|()| self.file.sync_all());
        if let Err(error) = persisted {
            // A partial write or failed sync has an unknown durable outcome.
            // Keep this owner fenced until explicit inspection and reopen.
            self.poisoned = true;
            return Err(error.into());
        }
        self.journal_bytes = next_bytes;
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum Event {
    Submit(InferenceRequest),
    Reserve {
        request_id: String,
        expected_revision: u64,
        reservation: Reservation,
    },
    Assign {
        request_id: String,
        expected_revision: u64,
        assignment: Assignment,
    },
    Cancel {
        request_id: String,
        expected_revision: u64,
    },
    Settle {
        request_id: String,
        expected_revision: u64,
        observation_digest: String,
        observation: TerminalObservation,
    },
}

impl Event {
    fn request_id(&self) -> &str {
        match self {
            Self::Submit(request) => &request.request_id,
            Self::Reserve { request_id, .. }
            | Self::Assign { request_id, .. }
            | Self::Cancel { request_id, .. }
            | Self::Settle { request_id, .. } => request_id,
        }
    }
}

fn apply_event(
    records: &mut BTreeMap<String, RequestRecord>,
    event: &Event,
    replay: bool,
) -> Result<(), Error> {
    match event {
        Event::Submit(request) => {
            if let Some(current) = records.get(&request.request_id) {
                if replay && current.request == *request {
                    return Ok(());
                }
                return Err(Error::Conflict);
            }
            records.insert(
                request.request_id.clone(),
                RequestRecord {
                    request: request.clone(),
                    revision: 1,
                    state: RequestState::Pending,
                    reservation: None,
                    assignment: None,
                    terminal_observation_digest: None,
                    consumed_tokens: 0,
                    usage_units: 0,
                },
            );
        }
        Event::Reserve {
            request_id,
            expected_revision,
            reservation,
        } => {
            let record = records.get_mut(request_id).ok_or(Error::RequestNotFound)?;
            require_revision(record, *expected_revision, replay)?;
            if record.state != RequestState::Pending {
                return Err(Error::InvalidTransition);
            }
            record.reservation = Some(reservation.clone());
            record.state = RequestState::Reserved;
            record.revision = next_revision(record.revision)?;
        }
        Event::Assign {
            request_id,
            expected_revision,
            assignment,
        } => {
            let record = records.get_mut(request_id).ok_or(Error::RequestNotFound)?;
            require_revision(record, *expected_revision, replay)?;
            if record.state != RequestState::Reserved {
                return Err(Error::InvalidTransition);
            }
            record.assignment = Some(assignment.clone());
            record.state = RequestState::Assigned;
            record.revision = next_revision(record.revision)?;
        }
        Event::Cancel {
            request_id,
            expected_revision,
        } => {
            let record = records.get_mut(request_id).ok_or(Error::RequestNotFound)?;
            require_revision(record, *expected_revision, replay)?;
            record.state = match record.state {
                RequestState::Pending | RequestState::Reserved => RequestState::Cancelled,
                RequestState::Assigned => RequestState::Cancelling,
                _ => return Err(Error::InvalidTransition),
            };
            record.revision = next_revision(record.revision)?;
        }
        Event::Settle {
            request_id,
            expected_revision,
            observation_digest,
            observation,
        } => {
            let record = records.get_mut(request_id).ok_or(Error::RequestNotFound)?;
            require_revision(record, *expected_revision, replay)?;
            if !matches!(
                record.state,
                RequestState::Assigned | RequestState::Cancelling
            ) {
                return Err(Error::InvalidTransition);
            }
            record.state = if observation.terminal_observed {
                observation
                    .terminal_status
                    .ok_or(Error::TerminalObservationMissing)?
            } else {
                RequestState::Indeterminate
            };
            record.terminal_observation_digest = Some(observation_digest.clone());
            record.consumed_tokens = observation.consumed_tokens;
            record.usage_units = observation.usage_units;
            record.revision = next_revision(record.revision)?;
        }
    }
    Ok(())
}

fn require_revision(record: &RequestRecord, expected: u64, replay: bool) -> Result<(), Error> {
    if record.revision != expected {
        if replay {
            return Err(Error::CorruptJournal("event revision"));
        }
        return Err(Error::StaleRevision);
    }
    Ok(())
}

fn next_revision(value: u64) -> Result<u64, Error> {
    value.checked_add(1).ok_or(Error::ArithmeticOverflow)
}

fn validate_request(now_ms: u64, request: &InferenceRequest) -> Result<(), Error> {
    validate_identity(&request.request_id, "request")?;
    validate_identity(&request.principal_id, "principal")?;
    validate_digest(&request.model_digest, "model")?;
    validate_digest(&request.payload_digest, "payload")?;
    validate_digest(&request.semantic_digest, "semantic")?;
    if request.maximum_tokens == 0 || request.maximum_tokens > MAX_TOKENS {
        return Err(Error::InvalidTokens);
    }
    if request.deadline_ms <= now_ms {
        return Err(Error::InvalidTime);
    }
    Ok(())
}

fn validate_reservation(now_ms: u64, value: &Reservation) -> Result<(), Error> {
    validate_identity(&value.reservation_id, "reservation")?;
    if value.quota_units == 0
        || value.maximum_tokens == 0
        || value.maximum_tokens > MAX_TOKENS
        || value.authority_epoch == 0
        || value.valid_until_ms <= now_ms
    {
        return Err(Error::InvalidTime);
    }
    Ok(())
}

fn validate_assignment(value: &Assignment) -> Result<(), Error> {
    validate_identity(&value.worker_id, "worker")?;
    validate_digest(&value.assignment_digest, "assignment")?;
    if value.worker_generation == 0 {
        return Err(Error::InvalidTransition);
    }
    Ok(())
}

fn validate_observation(value: &TerminalObservation) -> Result<(), Error> {
    validate_identity(&value.request_id, "request")?;
    validate_identity(&value.reservation_id, "reservation")?;
    validate_identity(&value.worker_id, "worker")?;
    validate_digest(&value.model_digest, "model")?;
    validate_digest(&value.payload_digest, "payload")?;
    if value.worker_generation == 0 || value.consumed_tokens > MAX_TOKENS {
        return Err(Error::InvalidTransition);
    }
    if let Some(output) = &value.output_digest {
        validate_digest(output, "output")?;
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), Error> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::InvalidDigest(field));
    }
    Ok(())
}

fn receipt(record: &RequestRecord, idempotent: bool) -> ControlReceipt {
    ControlReceipt {
        request_id: record.request.request_id.clone(),
        revision: record.revision,
        state: record.state,
        idempotent,
        terminal_observed: record.state.terminal() && record.state != RequestState::Indeterminate,
    }
}

fn encode_event(event: &Event) -> String {
    match event {
        Event::Submit(request) => format!(
            "submit|{}|{}|{}|{}|{}|{}|{}",
            request.request_id,
            request.principal_id,
            request.model_digest,
            request.payload_digest,
            request.maximum_tokens,
            request.deadline_ms,
            request.semantic_digest
        ),
        Event::Reserve {
            request_id,
            expected_revision,
            reservation,
        } => format!(
            "reserve|{request_id}|{expected_revision}|{}|{}|{}|{}|{}",
            reservation.reservation_id,
            reservation.quota_units,
            reservation.maximum_tokens,
            reservation.authority_epoch,
            reservation.valid_until_ms
        ),
        Event::Assign {
            request_id,
            expected_revision,
            assignment,
        } => format!(
            "assign|{request_id}|{expected_revision}|{}|{}|{}",
            assignment.worker_id, assignment.worker_generation, assignment.assignment_digest
        ),
        Event::Cancel {
            request_id,
            expected_revision,
        } => format!("cancel|{request_id}|{expected_revision}"),
        Event::Settle {
            request_id,
            expected_revision,
            observation_digest,
            observation,
        } => format!(
            "settle|{request_id}|{expected_revision}|{observation_digest}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
            observation.reservation_id,
            observation.worker_id,
            observation.worker_generation,
            observation.model_digest,
            observation.payload_digest,
            u8::from(observation.terminal_observed),
            observation
                .terminal_status
                .map_or("none", RequestState::as_str),
            observation.output_digest.as_deref().unwrap_or("none"),
            observation.consumed_tokens,
            observation.usage_units,
            observation.request_id
        ),
    }
}

fn decode_event(line: &str) -> Result<Event, Error> {
    let fields: Vec<_> = line.split('|').collect();
    match fields.as_slice() {
        [
            "submit",
            request_id,
            principal_id,
            model,
            payload,
            tokens,
            deadline,
            semantic,
        ] => Ok(Event::Submit(InferenceRequest {
            request_id: (*request_id).to_string(),
            principal_id: (*principal_id).to_string(),
            model_digest: (*model).to_string(),
            payload_digest: (*payload).to_string(),
            maximum_tokens: parse_u32(tokens)?,
            deadline_ms: parse_u64(deadline)?,
            semantic_digest: (*semantic).to_string(),
        })),
        [
            "reserve",
            request_id,
            revision,
            reservation_id,
            quota,
            tokens,
            epoch,
            valid_until,
        ] => Ok(Event::Reserve {
            request_id: (*request_id).to_string(),
            expected_revision: parse_u64(revision)?,
            reservation: Reservation {
                reservation_id: (*reservation_id).to_string(),
                quota_units: parse_u64(quota)?,
                maximum_tokens: parse_u32(tokens)?,
                authority_epoch: parse_u64(epoch)?,
                valid_until_ms: parse_u64(valid_until)?,
            },
        }),
        [
            "assign",
            request_id,
            revision,
            worker_id,
            generation,
            assignment_digest,
        ] => Ok(Event::Assign {
            request_id: (*request_id).to_string(),
            expected_revision: parse_u64(revision)?,
            assignment: Assignment {
                worker_id: (*worker_id).to_string(),
                worker_generation: parse_u64(generation)?,
                assignment_digest: (*assignment_digest).to_string(),
            },
        }),
        ["cancel", request_id, revision] => Ok(Event::Cancel {
            request_id: (*request_id).to_string(),
            expected_revision: parse_u64(revision)?,
        }),
        [
            "settle",
            request_id,
            revision,
            observation_digest,
            reservation_id,
            worker_id,
            worker_generation,
            model,
            payload,
            terminal,
            status,
            output,
            tokens,
            usage,
            observed_request_id,
        ] => Ok(Event::Settle {
            request_id: (*request_id).to_string(),
            expected_revision: parse_u64(revision)?,
            observation_digest: (*observation_digest).to_string(),
            observation: TerminalObservation {
                request_id: (*observed_request_id).to_string(),
                reservation_id: (*reservation_id).to_string(),
                worker_id: (*worker_id).to_string(),
                worker_generation: parse_u64(worker_generation)?,
                model_digest: (*model).to_string(),
                payload_digest: (*payload).to_string(),
                terminal_observed: match *terminal {
                    "1" => true,
                    "0" => false,
                    _ => return Err(Error::CorruptJournal("terminal boolean")),
                },
                terminal_status: if *status == "none" {
                    None
                } else {
                    Some(RequestState::parse(status)?)
                },
                output_digest: (*output != "none").then(|| (*output).to_string()),
                consumed_tokens: parse_u32(tokens)?,
                usage_units: parse_u64(usage)?,
            },
        }),
        _ => Err(Error::CorruptJournal("event shape")),
    }
}

fn parse_u64(value: &str) -> Result<u64, Error> {
    value.parse().map_err(|_| Error::CorruptJournal("u64"))
}

fn parse_u32(value: &str) -> Result<u32, Error> {
    value.parse().map_err(|_| Error::CorruptJournal("u32"))
}

#[cfg(test)]
#[path = "durable_control_tests.rs"]
mod tests;
