use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[derive(Default)]
struct TestOwner {
    entered: AtomicUsize,
    effects: AtomicUsize,
    fenced: AtomicBool,
}

impl LocalServiceOwner for TestOwner {
    async fn handle(
        &self,
        _peer_uid: u32,
        request: &[u8],
        _original_deadline: Instant,
    ) -> Result<Vec<u8>, ConsumerPortError> {
        self.entered.fetch_add(1, Ordering::SeqCst);
        if self.fenced.load(Ordering::SeqCst) {
            return Err(ConsumerPortError::Unavailable);
        }
        if request == b"status" {
            return Ok(if self.effects.load(Ordering::SeqCst) > 0 {
                b"completed".to_vec()
            } else {
                b"unknown".to_vec()
            });
        }
        if request == b"pending" {
            std::future::pending::<()>().await;
        }
        assert_ne!(request, b"panic", "synthetic owner panic");
        if request == b"slow" {
            std::thread::sleep(Duration::from_millis(150));
        }
        self.effects.fetch_add(1, Ordering::SeqCst);
        Ok(b"completed".to_vec())
    }

    fn fence_unknown(&self) {
        self.fenced.store(true, Ordering::SeqCst);
    }

    async fn close(&self) {}
}

fn config() -> LocalServiceConfig {
    LocalServiceConfig {
        socket_path: std::path::PathBuf::from("/unused-in-memory-fixture"),
        ipc_group_gid: 1000,
        service_uid: 1000,
        allowed_peer_uids: vec![1001],
        request_timeout_ms: 40,
        shutdown_drain_ms: 100,
    }
}

#[tokio::test]
async fn stalled_request_frame_does_not_fence_unentered_owner() {
    let owner = Arc::new(TestOwner::default());
    let serving = Arc::clone(&owner);
    let (mut client, stream) = tokio::io::duplex(64);
    let service = tokio::spawn(async move {
        serve_connection(
            stream,
            &config(),
            &*serving,
            Instant::now() + Duration::from_millis(40),
            |_| Ok(1001),
        )
        .await;
    });
    client.write_u32(7).await.unwrap();
    client.write_all(b"pend").await.unwrap();
    let mut response = Vec::new();
    timeout(Duration::from_secs(2), client.read_to_end(&mut response))
        .await
        .unwrap()
        .unwrap();
    service.await.unwrap();
    assert_eq!(owner.entered.load(Ordering::SeqCst), 0);
    assert!(
        !owner.fenced.load(Ordering::SeqCst),
        "incomplete framing has no owner mutation to fence"
    );
}

#[tokio::test]
async fn cancelled_entered_request_still_fences_owner() {
    let owner = Arc::new(TestOwner::default());
    let serving = Arc::clone(&owner);
    let (mut client, stream) = tokio::io::duplex(64);
    let service = tokio::spawn(async move {
        serve_connection(
            stream,
            &config(),
            &*serving,
            Instant::now() + Duration::from_millis(40),
            |_| Ok(1001),
        )
        .await;
    });
    client.write_u32(7).await.unwrap();
    client.write_all(b"pending").await.unwrap();
    let mut response = Vec::new();
    timeout(Duration::from_secs(2), client.read_to_end(&mut response))
        .await
        .unwrap()
        .unwrap();
    service.await.unwrap();
    assert_eq!(owner.entered.load(Ordering::SeqCst), 1);
    assert!(owner.fenced.load(Ordering::SeqCst));
}

#[tokio::test]
async fn response_backpressure_does_not_fence_completed_owner() {
    let owner = Arc::new(TestOwner::default());
    let serving = Arc::clone(&owner);
    let (mut client, stream) = tokio::io::duplex(4);
    let service = tokio::spawn(async move {
        serve_connection(
            stream,
            &config(),
            &*serving,
            Instant::now() + Duration::from_millis(40),
            |_| Ok(1001),
        )
        .await;
    });
    client.write_u32(4).await.unwrap();
    client.write_all(b"ping").await.unwrap();
    // Do not read the reply until its writer has exhausted the transport budget.
    timeout(Duration::from_secs(2), service)
        .await
        .unwrap()
        .unwrap();
    let mut partial_response = Vec::new();
    client.read_to_end(&mut partial_response).await.unwrap();
    assert_eq!(partial_response, 9_u32.to_be_bytes());
    assert_eq!(owner.entered.load(Ordering::SeqCst), 1);
    assert!(!owner.fenced.load(Ordering::SeqCst));
}

