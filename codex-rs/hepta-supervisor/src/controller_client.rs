//! Bounded lifecycle client; request IDs also identify the original durable receipt.

use std::path::PathBuf;
use std::time::Duration;

use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;

use crate::SupervisorControllerMethod;
use crate::SupervisorControllerRequest;
use crate::SupervisorError;
use crate::SupervisordPayload;
use crate::SupervisordResponse;
use crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES;
use crate::daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;

pub struct SupervisorControllerClient {
    socket_path: PathBuf,
    owner_uid: u32,
}

impl SupervisorControllerClient {
    pub fn new(socket_path: PathBuf, owner_uid: u32) -> Result<Self, SupervisorError> {
        if !socket_path.is_absolute() {
            return Err(SupervisorError::Invalid(
                "controller requires an absolute socket path".into(),
            ));
        }
        Ok(Self {
            socket_path,
            owner_uid,
        })
    }

    /// An uncertain reply must be inspected using Receipt and the same original
    /// mutation request ID. This client never retries a process effect.
    pub async fn request(
        &self,
        request: SupervisorControllerRequest,
    ) -> Result<SupervisordPayload, SupervisorError> {
        request.clone().owner_request().map_err(|error| {
            SupervisorError::Invalid(format!("invalid controller request: {error:?}"))
        })?;
        tokio::time::timeout(Duration::from_secs(3), self.exchange(request))
            .await
            .map_err(|_| {
                std::io::Error::new(
                    std::io::ErrorKind::TimedOut,
                    "controller outcome requires receipt inspection",
                )
            })?
    }

    async fn exchange(
        &self,
        request: SupervisorControllerRequest,
    ) -> Result<SupervisordPayload, SupervisorError> {
        let mut stream = UnixStream::connect(&self.socket_path).await?;
        stream.ensure_peer_user(self.owner_uid)?;
        let mut bytes = serde_json::to_vec(&request).map_err(invalid)?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES {
            return Err(invalid("controller request exceeded frame bound"));
        }
        stream.write_all(&bytes).await?;
        stream.shutdown().await?;
        let mut reader = BufReader::new(stream).take(MAX_SUPERVISORD_CONTROL_FRAME_BYTES + 1);
        let mut bytes = Vec::new();
        let count = reader.read_until(b'\n', &mut bytes).await?;
        if count == 0
            || count as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES
            || !bytes.ends_with(b"\n")
        {
            return Err(invalid("controller response is incomplete or oversized"));
        }
        let response: SupervisordResponse = serde_json::from_slice(&bytes).map_err(invalid)?;
        if response.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION
            || response.request_id != request.request_id
        {
            return Err(invalid("controller response identity mismatch"));
        }
        let matches_request = match (&request.method, &response.payload) {
            (
                SupervisorControllerMethod::Start { fence },
                SupervisordPayload::MutationAccepted {
                    operation,
                    agent,
                    production_receipt,
                    accepted_state_digest,
                    ..
                },
            ) => {
                accepted_state_digest == &fence.state_digest
                    && agent.agent_id == fence.agent_id
                    && *operation == crate::SupervisordMutation::Start
                    && production_receipt.is_none()
            }
            (
                SupervisorControllerMethod::Stop { fence },
                SupervisordPayload::MutationAccepted {
                    operation,
                    agent,
                    production_receipt,
                    accepted_state_digest,
                    ..
                },
            ) => {
                accepted_state_digest == &fence.state_digest
                    && agent.agent_id == fence.agent_id
                    && *operation == crate::SupervisordMutation::Stop
                    && production_receipt.is_none()
            }
            (
                SupervisorControllerMethod::Restart { fence },
                SupervisordPayload::MutationAccepted {
                    operation,
                    agent,
                    production_receipt,
                    accepted_state_digest,
                    ..
                },
            ) => {
                accepted_state_digest == &fence.state_digest
                    && agent.agent_id == fence.agent_id
                    && *operation == crate::SupervisordMutation::Restart
                    && production_receipt.is_none()
            }
            (
                SupervisorControllerMethod::Receipt {
                    agent_id,
                    mutation_request_id,
                },
                SupervisordPayload::OrdinaryMutationStatus { status },
            ) => status.as_ref().is_none_or(|status| {
                status.agent_id == *agent_id && status.request_id == *mutation_request_id
            }),
            (_, SupervisordPayload::Error { .. }) => true,
            _ => false,
        };
        if !matches_request {
            return Err(invalid("controller returned another operation's outcome"));
        }
        Ok(response.payload)
    }
}

fn invalid(error: impl std::fmt::Display) -> SupervisorError {
    SupervisorError::Invalid(error.to_string())
}

#[cfg(test)]
#[path = "controller_client_tests.rs"]
mod tests;
