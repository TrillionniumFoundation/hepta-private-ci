//! Exercise the production monitor and readiness probe with the real client worker.
use codex_app_server_client::RemoteAppServerClient;
use codex_hepta_fleet::AgentLifecycle;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::monitor_runtime;
use super::runtime_fixture;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::LifecycleSnapshot;
use crate::RuntimeTasks;
use crate::runtime::TASK_SHUTDOWN_GRACE;

#[derive(Clone, Copy)]
enum ServerHome {
    Matching,
    Mismatched,
}

async fn exercise(server_home: ServerHome) {
    let fixture = runtime_fixture();
    let expected_home = fixture.identity.home_root.to_string_lossy();
    let reported_home = match server_home {
        ServerHome::Matching => expected_home.as_ref(),
        ServerHome::Mismatched => "different-agent-home",
    };
    let (client, mut probe) = RemoteAppServerClient::blocked_close_fixture_for_test(reported_home)
        .await
        .expect("real initialized worker and pending read");
    let cancellation = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(cancellation.clone(), TASK_SHUTDOWN_GRACE)
        .expect("production host shutdown grace");
    let state = Arc::clone(&fixture.state);
    let returned = Arc::new(AtomicBool::new(false));
    let monitor_returned = Arc::clone(&returned);
    let mut client = Some(client);
    tasks
        .spawn_required("readiness-monitor", async move {
            monitor_runtime(state, cancellation, move |_args| {
                std::future::ready(Ok(client.take().expect("one readiness connection")))
            })
            .await?;
            monitor_returned.store(true, Ordering::SeqCst);
            Ok(())
        })
        .expect("monitor admission");

    // Do not cancel before the production probe has acquired the raw client,
    // checked its home, and asked the actual worker to flush a close frame.
    probe
        .wait_for_blocked_close()
        .await
        .expect("readiness shutdown is blocked in the real close flush");
    assert!(!probe.worker_finished());
    assert!(!probe.pending_request_finished());
    timeout(Duration::from_secs(6), tasks.shutdown())
        .await
        .expect("host shutdown after readiness cancellation");

    // Capture the failure before cleanup so cleanup cannot make the regression
    // green. Removing readiness's immediate adoption must leave this worker live.
    let stopped = probe.observe_stopped().await;
    probe.cleanup().await.expect("bounded fixture cleanup");
    stopped.expect("readiness cancellation released the worker and pending request");
    assert!(
        returned.load(Ordering::SeqCst),
        "monitor must return cooperatively through its cancellation select"
    );
    assert_eq!(tasks.active_count(), 0);
    assert!(probe.worker_finished());
    assert!(probe.pending_request_finished());

    let lifecycle = fixture
        .state
        .response(
            /*request_id*/ 1,
            /*spawn_generation*/ 1,
            AgentdMethod::Lifecycle,
        )
        .await
        .expect("lifecycle after cancellation");
    assert_eq!(
        lifecycle.payload,
        AgentdPayload::Lifecycle(LifecycleSnapshot {
            lifecycle: AgentLifecycle::Starting,
            app_server_ready: false,
            fenced: false,
        })
    );
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn monitor_cancellation_releases_matching_home_readiness_worker() {
    exercise(ServerHome::Matching).await;
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn monitor_cancellation_releases_mismatched_home_readiness_worker() {
    exercise(ServerHome::Mismatched).await;
}
