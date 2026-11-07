use super::GitCommandCancellation;
use super::lock_curated_plugins_startup_sync;
use super::sync_with_transport;
use pretty_assertions::assert_eq;
use std::sync::mpsc;
use std::time::Duration;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

struct CancelOnDrop(GitCommandCancellation);

impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

struct OwnedSyncThread {
    cancellation: GitCommandCancellation,
    thread: Option<std::thread::JoinHandle<()>>,
}

impl Drop for OwnedSyncThread {
    fn drop(&mut self) {
        self.cancellation.cancel();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

#[test]
fn cancelling_the_owner_leaves_an_actual_contended_sync_lock_without_acquiring_it() {
    let home = tempfile::tempdir().unwrap();
    let cancellation = GitCommandCancellation::default();
    std::thread::scope(|scope| {
        // Keep this file inside the scope closure so an assertion failure also
        // releases the actual OS lock before scoped-thread cleanup waits.
        let held =
            lock_curated_plugins_startup_sync(home.path(), &GitCommandCancellation::default())
                .unwrap();
        let contender = std::fs::File::options()
            .write(true)
            .open(home.path().join(super::CURATED_PLUGINS_SYNC_LOCK_FILE))
            .unwrap();
        assert!(matches!(
            contender.try_lock(),
            Err(std::fs::TryLockError::WouldBlock)
        ));
        let _cancel_on_exit = CancelOnDrop(cancellation.clone());
        let (started, ready) = mpsc::channel();
        let (done, terminal) = mpsc::channel();
        let worker_cancellation = cancellation.clone();
        let worker_home = home.path();
        let worker = scope.spawn(move || {
            started.send(()).unwrap();
            done.send(
                lock_curated_plugins_startup_sync(worker_home, &worker_cancellation).map(|_| ()),
            )
            .unwrap();
        });
        ready.recv_timeout(Duration::from_secs(5)).unwrap();
        cancellation.cancel();
        let error = terminal
            .recv_timeout(Duration::from_secs(5))
            .unwrap()
            .unwrap_err();
        assert!(
            error.contains("cancelled"),
            "unexpected terminal result: {error}"
        );
        assert!(matches!(
            contender.try_lock(),
            Err(std::fs::TryLockError::WouldBlock)
        ));
        worker.join().unwrap();
        drop(held);
        contender.try_lock().unwrap();
    });
}

#[tokio::test]
async fn cancellation_drops_an_actual_http_request_and_does_not_start_archive_fallback() {
    let home = tempfile::tempdir().unwrap();
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/repos/openai/plugins"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({"default_branch":"main"}))
                .set_delay(Duration::from_secs(30)),
        )
        .expect(1)
        .mount(&server)
        .await;
    let cancellation = GitCommandCancellation::default();
    let worker_cancellation = cancellation.clone();
    let worker_home = home.path().to_path_buf();
    let api = server.uri();
    let backup = format!("{api}/must-not-start-after-cancellation");
    let (done, terminal) = tokio::sync::oneshot::channel();
    let thread = std::thread::spawn(move || {
        let result = sync_with_transport(
            &worker_home,
            /*git_binary*/ None,
            &api,
            &backup,
            &crate::test_support::test_http_client_factory(),
            &worker_cancellation,
        );
        let _ = done.send(result);
    });
    let mut worker = OwnedSyncThread {
        cancellation: cancellation.clone(),
        thread: Some(thread),
    };
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if !server.received_requests().await.unwrap().is_empty() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    cancellation.cancel();
    let error = tokio::time::timeout(Duration::from_secs(5), terminal)
        .await
        .unwrap()
        .unwrap()
        .unwrap_err();
    worker.thread.take().unwrap().join().unwrap();
    assert!(
        error.contains("cancelled"),
        "unexpected terminal result: {error}"
    );
    let requests = server.received_requests().await.unwrap();
    assert_eq!(
        requests
            .iter()
            .map(|request| request.url.path())
            .collect::<Vec<_>>(),
        vec!["/repos/openai/plugins"]
    );
    assert!(!home.path().join(".tmp/plugins").exists());
    assert!(!home.path().join(".tmp/plugins.sha").exists());
}
