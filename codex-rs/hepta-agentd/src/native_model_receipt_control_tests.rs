//! Exercise the original socket's real kernel peer, not a JSON authority claim.
use super::*;
use crate::AgentdNativeModelReceiptReaderV1;
use std::future::Future;
use std::os::unix::fs::MetadataExt;
use std::pin::Pin;
use std::sync::atomic::AtomicUsize;

struct Reader(Arc<AtomicUsize>);
impl AgentdNativeModelReceiptReaderV1 for Reader {
    fn read<'a>(
        &'a self,
        _: &'a str,
    ) -> Pin<Box<dyn Future<Output = Result<Option<String>, crate::AgentdError>> + Send + 'a>> {
        Box::pin(async move {
            self.0.fetch_add(1, Ordering::SeqCst);
            Ok(None)
        })
    }
}

#[tokio::test]
async fn real_non_root_kernel_peer_cannot_read_native_receipts_or_invoke_owner_callback()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = runtime_fixture();
    let uid = std::fs::metadata("/proc/self")?.uid();
    assert_ne!(
        uid, 0,
        "ordinary owner fixture requires the non-Root workload"
    );
    let calls = Arc::new(AtomicUsize::new(0));
    fixture
        .state
        .native_model_receipt_reader
        .set(Arc::new(Reader(calls.clone())))
        .map_err(|_| "reader already attached")?;
    let cancellation = CancellationToken::new();
    let server = crate::control::AgentdControlServer::bind(
        fixture.identity.control_socket.clone(),
        fixture.state.clone(),
        cancellation.clone(),
    )
    .await?;
    let task = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(
        fixture.identity.control_socket.clone(),
        fixture.identity.agent_id.clone(),
        fixture.identity.spawn_generation,
    )?
    .with_peer_process(uid, std::process::id())?;
    assert!(
        client
            .native_model_receipt("assessment-1".into())
            .await
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    // Existing lifecycle reads remain available to their original workload.
    client.health().await?;
    cancellation.cancel();
    task.await??;
    Ok(())
}

#[tokio::test]
#[ignore = "requires an actual UID0 process; ordinary owning tests prove non-Root rejection"]
async fn real_root_kernel_peer_reads_definite_absence_through_the_original_owner_callback()
-> Result<(), Box<dyn std::error::Error>> {
    assert_eq!(
        std::fs::metadata("/proc/self")?.uid(),
        0,
        "actual Root peer required"
    );
    let fixture = runtime_fixture();
    let calls = Arc::new(AtomicUsize::new(0));
    fixture
        .state
        .native_model_receipt_reader
        .set(Arc::new(Reader(calls.clone())))
        .map_err(|_| "reader already attached")?;
    let cancellation = CancellationToken::new();
    let server = crate::control::AgentdControlServer::bind(
        fixture.identity.control_socket.clone(),
        fixture.state.clone(),
        cancellation.clone(),
    )
    .await?;
    let task = tokio::spawn(server.run());
    // This fixture tests the server's real Root authorization only. Installed
    // Root callers additionally pin the independently launched Agent UID/PID.
    let client = crate::AgentdClient::new(
        fixture.identity.control_socket.clone(),
        fixture.identity.agent_id.clone(),
        fixture.identity.spawn_generation,
    )?;
    assert_eq!(
        client.native_model_receipt("assessment-1".into()).await?,
        (1, None)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    cancellation.cancel();
    task.await??;
    Ok(())
}
