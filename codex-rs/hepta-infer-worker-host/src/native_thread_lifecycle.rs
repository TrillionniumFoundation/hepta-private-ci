//! Bounded cleanup for normal returns; cancellation/unwind is observable, not
//! falsely reported as successful asynchronous cleanup from Drop.

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use tokio::time::timeout;

use super::RPC_TIMEOUT;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Phase {
    Prepared,
    EffectPossible,
    TerminalDurable,
}

pub(super) struct ThreadLifecycle {
    thread_id: String,
    phase: Phase,
    finished: bool,
}

impl ThreadLifecycle {
    pub(super) fn new(thread_id: String) -> Self {
        Self {
            thread_id,
            phase: Phase::Prepared,
            finished: false,
        }
    }

    pub(super) fn effect_possible(&mut self) {
        self.phase = Phase::EffectPossible;
    }

    pub(super) fn terminal_durable(&mut self) {
        self.phase = Phase::TerminalDurable;
    }

    pub(super) async fn finish(&mut self, mut client: RemoteAppServerClient) {
        match self.phase {
            Phase::Prepared | Phase::TerminalDurable => {
                eprintln!("runtime.codex.thread_cleanup_attempted");
                match timeout(
                    RPC_TIMEOUT,
                    client.request(ClientRequest::ThreadUnsubscribe {
                        request_id: RequestId::Integer(4),
                        params: ThreadUnsubscribeParams {
                            thread_id: self.thread_id.clone(),
                        },
                    }),
                )
                .await
                {
                    Ok(Ok(Ok(_))) => eprintln!("runtime.codex.thread_cleanup_acknowledged"),
                    Ok(Ok(Err(_))) | Ok(Err(_)) | Err(_) => {
                        eprintln!("runtime.codex.thread_cleanup_unknown")
                    }
                }
            }
            Phase::EffectPossible => {
                // Do not remove the only remaining source of reconciliation.
                eprintln!("runtime.codex.thread_retained_for_reconciliation");
            }
        }
        match timeout(RPC_TIMEOUT, client.shutdown()).await {
            Ok(Ok(())) => {}
            Ok(Err(_)) => eprintln!("runtime.codex.client_shutdown_failed"),
            Err(_) => eprintln!("runtime.codex.client_shutdown_timeout"),
        }
        self.finished = true;
    }
}

impl Drop for ThreadLifecycle {
    fn drop(&mut self) {
        if !self.finished {
            // No async spawn, no detached cleanup and no claim that Drop can
            // complete an RPC. Route this counter to the owner's orphan sweep.
            eprintln!("runtime.codex.thread_cleanup_abandoned");
        }
    }
}
