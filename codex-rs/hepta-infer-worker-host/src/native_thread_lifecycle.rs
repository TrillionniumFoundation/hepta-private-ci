//! Durable cleanup for prepared/settled ephemeral threads. Unknown effects retain
//! their history: neither Drop nor disconnect is a terminal observation.

use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_app_server_client::RemoteAppServerRequestHandle;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use codex_app_server_protocol::ThreadUnsubscribeResponse;
use tokio::time::Instant;

use crate::native_app_server::Result;
use crate::native_cleanup_store::CleanupObligation;
use crate::native_cleanup_store::NativeCleanupStore;

static CLEANUP_ATTEMPTS: AtomicU64 = AtomicU64::new(0);
static CLEANUP_FAILURES: AtomicU64 = AtomicU64::new(0);
static UNKNOWN_RETAINED: AtomicU64 = AtomicU64::new(0);
static DROP_CLEANUPS: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(32);

/// Process-local diagnostics. Durable backlog metrics are owned by
/// `NativeCleanupStore` and are the capacity/recovery source of truth.
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
    store: NativeCleanupStore,
    obligation: CleanupObligation,
    phase: Phase,
}

impl NativeThreadGuard {
    pub(crate) async fn create(
        store: NativeCleanupStore,
        handle: RemoteAppServerRequestHandle,
        operation_id: String,
        thread_id: String,
        session_id: String,
    ) -> Result<Self> {
        let obligation = store.enqueue(operation_id, thread_id, session_id).await?;
        let phase = match obligation.state {
            crate::native_cleanup_store::CleanupState::Prepared => Phase::Prepared,
            crate::native_cleanup_store::CleanupState::EffectPossible => Phase::EffectPossible,
            crate::native_cleanup_store::CleanupState::TerminalDurable => Phase::TerminalDurable,
        };
        Ok(Self {
            handle,
            store,
            obligation,
            phase,
        })
    }

    pub(crate) async fn recover_pending(
        store: &NativeCleanupStore,
        handle: RemoteAppServerRequestHandle,
        deadline: Instant,
    ) -> Result<()> {
        let worker_id = format!("recovery:{}", std::process::id());
        let claims = store
            .claim_ready(worker_id, Duration::from_secs(10), 16)
            .await?;
        for claim in claims {
            if Instant::now() >= deadline {
                store
                    .fail(&claim, "cleanup recovery budget elapsed")
                    .await?;
                break;
            }
            cleanup_claim(store.clone(), handle.clone(), claim, deadline).await;
        }
        Ok(())
    }

    pub(crate) async fn effect_entered(&mut self) -> Result<()> {
        self.obligation = self.store.mark_effect_possible(&self.obligation).await?;
        self.phase = Phase::EffectPossible;
        Ok(())
    }

    // Called only AFTER settle_native/reject_native_before_start or a proved
    // cross-owner pre-effect abort durably committed the matching record.
    pub(crate) async fn terminal_persisted(&mut self) -> Result<()> {
        self.obligation = self.store.mark_terminal_durable(&self.obligation).await?;
        self.phase = Phase::TerminalDurable;
        Ok(())
    }

    pub(crate) async fn cleanup(&mut self) {
        if !matches!(self.phase, Phase::Prepared | Phase::TerminalDurable) {
            return;
        }
        let worker_id = format!("inline:{}", std::process::id());
        let claim = match self
            .store
            .claim_exact(&self.obligation, worker_id, Duration::from_secs(10))
            .await
        {
            Ok(Some(claim)) => claim,
            Ok(None) => return,
            Err(_) => {
                CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
                return;
            }
        };
        self.phase = Phase::CleanupRequested;
        cleanup_claim(
            self.store.clone(),
            self.handle.clone(),
            claim,
            Instant::now() + Duration::from_secs(5),
        )
        .await;
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
                let store = self.store.clone();
                let handle = self.handle.clone();
                let obligation = self.obligation.clone();
                runtime.spawn(async move {
                    let worker_id = format!("drop:{}", std::process::id());
                    match store
                        .claim_exact(&obligation, worker_id, Duration::from_secs(10))
                        .await
                    {
                        Ok(Some(claim)) => {
                            cleanup_claim(
                                store,
                                handle,
                                claim,
                                Instant::now() + Duration::from_secs(5),
                            )
                            .await;
                        }
                        Ok(None) => {}
                        Err(_) => {
                            CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
                        }
                    }
                    drop(permit);
                });
            }
        }
    }
}

async fn cleanup_claim(
    store: NativeCleanupStore,
    handle: RemoteAppServerRequestHandle,
    claim: crate::native_cleanup_store::CleanupClaim,
    deadline: Instant,
) {
    CLEANUP_ATTEMPTS.fetch_add(1, Ordering::Relaxed);
    let request =
        handle.request_typed::<ThreadUnsubscribeResponse>(ClientRequest::ThreadUnsubscribe {
            request_id: RequestId::String(format!(
                "hepta-cleanup:{}:{}",
                claim.fence, claim.operation_id
            )),
            params: ThreadUnsubscribeParams {
                thread_id: claim.thread_id.clone(),
            },
        });
    let response = tokio::time::timeout_at(
        deadline.min(Instant::now() + Duration::from_secs(5)),
        request,
    )
    .await;
    match response {
        Ok(Ok(_)) => {
            if store.complete(&claim).await.is_err() {
                CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
            }
        }
        Ok(Err(error)) => {
            CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
            let _ = store.fail(&claim, &error.to_string()).await;
        }
        Err(_) => {
            CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
            let _ = store.fail(&claim, "thread unsubscribe timed out").await;
        }
    }
}
