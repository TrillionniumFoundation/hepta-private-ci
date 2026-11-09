//! Fixed-scope checkpoint data over the original authenticated Root channel.
//! No receipt signature, learning role, owner registration or retry is supplied.

use std::sync::Mutex;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use serde::Deserialize;
use serde::Serialize;

use super::*;

#[cfg(test)]
#[path = "learning_checkpoint_data_tests.rs"]
pub(crate) mod test_data;

#[cfg(test)]
#[path = "learning_iteration_checkpoint_transport_tests.rs"]
mod tests;

pub(crate) const DOMAIN: &str = "runtime.agentd.learning_checkpoint.v1";
pub(crate) const FRAME_LIMIT: usize = 16 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u8,
    operation: String,
    sequence: u64,
    command: Command,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Restore,
    Checkpoint {
        expected_head: String,
        snapshot: String,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Response {
    schema_version: u8,
    operation: String,
    sequence: u64,
    owner_id: String,
    binding: String,
    outcome: Outcome,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
enum Outcome {
    Vacant,
    Current { snapshot: String },
    Committed { head: String },
    Conflict,
    Refused,
}

pub(crate) fn encode_snapshot(snapshot: &LearningIterationSnapshotV1) -> Result<String, Error> {
    Ok(STANDARD_NO_PAD.encode(codec::encode(snapshot)?))
}

pub(crate) fn decode_snapshot(encoded: &str) -> Result<LearningIterationSnapshotV1, Error> {
    if encoded.len() > codec::MAX_BYTES.div_ceil(3) * 4 {
        return Err(Error::Capacity);
    }
    let mut bytes = [0_u8; codec::MAX_BYTES];
    let length = STANDARD_NO_PAD
        .decode_slice(encoded, &mut bytes)
        .map_err(|_| Error::InvalidRecord)?;
    let bytes = &bytes[..length];
    if STANDARD_NO_PAD.encode(bytes) != encoded {
        return Err(Error::InvalidRecord);
    }
    codec::decode(bytes)
}

fn encode_frame(value: &impl Serialize) -> Result<Vec<u8>, HostIssuerTransportError> {
    let bytes = serde_json::to_vec(value).map_err(|_| HostIssuerTransportError::Unavailable)?;
    if bytes.is_empty() || bytes.len() > FRAME_LIMIT {
        return Err(HostIssuerTransportError::InvalidRequest);
    }
    Ok(bytes)
}

/// Root retains the original concrete capability. This adapter cannot be built
/// from a caller-defined store and has no registration, reset or signing API.
pub(crate) struct LearningCheckpointBackend {
    owner: LearningIterationCheckpointOwnerV1,
    pub(crate) owner_id: String,
    pub(crate) initial: LearningIterationSnapshotV1,
    next_sequence: u64,
}

impl LearningCheckpointBackend {
    pub(crate) fn new(owner: LearningIterationCheckpointOwnerV1) -> Self {
        Self {
            owner_id: owner.owner_id.clone(),
            initial: owner.initial.clone(),
            owner,
            next_sequence: 1,
        }
    }

    pub(crate) fn exchange(&mut self, bytes: &[u8]) -> Result<Vec<u8>, HostIssuerTransportError> {
        if bytes.is_empty() || bytes.len() > FRAME_LIMIT {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        let request: Request =
            serde_json::from_slice(bytes).map_err(|_| HostIssuerTransportError::InvalidRequest)?;
        if request.schema_version != 1
            || request.operation != DOMAIN
            || request.sequence != self.next_sequence
        {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        self.next_sequence = self
            .next_sequence
            .checked_add(1)
            .ok_or(HostIssuerTransportError::Unavailable)?;
        let result = match request.command {
            Command::Restore => self
                .owner
                .restore(&self.initial.request)
                .and_then(|snapshot| {
                    snapshot.map_or(Ok(Outcome::Vacant), |snapshot| {
                        encode_snapshot(&snapshot).map(|snapshot| Outcome::Current { snapshot })
                    })
                }),
            Command::Checkpoint {
                expected_head,
                snapshot,
            } => expected_head
                .parse()
                .map_err(|_| Error::InvalidRecord)
                .and_then(|expected| {
                    let snapshot = decode_snapshot(&snapshot)?;
                    self.owner.checkpoint(expected, &snapshot)
                })
                .map(|head| Outcome::Committed {
                    head: head.to_string(),
                }),
        };
        let outcome = match result {
            Ok(outcome) => outcome,
            Err(Error::Conflict) => Outcome::Conflict,
            Err(
                Error::Capacity | Error::InvalidRecord | Error::WrongScope | Error::Snapshot(_),
            ) => Outcome::Refused,
            Err(Error::Store(_) | Error::CommitUncertain(_)) => {
                return Err(HostIssuerTransportError::Unavailable);
            }
        };
        encode_frame(&Response {
            schema_version: 1,
            operation: DOMAIN.into(),
            sequence: request.sequence,
            owner_id: self.owner_id.clone(),
            binding: self.initial.head_digest.to_string(),
            outcome,
        })
    }
}

enum CallKind {
    Restore,
    Checkpoint,
}

impl CallKind {
    fn unavailable(&self) -> Error {
        match self {
            Self::Restore => Error::Store(AuthorityTrustError::Unavailable),
            Self::Checkpoint => Error::CommitUncertain(AuthorityTrustError::Unavailable),
        }
    }
}

/// A concrete, original-Root-pinned checkpoint client. Construction is only
/// through the explicit sealed handoff. Calls do synchronous bounded I/O and
/// belong on the learning owner's blocking worker, outside foreground turns.
/// Snapshots remain data requiring the existing independent receipt verifier.
pub struct AgentdLearningCheckpointClientV1 {
    channel: Mutex<Option<(HostAuthorityPeerChannel, u64)>>,
    owner_id: String,
    initial: LearningIterationSnapshotV1,
}

impl AgentdLearningCheckpointClientV1 {
    pub(crate) fn from_admitted_channel(
        channel: HostAuthorityPeerChannel,
        owner_id: String,
        initial: LearningIterationSnapshotV1,
    ) -> Self {
        Self {
            channel: Mutex::new(Some((channel, 1))),
            owner_id,
            initial,
        }
    }

    /// Read the durable original owner every time. No local success cache is
    /// available after a lost response or an expired/revoked Root lease.
    pub fn restore(
        &self,
        request: &LearningIterationRequestV1,
    ) -> Result<Option<LearningIterationSnapshotV1>, Error> {
        if request != &self.initial.request {
            return Err(Error::WrongScope);
        }
        self.exchange(
            Command::Restore,
            CallKind::Restore,
            |outcome| match outcome {
                Outcome::Vacant => Ok(None),
                Outcome::Current { snapshot } => {
                    let snapshot = decode_snapshot(&snapshot)?;
                    if snapshot.request != self.initial.request
                        || snapshot.owners != self.initial.owners
                    {
                        return Err(Error::WrongScope);
                    }
                    Ok(Some(snapshot))
                }
                Outcome::Committed { .. } | Outcome::Conflict | Outcome::Refused => {
                    Err(Error::InvalidRecord)
                }
            },
        )
    }

    /// Commit only the same request and owners. Any exchange/ACK uncertainty
    /// closes this client and reports CommitUncertain; there is no reconnect or
    /// retry. Before-send lock contention instead reports Store(Unavailable)
    /// without sending or disturbing the in-flight call. A newly authenticated
    /// owner must reconcile any operation whose acknowledgment was uncertain.
    pub fn checkpoint(
        &self,
        expected_head: Digest32,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<Digest32, Error> {
        if snapshot.request != self.initial.request || snapshot.owners != self.initial.owners {
            return Err(Error::WrongScope);
        }
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone()).map_err(Error::Snapshot)?;
        self.exchange(
            Command::Checkpoint {
                expected_head: expected_head.to_string(),
                snapshot: encode_snapshot(snapshot)?,
            },
            CallKind::Checkpoint,
            |outcome| match outcome {
                Outcome::Committed { head } if head == snapshot.head_digest.to_string() => {
                    Ok(snapshot.head_digest)
                }
                Outcome::Vacant
                | Outcome::Current { .. }
                | Outcome::Committed { .. }
                | Outcome::Conflict
                | Outcome::Refused => Err(Error::InvalidRecord),
            },
        )
    }

    fn exchange<T>(
        &self,
        command: Command,
        kind: CallKind,
        interpret: impl FnOnce(Outcome) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let mut slot = self
            .channel
            .try_lock()
            .map_err(|_| Error::Store(AuthorityTrustError::Unavailable))?;
        let (mut channel, sequence) = slot.take().ok_or_else(|| kind.unavailable())?;
        let next = sequence.checked_add(1).ok_or_else(|| kind.unavailable())?;
        let request = encode_frame(&Request {
            schema_version: 1,
            operation: DOMAIN.into(),
            sequence,
            command,
        })
        .map_err(|_| kind.unavailable())?;
        let bytes = channel.request(&request).map_err(|_| kind.unavailable())?;
        let response: Response = serde_json::from_slice(&bytes).map_err(|_| kind.unavailable())?;
        if response.schema_version != 1
            || response.operation != DOMAIN
            || response.sequence != sequence
            || response.owner_id != self.owner_id
            || response.binding != self.initial.head_digest.to_string()
        {
            return Err(kind.unavailable());
        }
        let result = match response.outcome {
            Outcome::Conflict if matches!(kind, CallKind::Checkpoint) => Err(Error::Conflict),
            Outcome::Refused => Err(Error::InvalidRecord),
            outcome => Ok(interpret(outcome).map_err(|_| kind.unavailable())?),
        };
        *slot = Some((channel, next));
        result
    }
}
