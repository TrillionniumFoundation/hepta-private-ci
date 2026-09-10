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
    pub redaction_digest: Option<String>,
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
    last_observation: Option<ServerObservation>,
    terminal_observation: Option<ServerObservation>,
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
            redaction_digest: None,
            terminal_observed: false,
            idempotent: false,
        };
        self.sends.insert(
            intent.operation_id.clone(),
            SendRecord {
                intent,
                receipt: receipt.clone(),
                last_observation: None,
                terminal_observation: None,
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
        verify_observation_binding(&current.intent, &observation)?;

        if let Some(terminal) = &current.terminal_observation {
            if terminal == &observation {
                let mut receipt = current.receipt.clone();
                receipt.idempotent = true;
                return Ok(receipt);
            }
            return Err(Error::AlreadyTerminal);
        }
        if current.receipt.state == SendState::Redacted {
            return Err(Error::AlreadyTerminal);
        }
        if current.last_observation.as_ref() == Some(&observation) {
            let mut receipt = current.receipt.clone();
            receipt.idempotent = true;
            return Ok(receipt);
        }

        if !observation.terminal_observed {
            current.receipt.state = SendState::Indeterminate;
            current.receipt.observation_digest = Some(observation.observation_digest.clone());
            current.last_observation = Some(observation);
            return Ok(current.receipt.clone());
        }

        if observation.accepted {
            let event_id = observation
                .server_event_id
                .as_ref()
                .ok_or(Error::TerminalEventMissing)?;
            if let Some(prior_operation) = self.events.get(event_id) {
                if prior_operation != &observation.operation_id {
                    return Err(Error::OperationConflict);
                }
            }
            self.events
                .insert(event_id.clone(), observation.operation_id.clone());
            current.receipt.state = SendState::Succeeded;
            current.receipt.server_event_id = Some(event_id.clone());
        } else {
            current.receipt.state = SendState::Failed;
        }
        current.receipt.observation_digest = Some(observation.observation_digest.clone());
        current.receipt.terminal_observed = true;
        current.last_observation = Some(observation.clone());
        current.terminal_observation = Some(observation);
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
            if current.receipt.redaction_digest.as_deref() == Some(redaction_digest) {
                let mut receipt = current.receipt.clone();
                receipt.idempotent = true;
                return Ok(receipt);
            }
            return Err(Error::AlreadyTerminal);
        }
        if current.receipt.state != SendState::Succeeded
            || !current.receipt.terminal_observed
            || current.receipt.server_event_id.as_deref() != Some(server_event_id)
        {
            return Err(Error::AlreadyTerminal);
        }
        current.receipt.state = SendState::Redacted;
        current.receipt.redaction_digest = Some(redaction_digest.to_string());
        current.receipt.idempotent = false;
        Ok(current.receipt.clone())
    }

    pub fn receipt(&self, operation_id: &str) -> Option<&SendReceipt> {
        self.sends.get(operation_id).map(|record| &record.receipt)
    }
}

