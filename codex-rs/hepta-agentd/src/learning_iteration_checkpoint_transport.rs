//! A separate purpose-bound lane for an already registered learning checkpoint.
//! No request selects an owner, registers genesis, signs evidence or adopts a model.

use super::*;
use crate::AgentdRootAuthorityPeer;
use crate::root_observation_stream::RootObservationStream;
use codex_hepta_contracts::HostIssuerTransportError;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;

use crate::same_actor_q24_phase_gate::RequiredSameActorPhaseChannel;

#[path = "learning_iteration_checkpoint_same_actor.rs"]
mod same_actor;

const OPERATION: &str = "runtime.learning.checkpoint.v1";
const SCOPED_OPERATION: &str = "runtime.learning.checkpoint.v2";
const FRAME_BOUND: usize = 16 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: u8,
    operation: String,
    request_id: u64,
    binding: String,
    command: Command,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
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
    schema: u8,
    request_id: u64,
    binding: String,
    result: Reply,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
enum Reply {
    Restored { snapshot: Option<String> },
    Committed { head: String },
    Conflict,
}

struct Channel {
    transport: RootObservationStream,
    next_request_id: u64,
}

/// Retains the original Root connection and process lifetime. The trusted
/// launcher supplies a dedicated learning socket, never an observation or
/// Cognitive checkpoint lane. Cancellation or an uncertain reply permanently
/// consumes this connection. Only the original launcher may deliver a fresh
/// connection to reconcile the same registered operation.
pub struct AgentdLearningCheckpointClientV1 {
    channel: Mutex<Option<Channel>>,
    pub(super) initial: LearningIterationSnapshotV1,
    pub(super) scope: Option<FrozenLearningScopeV2>,
    phase: Option<RequiredSameActorPhaseChannel>,
}

impl AgentdLearningCheckpointClientV1 {
    /// The exact empty initial snapshot is a public scope pin, not authority.
    /// Timing retains the existing 500 ms exchange / 300 s lifetime bounds.
    pub fn from_root_stream(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        initial: LearningIterationSnapshotV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::from_stream_profile(
            stream, peer, root_pidfd, initial, timeout, lifetime, /*scope*/ None,
        )
    }

    /// The sealed original Root handoff selects this profile. Scope is checked
    /// against every transport frame and restored candidate, never inferred from
    /// an unprotected receipt or silently dropped on an incompatible Root.
    pub fn from_root_stream_scoped_v2(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        initial: LearningIterationSnapshotV1,
        timeout: Duration,
        lifetime: Duration,
        scope: FrozenLearningScopeV2,
    ) -> Result<Self, Error> {
        scope.validate_snapshot(&initial).map_err(Error::Snapshot)?;
        Self::from_stream_profile(
            stream,
            peer,
            root_pidfd,
            initial,
            timeout,
            lifetime,
            Some(scope),
        )
    }

