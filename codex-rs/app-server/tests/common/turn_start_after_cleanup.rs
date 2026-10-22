use std::time::Duration;

use anyhow::Context;
use codex_app_server_protocol::JSONRPCMessage;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;

use super::DEFAULT_REQUEST_TIMEOUT;
use super::TestAppServer;

impl TestAppServer {
    /// Starts the next successful fixture turn after terminal cleanup finishes.
    ///
    /// A completion notification can arrive before Core retires the preceding
    /// turn's admission fence. Only the two exact pre-admission refusals are
    /// retried, with fresh request IDs within the existing request timeout.
    /// Disconnects, timeouts, and other errors never cause another submission.
    /// Tests of admission rejection must use the ordinary request methods.
    pub async fn start_turn_after_terminal_cleanup(
        &mut self,
        params: TurnStartParams,
    ) -> anyhow::Result<TurnStartResponse> {
        self.start_turn_after_terminal_cleanup_with_timeout(params, DEFAULT_REQUEST_TIMEOUT)
            .await
    }

    /// Retains a suite's existing response timeout while awaiting admission.
    pub async fn start_turn_after_terminal_cleanup_with_timeout(
        &mut self,
        params: TurnStartParams,
        timeout: Duration,
    ) -> anyhow::Result<TurnStartResponse> {
        tokio::time::timeout(timeout, async {
            loop {
                let request_id = RequestId::Integer(
                    self.send_turn_start_request(params.clone()).await?,
                );
                let message = self
                    .read_stream_until_message(|message| {
                        // Server requests have their own ID namespace and can
                        // overlap this client ID. Keep them buffered for the
                        // fixture that owns their response.
                        match message {
                            JSONRPCMessage::Response(response) => response.id == request_id,
                            JSONRPCMessage::Error(error) => error.id == request_id,
                            JSONRPCMessage::Request(_) | JSONRPCMessage::Notification(_) => false,
                        }
                    })
                    .await?;
                match message {
                    JSONRPCMessage::Response(response) => {
                        return crate::to_response(response);
                    }
                    JSONRPCMessage::Error(error)
                        if error.error.code == -32603
                            && error.error.data.is_none()
                            && matches!(
                                error.error.message.as_str(),
                                "failed to submit turn input: NotIdle"
                                    | "failed to submit turn input: turn start is fenced while the session is terminalizing"
                            ) =>
                    {
                        tokio::time::sleep(Duration::from_millis(25)).await;
                    }
                    other => anyhow::bail!("turn/start did not succeed: {other:?}"),
                }
            }
        })
        .await
        .context("previous turn must retire its admission fence before the next starts")?
    }
}
