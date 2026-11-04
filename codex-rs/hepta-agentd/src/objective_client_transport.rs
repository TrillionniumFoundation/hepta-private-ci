//! Exact bounded frames and kernel-authenticated control replies.

use super::*;

impl<C: ObjectiveSenderCheckpoint> AgentdObjectiveClient<C> {
    pub(super) async fn send_method(
        &self,
        method: crate::AgentdMethod,
    ) -> Result<(AgentdResponse, String), AgentdObjectiveClientError> {
        let request_id = self
            .client
            .next_request_id
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                (value != 0).then(|| value.checked_add(1)).flatten()
            })
            .map_err(|_| AgentdObjectiveClientError::Binding)?;
        let request = AgentdRequest {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation: self.client.spawn_generation,
            method,
        };
        let mut bytes = serde_json::to_vec(&request).map_err(AgentdError::from)?;
        bytes.push(b'\n');
        self.send_frame(request_id, bytes).await
    }

    pub(super) async fn send_frame(
        &self,
        request_id: u64,
        bytes: Vec<u8>,
    ) -> Result<(AgentdResponse, String), AgentdObjectiveClientError> {
        self.require_live()?;
        if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES {
            return Err(AgentdObjectiveClientError::Binding);
        }
        let stream = timeout(
            self.client.timeout,
            tokio::net::UnixStream::connect(&self.client.socket_path),
        )
        .await
        .map_err(|_| AgentdError::Protocol("Objective control connect timed out".to_string()))?
        .map_err(AgentdError::from)?;
        let actual = stream.peer_cred().map_err(AgentdError::from)?;
        if actual.uid() != self.peer.uid || actual.pid() != i32::try_from(self.peer.pid).ok() {
            return Err(AgentdObjectiveClientError::Binding);
        }
        // No await separates the final window/peer checks and starting the write.
        self.require_live()?;
        let (reader, mut writer) = tokio::io::split(stream);
        timeout(self.client.timeout, writer.write_all(&bytes))
            .await
            .map_err(|_| AgentdError::Protocol("Objective control write timed out".to_string()))?
            .map_err(AgentdError::from)?;
        let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
        let mut response_bytes = Vec::new();
        let count = timeout(
            self.client.timeout,
            reader.read_until(b'\n', &mut response_bytes),
        )
        .await
        .map_err(|_| AgentdError::Protocol("Objective control read timed out".to_string()))?
        .map_err(AgentdError::from)?;
        if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !response_bytes.ends_with(b"\n")
        {
            return Err(AgentdObjectiveClientError::Observation);
        }
        if response_bytes == AGENTD_CONTROL_OVERLOAD_FRAME {
            return Err(AgentdError::Overloaded {
                retry_after_ms: AGENTD_OVERLOAD_RETRY_AFTER_MS,
            }
            .into());
        }
        let response: AgentdResponse =
            serde_json::from_slice(&response_bytes).map_err(AgentdError::from)?;
        if response.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
            || response.request_id != request_id
            || response.agent_id != self.client.expected_agent_id
            || response.spawn_generation != self.client.spawn_generation
            // The original daemon accepts Starting at spawn, Running at
            // spawn + 1 and Draining at spawn + 2. Never confuse that lifecycle
            // witness with process identity, or accept a later daemon epoch.
            || !matches!(response.current_generation.checked_sub(self.client.spawn_generation), Some(0..=2))
        {
            return Err(AgentdObjectiveClientError::Binding);
        }
        let raw = String::from_utf8(response_bytes)
            .map_err(|_| AgentdObjectiveClientError::Observation)?;
        Ok((response, raw))
    }
}
