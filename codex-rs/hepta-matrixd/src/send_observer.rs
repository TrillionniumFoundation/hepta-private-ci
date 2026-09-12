#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

const MAX_PENDING_SENDS: usize = 4_096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SendIntent {
    pub operation_id: String,
    pub transaction_id: String,
    pub homeserver_id: String,
    pub room_id: String,
    pub device_id: String,
    pub session_generation: u64,
    pub authority_epoch: u64,
    pub payload_digest: String,
    pub grant_payload_digest: String,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ServerObservation {
    pub operation_id: String,
    pub transaction_id: String,
    pub homeserver_id: String,
    pub room_id: String,
    pub session_generation: u64,
    pub terminal_observed: bool,
    pub accepted: bool,
    pub server_event_id: Option<String>,
    pub observation_digest: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SendState {
    Prepared,
    Indeterminate,
    Succeeded,
    Failed,
    Redacted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SendReceipt {
    pub operation_id: String,
    pub transaction_id: String,
    pub state: SendState,
    pub server_event_id: Option<String>,
    pub observation_digest: Option<String>,
    pub terminal_observed: bool,
    pub idempotent: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidGeneration,
    DeadlineExpired,
    CapacityExceeded,
    PayloadMismatch,
    OperationConflict,
    SendNotFound,
    ObservationMismatch,
    TerminalEventMissing,
    AlreadyTerminal,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[derive(Debug)]
struct SendRecord {
    intent: SendIntent,
    receipt: SendReceipt,
}

#[derive(Debug, Default)]
pub struct MatrixSendObserver {
    sends: BTreeMap<String, SendRecord>,
    events: BTreeMap<String, String>,
}

impl MatrixSendObserver {
    pub fn prepare_send(&mut self, now_ms: u64, intent: SendIntent) -> Result<SendReceipt, Error> {
        validate_intent(now_ms, &intent)?;
        if intent.payload_digest != intent.grant_payload_digest {
            return Err(Error::PayloadMismatch);
        }
        if let Some(current) = self.sends.get(&intent.operation_id) {
            if current.intent == intent {
                let mut receipt = current.receipt.clone();
                receipt.idempotent = true;
                return Ok(receipt);
            }
            return Err(Error::OperationConflict);
        }
        if self.sends.len() >= MAX_PENDING_SENDS {
            return Err(Error::CapacityExceeded);
        }
        if self
            .sends
            .values()
            .any(|current| current.intent.transaction_id == intent.transaction_id)
        {
            return Err(Error::OperationConflict);
        }
        let receipt = SendReceipt {
            operation_id: intent.operation_id.clone(),
            transaction_id: intent.transaction_id.clone(),
            state: SendState::Prepared,
            server_event_id: None,
            observation_digest: None,
            terminal_observed: false,
            idempotent: false,
        };
        self.sends.insert(
            intent.operation_id.clone(),
            SendRecord {
                intent,
                receipt: receipt.clone(),
            },
        );
        Ok(receipt)
    }

    pub fn observe_send(&mut self, observation: ServerObservation) -> Result<SendReceipt, Error> {
        validate_observation(&observation)?;
        let current = self
            .sends
            .get_mut(&observation.operation_id)
            .ok_or(Error::SendNotFound)?;
        if observation.transaction_id != current.intent.transaction_id
            || observation.homeserver_id != current.intent.homeserver_id
            || observation.room_id != current.intent.room_id
            || observation.session_generation != current.intent.session_generation
        {
            return Err(Error::ObservationMismatch);
        }
        // Terminal outcomes cannot be reopened by delayed or contradictory observations.
        // A digest alone is not sufficient to establish an identical replay.
        match current.receipt.state {
            SendState::Succeeded | SendState::Failed => {
                if observation.terminal_observed
                    && observation.accepted == (current.receipt.state == SendState::Succeeded)
                    && observation.server_event_id == current.receipt.server_event_id
                    && current.receipt.observation_digest.as_deref()
                        == Some(observation.observation_digest.as_str())
                {
                    let mut receipt = current.receipt.clone();
                    receipt.idempotent = true;
                    return Ok(receipt);
                }
                return Err(Error::AlreadyTerminal);
            }
            SendState::Redacted => return Err(Error::AlreadyTerminal),
            SendState::Prepared | SendState::Indeterminate => {}
        }
        if !observation.terminal_observed {
            current.receipt.state = SendState::Indeterminate;
            current.receipt.observation_digest = Some(observation.observation_digest);
            return Ok(current.receipt.clone());
        }
        if observation.accepted {
            let event_id = observation
                .server_event_id
                .as_ref()
                .ok_or(Error::TerminalEventMissing)?;
            validate_identity(event_id, "server event")?;
            if let Some(prior_operation) = self.events.get(event_id)
                && prior_operation != &observation.operation_id
            {
                return Err(Error::OperationConflict);
            }
            self.events
                .insert(event_id.clone(), observation.operation_id.clone());
            current.receipt.state = SendState::Succeeded;
            current.receipt.server_event_id = Some(event_id.clone());
        } else {
            if observation.server_event_id.is_some() {
                return Err(Error::ObservationMismatch);
            }
            current.receipt.state = SendState::Failed;
        }
        current.receipt.observation_digest = Some(observation.observation_digest);
        current.receipt.terminal_observed = true;
        Ok(current.receipt.clone())
    }

    pub fn apply_redaction(
        &mut self,
        server_event_id: &str,
        redaction_digest: &str,
    ) -> Result<SendReceipt, Error> {
        validate_identity(server_event_id, "server event")?;
        validate_digest(redaction_digest, "redaction")?;
        let operation_id = self
            .events
            .get(server_event_id)
            .cloned()
            .ok_or(Error::SendNotFound)?;
        let current = self
            .sends
            .get_mut(&operation_id)
            .ok_or(Error::SendNotFound)?;
        if current.receipt.state == SendState::Redacted {
            if current.receipt.observation_digest.as_deref() == Some(redaction_digest) {
                let mut receipt = current.receipt.clone();
                receipt.idempotent = true;
                return Ok(receipt);
            }
            return Err(Error::AlreadyTerminal);
        }
        current.receipt.state = SendState::Redacted;
        current.receipt.observation_digest = Some(redaction_digest.to_string());
        current.receipt.terminal_observed = true;
        Ok(current.receipt.clone())
    }

    pub fn receipt(&self, operation_id: &str) -> Option<&SendReceipt> {
        self.sends.get(operation_id).map(|record| &record.receipt)
    }
}

fn validate_intent(now_ms: u64, value: &SendIntent) -> Result<(), Error> {
    for (field, name) in [
        (&value.operation_id, "operation"),
        (&value.transaction_id, "transaction"),
        (&value.homeserver_id, "homeserver"),
        (&value.room_id, "room"),
        (&value.device_id, "device"),
    ] {
        validate_identity(field, name)?;
    }
    validate_digest(&value.payload_digest, "payload")?;
    validate_digest(&value.grant_payload_digest, "grant payload")?;
    if value.session_generation == 0 || value.authority_epoch == 0 {
        return Err(Error::InvalidGeneration);
    }
    if value.deadline_ms <= now_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

fn validate_observation(value: &ServerObservation) -> Result<(), Error> {
    for (field, name) in [
        (&value.operation_id, "operation"),
        (&value.transaction_id, "transaction"),
        (&value.homeserver_id, "homeserver"),
        (&value.room_id, "room"),
    ] {
        validate_identity(field, name)?;
    }
    validate_digest(&value.observation_digest, "observation")?;
    if value.session_generation == 0 {
        return Err(Error::InvalidGeneration);
    }
    if let Some(event) = &value.server_event_id {
        validate_identity(event, "server event")?;
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 255
        || value.chars().any(char::is_whitespace)
        || value.chars().any(char::is_control)
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

#[cfg(test)]
#[path = "send_observer_tests.rs"]
mod tests;