    fn from_stream_profile(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        initial: LearningIterationSnapshotV1,
        timeout: Duration,
        lifetime: Duration,
        scope: Option<FrozenLearningScopeV2>,
    ) -> Result<Self, Error> {
        let expected =
            LearningIterationCoordinatorV1::new(initial.request.clone(), initial.owners.clone())
                .map_err(Error::Snapshot)?;
        if expected.snapshot() != &initial {
            return Err(Error::WrongScope);
        }
        let transport =
            RootObservationStream::from_stream(stream, peer, root_pidfd, timeout, lifetime)
                .map_err(|_| Error::Store(AuthorityTrustError::Unavailable))?;
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                transport,
                next_request_id: 1,
            })),
            initial,
            scope,
            phase: None,
        })
    }

    pub fn frozen_scope_binding(&self) -> Option<Digest32> {
        self.scope.as_ref().map(FrozenLearningScopeV2::binding)
    }

    fn profile_identity(&self) -> (u8, String) {
        match self.frozen_scope_binding() {
            Some(binding) => (2, binding.to_string()),
            None => (1, self.initial.head_digest.to_string()),
        }
    }

    pub async fn restore(
        &self,
        request: &LearningIterationRequestV1,
    ) -> Result<Option<LearningIterationSnapshotV1>, Error> {
        let mut phase_closing = self.original_phase_failure_scope();
        self.require_original_phase(/*mutation*/ false)?;
        if request != &self.initial.request {
            return Err(Error::WrongScope);
        }
        let result = self
            .exchange(Command::Restore, |reply| match reply {
                Reply::Restored { snapshot } => snapshot
                    .map(|encoded| {
                        let snapshot = decode_snapshot(&encoded)?;
                        if let Some(scope) = &self.scope {
                            scope
                                .validate_snapshot(&snapshot)
                                .map_err(Error::Snapshot)?;
                        } else if snapshot.requires_scoped_owner_v2() {
                            return Err(Error::WrongScope);
                        }
                        if snapshot.request != self.initial.request
                            || snapshot.owners != self.initial.owners
                        {
                            return Err(Error::WrongScope);
                        }
                        Ok(snapshot)
                    })
                    .transpose(),
                Reply::Committed { .. } | Reply::Conflict => Err(Error::InvalidRecord),
            })
            .await;
        if result.is_ok() {
            self.require_original_phase(/*mutation*/ false)?;
            if let Some(closing) = &mut phase_closing {
                closing.disarm();
            }
        }
        result
    }

    pub async fn checkpoint(
        &self,
        expected_head: Digest32,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<Digest32, Error> {
        let mut phase_closing = self.original_phase_failure_scope();
        self.require_original_phase(/*mutation*/ true)?;
        if snapshot.request != self.initial.request || snapshot.owners != self.initial.owners {
            return Err(Error::WrongScope);
        }
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone()).map_err(Error::Snapshot)?;
        if let Some(scope) = &self.scope {
            scope.validate_snapshot(snapshot).map_err(Error::Snapshot)?;
        } else if snapshot.requires_scoped_owner_v2() {
            return Err(Error::WrongScope);
        }
        let predecessor = snapshot
            .receipts
            .last()
            .map_or(Digest32::ZERO, |receipt| receipt.predecessor);
        if predecessor != expected_head {
            return Err(Error::Conflict);
        }
        let command = Command::Checkpoint {
            expected_head: expected_head.to_string(),
            snapshot: STANDARD_NO_PAD.encode(codec::encode(snapshot)?),
        };
        let result = self
            .exchange(command, |reply| match reply {
                Reply::Committed { head } if head == snapshot.head_digest.to_string() => {
                    Ok(snapshot.head_digest)
                }
                Reply::Conflict => Err(Error::Conflict),
                Reply::Committed { .. } | Reply::Restored { .. } => Err(Error::InvalidRecord),
            })
            .await;
        if result.is_ok() {
            self.require_original_phase(/*mutation*/ true)?;
            if let Some(closing) = &mut phase_closing {
                closing.disarm();
            }
        }
        result
    }

    async fn exchange<T>(
        &self,
        command: Command,
        validate: impl FnOnce(Reply) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let mutation = matches!(&command, Command::Checkpoint { .. });
        let unavailable = || {
            if mutation {
                Error::CommitUncertain(AuthorityTrustError::Unavailable)
            } else {
                Error::Store(AuthorityTrustError::Unavailable)
            }
        };
        let mut phase_closing = self.original_phase_failure_scope();
        self.require_original_phase(mutation)?;
        // Framing alone cannot authenticate the response binding. Take the
        // whole transport and restore only after complete semantic validation.
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| unavailable())?
            .take()
            .ok_or_else(&unavailable)?;
        let request_id = channel.next_request_id;
        channel.next_request_id = request_id.checked_add(1).ok_or_else(&unavailable)?;
        let (schema, binding) = self.profile_identity();
        let operation = match self.frozen_scope_binding() {
            Some(_) => SCOPED_OPERATION,
            None => OPERATION,
        };
        let request = Request {
            schema,
            operation: operation.into(),
            request_id,
            binding,
            command,
        };
        let response: Response = channel
            .transport
            .read(&request)
            .await
            .map_err(|_| unavailable())?;
        if response.schema != request.schema
            || response.request_id != request_id
            || response.binding != request.binding
        {
            return Err(unavailable());
        }
        let result = validate(response.result);
        if result.is_ok() || matches!(result, Err(Error::Conflict)) {
            // Never make a phase lane available between a Conflict and the
            // failure guard closing the other original lanes.
            if self.phase.is_some() && result.is_err() {
                return result;
            }
            self.require_original_phase(mutation)?;
            *self.channel.try_lock().map_err(|_| unavailable())? = Some(channel);
            self.require_original_phase(mutation)?;
            // A Conflict keeps its original error value. Only the old None
            // profile may reuse that lane; this phase closes on every error.
            if result.is_ok()
                && let Some(closing) = &mut phase_closing {
                    closing.disarm();
                }
            result
        } else {
            Err(unavailable())
        }
    }
}

