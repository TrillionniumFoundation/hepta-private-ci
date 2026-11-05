use super::ThreadRequestProcessor;
use crate::error_code::invalid_request;
use crate::termination_observation::not_confirmed;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedParams;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedResponse;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedStatus;
use tokio::time::Instant;
use tokio::time::timeout_at;

impl ThreadRequestProcessor {
    pub(crate) async fn thread_background_terminals_terminate_observed(
        &self,
        params: ThreadBackgroundTerminalsTerminateObservedParams,
        end: Instant,
    ) -> Result<ThreadBackgroundTerminalsTerminateObservedResponse, JSONRPCErrorError> {
        if Instant::now() >= end {
            return Ok(not_confirmed());
        }
        let process_id = params.process_id.parse::<i32>().map_err(|err| {
            invalid_request(format!("invalid background terminal process id: {err}"))
        })?;
        let (_, thread) = match timeout_at(end, self.load_thread(&params.thread_id)).await {
            Ok(loaded) => loaded?,
            Err(_) => return Ok(not_confirmed()),
        };
        // The existing Core API owns the exact process, its observation, and cleanup.
        // A timeout/cancel here drops that future without treating its ACK as exit.
        let confirmed = thread
            .terminate_background_terminal_until(process_id, end)
            .await;
        if confirmed && Instant::now() < end {
            Ok(ThreadBackgroundTerminalsTerminateObservedResponse {
                status: ThreadBackgroundTerminalsTerminateObservedStatus::Confirmed,
            })
        } else {
            Ok(not_confirmed())
        }
    }
}
