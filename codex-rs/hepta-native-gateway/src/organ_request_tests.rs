use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_runtime::RuntimeAuthorityStatus;
use codex_hepta_runtime::RuntimeStateAdapter;
use codex_hepta_runtime::RuntimeStateStatus;
use pretty_assertions::assert_eq;

use super::*;

#[derive(Debug)]
struct RequestObservedAdapter(Arc<AtomicUsize>);

impl RuntimeStateAdapter for RequestObservedAdapter {
    fn status(&self) -> RuntimeStateStatus {
        self.0.fetch_add(1, Ordering::SeqCst);
        RuntimeStateStatus {
            adapter: "http-test-adapter",
            schema_version: 5,
            outcome_generation: 1,
            preference_generation: 2,
            runtime_snapshot_version: 1,
            runtime_snapshot_generation: 3,
            integrity_binding_present: true,
            integrity_verification: "test-only",
            open_mode: "read-only-test",
        }
    }
}

#[tokio::test]
async fn loopback_http_request_reaches_the_read_only_status_organ() -> Result<()> {
    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-http-organ"))?;
    let runtime = Arc::new(HeptaRuntime::from_adapter(
        root,
        Arc::new(RequestObservedAdapter(Arc::clone(&calls))),
    ));
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        serve_connection(stream, runtime).await
    });
    let mut client = TcpStream::connect(address).await?;
    client
        .write_all(b"GET /api/hepta/runtime HTTP/1.1\r\nHost: localhost\r\n\r\n")
        .await?;
    let mut bytes = Vec::new();
    tokio::time::timeout(RESPONSE_TIMEOUT, client.read_to_end(&mut bytes)).await??;
    server.await??;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let wire = std::str::from_utf8(&bytes)?;
    let (headers, body) = wire.split_once("\r\n\r\n").context("HTTP framing")?;
    assert!(headers.starts_with("HTTP/1.1 200 OK\r\n"));
    let body: serde_json::Value = serde_json::from_str(body)?;
    assert_eq!(body["state"]["adapter"], "http-test-adapter");
    assert_eq!(
        body["authority"],
        serde_json::to_value(RuntimeAuthorityStatus::default())?
    );
    Ok(())
}