impl LearningIterationCheckpointOwnerV1 {
    /// Root retains its live writer lease across this bounded exchange. Only
    /// one snapshot is transmitted, not two complete protected CAS records.
    pub(crate) fn exchange_learning_checkpoint(
        &self,
        bytes: &[u8],
        next_request_id: &mut u64,
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        if bytes.is_empty() || bytes.len() > FRAME_BOUND {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        let request: Request =
            serde_json::from_slice(bytes).map_err(|_| HostIssuerTransportError::InvalidRequest)?;
        let (schema, binding) = self.profile_identity();
        let operation = match self.frozen_scope_binding() {
            Some(_) => SCOPED_OPERATION,
            None => OPERATION,
        };
        if request.schema != schema
            || request.operation != operation
            || request.request_id != *next_request_id
            || request.request_id == 0
            || request.binding != binding
        {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        *next_request_id = next_request_id
            .checked_add(1)
            .ok_or(HostIssuerTransportError::Unavailable)?;
        let result = match request.command {
            Command::Restore => self.restore(&self.initial.request).and_then(|snapshot| {
                Ok(Reply::Restored {
                    snapshot: snapshot
                        .map(|snapshot| {
                            codec::encode(&snapshot).map(|bytes| STANDARD_NO_PAD.encode(bytes))
                        })
                        .transpose()?,
                })
            }),
            Command::Checkpoint {
                expected_head,
                snapshot,
            } => {
                let next = decode_snapshot(&snapshot)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let expected = next
                    .receipts
                    .last()
                    .map_or(Digest32::ZERO, |receipt| receipt.predecessor);
                if expected_head != expected.to_string() {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                self.checkpoint(expected, &next)
                    .map(|head| Reply::Committed {
                        head: head.to_string(),
                    })
            }
        };
        let result = match result {
            Ok(reply) => reply,
            Err(Error::Conflict) => Reply::Conflict,
            Err(
                Error::Capacity | Error::InvalidRecord | Error::WrongScope | Error::Snapshot(_),
            ) => {
                return Err(HostIssuerTransportError::InvalidRequest);
            }
            Err(Error::Store(_) | Error::CommitUncertain(_)) => {
                return Err(HostIssuerTransportError::Unavailable);
            }
        };
        let bytes = serde_json::to_vec(&Response {
            schema,
            request_id: request.request_id,
            binding,
            result,
        })
        .map_err(|_| HostIssuerTransportError::Unavailable)?;
        if bytes.len() > FRAME_BOUND {
            return Err(HostIssuerTransportError::Unavailable);
        }
        Ok(bytes)
    }
}

fn decode_snapshot(encoded: &str) -> Result<LearningIterationSnapshotV1, Error> {
    if encoded.len() > codec::MAX_BYTES.div_ceil(3) * 4 {
        return Err(Error::Capacity);
    }
    let bytes = STANDARD_NO_PAD
        .decode(encoded)
        .map_err(|_| Error::InvalidRecord)?;
    if STANDARD_NO_PAD.encode(&bytes) != encoded {
        return Err(Error::InvalidRecord);
    }
    codec::decode(&bytes)
}

#[cfg(test)]
#[path = "learning_iteration_checkpoint_transport_tests.rs"]
mod tests;
