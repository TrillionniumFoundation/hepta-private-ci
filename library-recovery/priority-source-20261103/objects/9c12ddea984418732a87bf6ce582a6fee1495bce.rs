//! Real host supervision and real transport-worker close in one qualification.
use codex_app_server_client::RemoteAppServerClient;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::RuntimeTasks;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::time::Instant;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

#[derive(Clone, Copy)]
enum Ownership {
    AbortOnDrop,
    LegacyUnowned,
}

async fn exercise(ownership: Ownership) {
    let (client, mut probe) = RemoteAppServerClient::blocked_close_fixture_for_test("fixture")
        .await
        .expect("real initialized worker and pending read");
    // Match the production host's grace without shortening client timeouts.
    let grace = Duration::from_secs(3);
    let mut tasks = RuntimeTasks::new(CancellationToken::new(), grace).expect("host");
    let returned = Arc::new(AtomicBool::new(false));
    let child_returned = Arc::clone(&returned);
    tasks
        .spawn_required("blocked-owned-transport", async move {
            let result = match ownership {
                Ownership::AbortOnDrop => client.into_abort_on_drop().shutdown().await,
                Ownership::LegacyUnowned => client.shutdown().await,
            };
            child_returned.store(true, Ordering::SeqCst);
            result.map_err(|error| AgentdError::Protocol(error.to_string()))
        })
        .expect("host admission");
    let start = Instant::now();
    {
        let shutdown = tasks.shutdown();
        tokio::pin!(shutdown);
        // On this current-thread runtime the child cannot start until we yield.
        // The initial barrier is pending, so this select starts the real host
        // grace before the child's five-second shutdown wait can begin. Prefer
        // an already delivered barrier on later polls, before host completion.
        tokio::select! {
            biased;
            blocked = probe.wait_for_blocked_close() => {
                blocked.expect("actual close-frame flush is pending");
            }
            _ = &mut shutdown => panic!("host returned before the close-flush barrier"),
        }
        assert!(!probe.worker_finished());
        assert!(!probe.pending_request_finished());
        timeout(Duration::from_secs(6), &mut shutdown)
            .await
            .expect("host shutdown");
    }
    assert!(start.elapsed() >= grace, "the real host grace was bypassed");
    assert_eq!(tasks.active_count(), 0);
    assert!(
        !returned.load(Ordering::SeqCst),
        "child returned instead of being aborted by the host"
    );
    match ownership {
        Ownership::AbortOnDrop => {
            probe
                .observe_stopped()
                .await
                .expect("actual transport and pending map released after abort");
            assert!(probe.worker_finished());
        }
        Ownership::LegacyUnowned => {
            assert!(
                !probe.worker_finished(),
                "negative control must expose the detached worker"
            );
            assert!(!probe.pending_request_finished());
        }
    }
    // Only after the assertions: negative-control worker and fixture peer cleanup.
    probe
        .cleanup()
        .await
        .expect("explicit bounded fixture cleanup");
}

#[tokio::test(flavor = "current_thread")]
async fn runtime_tasks_abort_drops_real_worker_blocked_in_close_flush() {
    exercise(Ownership::AbortOnDrop).await;
}

#[tokio::test(flavor = "current_thread")]
async fn runtime_tasks_negative_control_exposes_unowned_worker_after_host_abort() {
    exercise(Ownership::LegacyUnowned).await;
}