fn verify_observation_binding(
    intent: &SendIntent,
    observation: &ServerObservation,
) -> Result<(), Error> {
    if observation.transaction_id != intent.transaction_id
        || observation.homeserver_id != intent.homeserver_id
        || observation.room_id != intent.room_id
        || observation.session_generation != intent.session_generation
    {
        return Err(Error::ObservationMismatch);
    }
    Ok(())
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
    match (
        value.terminal_observed,
        value.accepted,
        value.server_event_id.as_ref(),
    ) {
        (false, false, None) | (true, false, None) => {}
        (true, true, Some(event)) => validate_identity(event, "server event")?,
        _ => return Err(Error::ObservationMismatch),
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

fn main() {
    let mut arguments = std::env::args().skip(1);
    match (arguments.next().as_deref(), arguments.next()) {
        (Some("--describe"), None) => println!(
            "{{\"kind\":\"hepta.matrix.send-observer-kernel.v1\",\"homeserverTransportEnrolled\":false,\"externalTerminalityProved\":false}}"
        ),
        (Some("--self-test"), None) => {
            let observer = MatrixSendObserver::default();
            assert!(observer.sends.is_empty());
            println!(
                "{{\"status\":\"PASS_HEPTA_MATRIX_OBSERVER_KERNEL_SELF_TEST\",\"homeserverTransportEnrolled\":false}}"
            );
        }
        _ => {
            eprintln!("usage: hepta-matrix-send-observer --describe|--self-test");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn intent() -> SendIntent {
        SendIntent {
            operation_id: "operation.1".to_string(),
            transaction_id: "transaction.1".to_string(),
            homeserver_id: "homeserver.1".to_string(),
            room_id: "!room:example.org".to_string(),
            device_id: "device.1".to_string(),
            session_generation: 3,
            authority_epoch: 7,
            payload_digest: "1".repeat(64),
            grant_payload_digest: "1".repeat(64),
            deadline_ms: 10_000,
        }
    }

    fn observation(
        terminal_observed: bool,
        accepted: bool,
        event: Option<&str>,
        digest_byte: char,
    ) -> ServerObservation {
        ServerObservation {
            operation_id: "operation.1".to_string(),
            transaction_id: "transaction.1".to_string(),
            homeserver_id: "homeserver.1".to_string(),
            room_id: "!room:example.org".to_string(),
            session_generation: 3,
            terminal_observed,
            accepted,
            server_event_id: event.map(str::to_string),
            observation_digest: digest_byte.to_string().repeat(64),
        }
    }

    #[test]
    fn lost_ack_keeps_transaction_and_reconciles_to_server_event() {
        let mut observer = MatrixSendObserver::default();
        observer.prepare_send(100, intent()).expect("prepare");
        let pending = observer
            .observe_send(observation(false, false, None, '2'))
            .expect("unknown");
        assert_eq!(pending.state, SendState::Indeterminate);
        let terminal_observation = observation(true, true, Some("$event:example.org"), '3');
        let terminal = observer
            .observe_send(terminal_observation.clone())
            .expect("terminal");
        assert_eq!(terminal.state, SendState::Succeeded);
        assert_eq!(terminal.transaction_id, "transaction.1");
        let retry = observer
            .observe_send(terminal_observation)
            .expect("idempotent terminal observation");
        assert!(retry.idempotent);
    }

    #[test]
    fn failed_terminal_observation_cannot_be_rewritten() {
        let mut observer = MatrixSendObserver::default();
        observer.prepare_send(100, intent()).expect("prepare");
        observer
            .observe_send(observation(true, false, None, '4'))
            .expect("failed terminal");
        assert_eq!(
            observer.observe_send(observation(true, true, Some("$event:example.org"), '5')),
            Err(Error::AlreadyTerminal)
        );
        assert_eq!(
            observer.receipt("operation.1").map(|receipt| receipt.state),
            Some(SendState::Failed)
        );
    }

    #[test]
    fn redaction_is_terminal_and_preserves_send_observation() {
        let mut observer = MatrixSendObserver::default();
        observer.prepare_send(100, intent()).expect("prepare");
        observer
            .observe_send(observation(true, true, Some("$event:example.org"), '3'))
            .expect("terminal");
        let redacted = observer
            .apply_redaction("$event:example.org", &"6".repeat(64))
            .expect("redact");
        assert_eq!(redacted.state, SendState::Redacted);
        assert_eq!(redacted.observation_digest, Some("3".repeat(64)));
        assert_eq!(redacted.redaction_digest, Some("6".repeat(64)));
        assert!(
            observer
                .apply_redaction("$event:example.org", &"6".repeat(64))
                .expect("same redaction")
                .idempotent
        );
        assert_eq!(
            observer.apply_redaction("$event:example.org", &"7".repeat(64)),
            Err(Error::AlreadyTerminal)
        );
        assert_eq!(
            observer.observe_send(observation(true, true, Some("$event:example.org"), '3')),
            Err(Error::AlreadyTerminal)
        );
    }

    #[test]
    fn payload_drift_and_transaction_reuse_are_rejected() {
        let mut observer = MatrixSendObserver::default();
        let mut changed = intent();
        changed.grant_payload_digest = "2".repeat(64);
        assert_eq!(
            observer.prepare_send(100, changed),
            Err(Error::PayloadMismatch)
        );
        observer.prepare_send(100, intent()).expect("prepare");
        let mut duplicate = intent();
        duplicate.operation_id = "operation.2".to_string();
        assert_eq!(
            observer.prepare_send(100, duplicate),
            Err(Error::OperationConflict)
        );
    }

    #[test]
    fn malformed_observation_state_is_rejected() {
        let mut observer = MatrixSendObserver::default();
        observer.prepare_send(100, intent()).expect("prepare");
        assert_eq!(
            observer.observe_send(observation(false, true, Some("$event:example.org"), '8')),
            Err(Error::ObservationMismatch)
        );
    }
}