#[tokio::test]
async fn expired_original_deadline_rejects_before_owner_entry() {
    let owner = TestOwner::default();
    let (mut client, stream) = tokio::io::duplex(64);
    client.write_u32(4).await.unwrap();
    client.write_all(b"ping").await.unwrap();
    let original_deadline = Instant::now() + Duration::from_millis(10);
    // The accepted connection waits before its task is scheduled. Its frame is
    // ready, but queue time must not become a fresh request budget.
    tokio::time::sleep(Duration::from_millis(20)).await;
    serve_connection(stream, &config(), &owner, original_deadline, |_| Ok(1001)).await;
    assert_eq!(owner.entered.load(Ordering::SeqCst), 0);
    assert!(!owner.fenced.load(Ordering::SeqCst));
}

#[tokio::test]
async fn expiry_during_final_peer_check_rejects_before_owner_entry() {
    let owner = TestOwner::default();
    let (mut client, stream) = tokio::io::duplex(64);
    client.write_u32(4).await.unwrap();
    client.write_all(b"ping").await.unwrap();
    let checks = AtomicUsize::new(0);
    serve_connection(
        stream,
        &config(),
        &owner,
        Instant::now() + Duration::from_millis(10),
        |_| {
            if checks.fetch_add(1, Ordering::SeqCst) == 1 {
                std::thread::sleep(Duration::from_millis(20));
            }
            Ok(1001)
        },
    )
    .await;
    assert_eq!(checks.load(Ordering::SeqCst), 2);
    assert_eq!(owner.entered.load(Ordering::SeqCst), 0);
    assert!(!owner.fenced.load(Ordering::SeqCst));
}

#[tokio::test]
async fn changed_peer_cannot_enter_the_owner() {
    let owner = TestOwner::default();
    let (mut client, stream) = tokio::io::duplex(64);
    client.write_u32(4).await.unwrap();
    client.write_all(b"ping").await.unwrap();
    let checks = AtomicUsize::new(0);
    serve_connection(
        stream,
        &config(),
        &owner,
        Instant::now() + Duration::from_secs(1),
        |_| Ok(1001 + checks.fetch_add(1, Ordering::SeqCst) as u32),
    )
    .await;
    assert_eq!(checks.load(Ordering::SeqCst), 2);
    assert_eq!(owner.entered.load(Ordering::SeqCst), 0);
    assert!(!owner.fenced.load(Ordering::SeqCst));
}

#[tokio::test]
async fn denied_peer_cannot_enter_or_fence_the_owner() {
    let owner = TestOwner::default();
    let (mut client, stream) = tokio::io::duplex(64);
    client.write_u32(4).await.unwrap();
    client.write_all(b"ping").await.unwrap();
    serve_connection(
        stream,
        &config(),
        &owner,
        Instant::now() + Duration::from_secs(1),
        |_| Ok(1002),
    )
    .await;
    assert_eq!(owner.entered.load(Ordering::SeqCst), 0);
    assert!(!owner.fenced.load(Ordering::SeqCst));
}

#[tokio::test]
async fn panicking_owner_is_fenced_before_task_completion() {
    let owner = Arc::new(TestOwner::default());
    let serving = Arc::clone(&owner);
    let (mut client, stream) = tokio::io::duplex(64);
    let service = tokio::spawn(async move {
        serve_connection(
            stream,
            &config(),
            &*serving,
            Instant::now() + Duration::from_secs(1),
            |_| Ok(1001),
        )
        .await;
    });
    client.write_u32(5).await.unwrap();
    client.write_all(b"panic").await.unwrap();
    assert!(service.await.unwrap_err().is_panic());
    assert_eq!(owner.entered.load(Ordering::SeqCst), 1);
    assert!(owner.fenced.load(Ordering::SeqCst));
}

#[tokio::test]
async fn late_ready_completion_withholds_reply_without_losing_original_result() {
    let owner = TestOwner::default();
    let (mut client, stream) = tokio::io::duplex(64);
    client.write_u32(4).await.unwrap();
    client.write_all(b"slow").await.unwrap();
    serve_connection(
        stream,
        &config(),
        &owner,
        Instant::now() + Duration::from_millis(100),
        |_| Ok(1001),
    )
    .await;
    let mut late_response = Vec::new();
    client.read_to_end(&mut late_response).await.unwrap();
    assert!(late_response.is_empty());
    assert!(!owner.fenced.load(Ordering::SeqCst));
    assert_eq!(owner.effects.load(Ordering::SeqCst), 1);

    let (mut status_client, status_stream) = tokio::io::duplex(64);
    status_client.write_u32(6).await.unwrap();
    status_client.write_all(b"status").await.unwrap();
    serve_connection(
        status_stream,
        &config(),
        &owner,
        Instant::now() + Duration::from_secs(1),
        |_| Ok(1001),
    )
    .await;
    assert_eq!(status_client.read_u32().await.unwrap(), 9);
    let mut original = Vec::new();
    status_client.read_to_end(&mut original).await.unwrap();
    assert_eq!(original, b"completed");
    assert_eq!(owner.effects.load(Ordering::SeqCst), 1);
}
