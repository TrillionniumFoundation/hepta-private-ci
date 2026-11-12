//! Bounded control framing distinguishes an absent response after a complete
//! request write from a malformed, mismatched, overloaded or rejected reply.
//! It never retries admission or treats transport uncertainty as completion.

use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::Instant;
use tokio::time::timeout_at;

use super::AgentdClient;
use super::unexpected;
use crate::AGENTD_CONTROL_OVERLOAD_FRAME;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AGENTD_OVERLOAD_RETRY_AFTER_MS;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AuthBusObjectiveIngress;
use crate::MAX_CONTROL_FRAME_BYTES;
use crate::ObjectiveStartOutcome;

pub(crate) enum ObjectiveStartReplyV1 {
    Completed(ObjectiveStartOutcome),
    AcknowledgementLost(AgentdError),
}

enum ControlCallError {
    Rejected(AgentdError),
    AcknowledgementLost(AgentdError),
}

impl From<AgentdError> for ControlCallError {
    fn from(error: AgentdError) -> Self {
        Self::Rejected(error)
    }
}

impl AgentdClient {
    pub(crate) async fn objective_start_once(
        &self,
        request: AuthBusObjectiveIngress,
    ) -> Result<ObjectiveStartReplyV1, AgentdError> {
        self.objective_start_with_original_end(request, None).await
    }

    pub(crate) async fn objective_start_once_until(
        &self,
        request: AuthBusObjectiveIngress,
        end: Instant,
    ) -> Result<ObjectiveStartReplyV1, AgentdError> {
        self.objective_start_with_original_end(request, Some(end))
            .await
    }

    async fn objective_start_with_original_end(
        &self,
        request: AuthBusObjectiveIngress,
        end: Option<Instant>,
    ) -> Result<ObjectiveStartReplyV1, AgentdError> {
        let request =
            AgentdRequest::objective_start(self.request_id(), self.spawn_generation, request);
        let response = match self.send_once_with_original_end(request, end).await {
            Ok(response) => response,
            Err(ControlCallError::AcknowledgementLost(error)) => {
                return Ok(ObjectiveStartReplyV1::AcknowledgementLost(error));
            }
            Err(ControlCallError::Rejected(error)) => return Err(error),
        };
        let outcome = match response.payload {
            AgentdPayload::ObjectiveRun(receipt) => ObjectiveStartOutcome::Admitted { receipt },
            AgentdPayload::ObjectiveConflict {
                run_id,
                conflict_digest,
            } => ObjectiveStartOutcome::Conflict {
                run_id,
                conflict_digest,
            },
            payload => return unexpected(payload),
        };
        Ok(ObjectiveStartReplyV1::Completed(outcome))
    }

    pub(super) async fn send(&self, request: AgentdRequest) -> Result<AgentdResponse, AgentdError> {
        self.send_once(request).await.map_err(|error| match error {
            ControlCallError::Rejected(error) | ControlCallError::AcknowledgementLost(error) => {
                error
            }
        })
    }

    async fn send_once(&self, request: AgentdRequest) -> Result<AgentdResponse, ControlCallError> {
        self.send_once_with_original_end(request, None).await
    }

    async fn send_once_with_original_end(
        &self,
        request: AgentdRequest,
        end: Option<Instant>,
    ) -> Result<AgentdResponse, ControlCallError> {
        let expected_request_id = request.request_id;
        let stream = timeout_at(
            self.original_phase_end(end)?,
            UnixStream::connect(&self.socket_path),
        )
        .await
        .map_err(|_| AgentdError::Protocol("agentd control connect timed out".to_string()))?
        .map_err(AgentdError::from)?;
        let (reader, mut writer) = tokio::io::split(stream);
        let mut bytes = serde_json::to_vec(&request).map_err(AgentdError::from)?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES {
            return Err(
                AgentdError::Protocol("agentd request exceeded frame bound".to_string()).into(),
            );
        }
        timeout_at(self.original_phase_end(end)?, writer.write_all(&bytes))
            .await
            .map_err(|_| AgentdError::Protocol("agentd control write timed out".to_string()))?
            .map_err(AgentdError::from)?;
        let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
        let mut response_bytes = Vec::new();
        let read_end = self
            .original_phase_end(end)
            .map_err(ControlCallError::AcknowledgementLost)?;
        let count = timeout_at(read_end, reader.read_until(b'\n', &mut response_bytes))
            .await
            .map_err(|_| {
                ControlCallError::AcknowledgementLost(AgentdError::Protocol(
                    "agentd control read timed out".to_string(),
                ))
            })?
            .map_err(|error| ControlCallError::AcknowledgementLost(AgentdError::from(error)))?;
        if count == 0 {
            return Err(ControlCallError::AcknowledgementLost(
                AgentdError::Protocol(
                    "agentd returned an invalid bounded response frame".to_string(),
                ),
            ));
        }
        if count as u64 > MAX_CONTROL_FRAME_BYTES || !response_bytes.ends_with(b"\n") {
            return Err(AgentdError::Protocol(
                "agentd returned an invalid bounded response frame".to_string(),
            )
            .into());
        }
        if response_bytes.as_slice() == AGENTD_CONTROL_OVERLOAD_FRAME {
            return Err(AgentdError::Overloaded {
                retry_after_ms: AGENTD_OVERLOAD_RETRY_AFTER_MS,
            }
            .into());
        }
        let response: AgentdResponse =
            serde_json::from_slice(&response_bytes).map_err(AgentdError::from)?;
        if response.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
            || response.request_id != expected_request_id
            || response.agent_id != self.expected_agent_id
            || response.spawn_generation != self.spawn_generation
        {
            return Err(AgentdError::Protocol(
                "agentd response identity does not match request".to_string(),
            )
            .into());
        }
        if end.is_some_and(|end| Instant::now() >= end) {
            return Err(ControlCallError::AcknowledgementLost(
                AgentdError::Protocol("original agentd control end elapsed".into()),
            ));
        }
        Ok(response)
    }

    fn original_phase_end(&self, end: Option<Instant>) -> Result<Instant, AgentdError> {
        let now = Instant::now();
        let deadline = end.map_or(now + self.timeout, |end| (now + self.timeout).min(end));
        if now >= deadline {
            return Err(AgentdError::Protocol(
                "original agentd control end elapsed".into(),
            ));
        }
        Ok(deadline)
    }
}

#[cfg(test)]
#[path = "client_control_tests.rs"]
mod tests;
