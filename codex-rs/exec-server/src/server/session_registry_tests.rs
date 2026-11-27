use super::*;
use pretty_assertions::assert_eq;
use tokio::sync::mpsc;

fn runtime_paths() -> ExecServerRuntimePaths {
    ExecServerRuntimePaths::new(
        std::env::current_exe().expect("current exe"),
        /*codex_linux_sandbox_exe*/ None,
    )
    .expect("runtime paths")
}

async fn detached_session_id(
    registry: &Arc<SessionRegistry>,
    notifications: RpcNotificationSender,
) -> String {
    let session = registry
        .attach(
            /*resume_session_id*/ None,
            notifications,
            runtime_paths(),
        )
        .await
        .expect("create session");
    let session_id = session.session_id().to_string();
    session.detach().await;
    assert!(!session.is_session_attached());
    session_id
}

#[tokio::test(start_paused = true)]
async fn detached_session_resumes_before_the_original_expiry() {
    let registry = SessionRegistry::new(ExecServerTelemetry::default());
    let (sender, _receiver) = mpsc::channel(/*buffer*/ 16);
    let notifications = RpcNotificationSender::new(sender);
    let session_id = detached_session_id(&registry, notifications.clone()).await;

    tokio::time::advance(Duration::from_millis(199)).await;
    let resumed = registry
        .attach(Some(session_id.clone()), notifications, runtime_paths())
        .await
        .expect("session must remain resumable before 200 ms");
    assert_eq!(resumed.session_id(), session_id);
    assert!(resumed.is_session_attached());
    registry.shutdown().await;
}

#[tokio::test(start_paused = true)]
async fn detached_session_is_rejected_at_the_original_expiry() {
    let registry = SessionRegistry::new(ExecServerTelemetry::default());
    let (sender, _receiver) = mpsc::channel(/*buffer*/ 16);
    let notifications = RpcNotificationSender::new(sender);
    let session_id = detached_session_id(&registry, notifications.clone()).await;

    tokio::time::advance(Duration::from_millis(200)).await;
    let error = match registry
        .attach(Some(session_id.clone()), notifications, runtime_paths())
        .await
    {
        Ok(_) => panic!("session must expire at 200 ms"),
        Err(error) => error,
    };
    assert_eq!(
        error,
        invalid_request(format!("unknown session id {session_id}"))
    );
    registry.shutdown().await;
}
