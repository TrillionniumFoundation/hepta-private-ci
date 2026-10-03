//! Exact historical message reads through the current original App Server.
use super::*;
use native_wire::MessageObservation;

impl AgentChatSession {
    /// Never resumes a thread, reserves a queue row, or sends a message.
    pub async fn observe_message(&self, request: &ChatRequest) -> Result<MessageObservation> {
        request.validate().map_err(invalid)?;
        let ChatCommand::Send {
            thread_id,
            operation_id,
            text,
        } = &request.command
        else {
            return Err(invalid("only original identified messages can be observed"));
        };
        let health = self.agentd.health().await?;
        if !health.ready || health.fenced || !self.connected.load(Ordering::Acquire) {
            return Err(invalid("current original Agent is not ready"));
        }
        let input = vec![UserInput::Text {
            text: text.clone(),
            text_elements: vec![],
        }];
        let digest = crate::bridge_user_input_payload_sha256(&input)?;
        let response: ThreadQueueObserveResponse = self
            .transport
            .request(ClientRequest::ThreadQueueObserve {
                request_id: self.transport.request_id(),
                params: ThreadQueueObserveParams {
                    thread_id: thread_id.clone(),
                    expected_project_id: self.project_id.clone(),
                    expected_cwd: self.workspace.clone(),
                    expected_thread_source: ThreadSource::Feature(SOURCE.into()),
                    client_user_message_id: operation_id.clone(),
                    expected_payload_sha256: digest.clone(),
                },
            })
            .await?;
        crate::ensure_bridge_payload_digest(
            "chat observation",
            operation_id,
            &digest,
            Some(&response.payload_sha256),
        )?;
        if response.client_user_message_id != *operation_id {
            return Err(invalid("original observed operation changed"));
        }
        let after = self.agentd.health().await?;
        if !after.ready || after.fenced || !self.connected.load(Ordering::Acquire) {
            return Err(invalid("original Agent changed during message observation"));
        }
        Ok(match response.outcome {
            ThreadQueueObserveOutcome::Pending {
                queued_submission_id,
            } => MessageObservation::Pending {
                queue_id: queued_submission_id,
            },
            ThreadQueueObserveOutcome::Persisted { turn_id, .. } => {
                MessageObservation::Persisted { turn_id }
            }
            ThreadQueueObserveOutcome::Cancelled => MessageObservation::Cancelled,
            ThreadQueueObserveOutcome::Missing => MessageObservation::Missing,
            ThreadQueueObserveOutcome::Unknown => MessageObservation::Unknown,
        })
    }
}
