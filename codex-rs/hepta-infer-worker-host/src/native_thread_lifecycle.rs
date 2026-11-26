//! Bounded cleanup for prepared/settled ephemeral threads. Unknown effects retain
//! their history: neither Drop nor disconnect is a terminal observation.

use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_app_server_client::RemoteAppServerRequestHandle;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use codex_app_server_protocol::ThreadUnsubscribeResponse;

static CLEANUP_ATTEMPTS: AtomicU64 = AtomicU64::new(0);
static CLEANUP_FAILURES: AtomicU64 = AtomicU64::new(0);
static UNKNOWN_RETAINED: AtomicU64 = AtomicU64::new(0);
static DROP_CLEANUPS: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(32);

/// Process-local diagnostics, not durable evidence or a capacity-release oracle.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeCleanupMetrics {
    pub attempted: u64,
    pub failed_or_orphaned: u64,
    pub unknown_history_retained: u64,
}

pub fn native_cleanup_metrics() -> NativeCleanupMetrics {
    NativeCleanupMetrics {
        attempted: CLEANUP_ATTEMPTS.load(Ordering::Relaxed),
        failed_or_orphaned: CLEANUP_FAILURES.load(Ordering::Relaxed),
        unknown_history_retained: UNKNOWN_RETAINED.load(Ordering::Relaxed),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Phase {
    Prepared,
    EffectPossible,
    TerminalDurable,
    CleanupRequested,
}

pub(crate) struct NativeThreadGuard {
    handle: RemoteAppServerRequestHandle,
    thread_id: String,
    phase: Phase,
}

impl NativeThreadGuard {
    pub(crate) fn new(handle: RemoteAppServerRequestHandle, thread_id: String) -> Self {
        Self {
            handle,
            thread_id,
            phase: Phase::Prepared,
        }
    }

    pub(crate) fn effect_entered(&mut self) {
        self.phase = Phase::EffectPossible;
    }

    // Called only AFTER settle_native/reject_native_before_start successfully
    // committed a matching terminal/rejection record. Never call on a raw event.
    pub(crate) fn terminal_persisted(&mut self) {
        self.phase = Phase::TerminalDurable;
    }

    pub(crate) async fn cleanup(&mut self) {
        if !matches!(self.phase, Phase::Prepared | Phase::TerminalDurable) {
            return;
        }
        self.phase = Phase::CleanupRequested;
        cleanup(self.handle.clone(), self.thread_id.clone()).await;
    }
}

impl Drop for NativeThreadGuard {
    fn drop(&mut self) {
        match self.phase {
            Phase::CleanupRequested => {}
            Phase::EffectPossible => {
                UNKNOWN_RETAINED.fetch_add(1, Ordering::Relaxed);
            }
            Phase::Prepared | Phase::TerminalDurable => {
                let Ok(runtime) = tokio::runtime::Handle::try_current() else {
                    CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
                    return;
                };
                let Ok(permit) = DROP_CLEANUPS.try_acquire() else {
                    CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
                    return;
                };
                let handle = self.handle.clone();
                let thread_id = self.thread_id.clone();
                runtime.spawn(async move {
                    cleanup(handle, thread_id).await;
                    drop(permit);
                });
            }
        }
    }
}

async fn cleanup(handle: RemoteAppServerRequestHandle, thread_id: String) {
    CLEANUP_ATTEMPTS.fetch_add(1, Ordering::Relaxed);
    let response = tokio::time::timeout(
        Duration::from_secs(5),
        handle.request_typed::<ThreadUnsubscribeResponse>(ClientRequest::ThreadUnsubscribe {
            request_id: RequestId::String(format!("hepta-cleanup:{thread_id}")),
            params: ThreadUnsubscribeParams { thread_id },
        }),
    )
    .await;
    if !matches!(response, Ok(Ok(_))) {
        CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
    }
}
