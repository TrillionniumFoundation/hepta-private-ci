use super::*;
use codex_hepta_runtime::RuntimeStateAdapter;
use codex_hepta_runtime::RuntimeStateStatus;
use codex_hepta_wire::WireEnvelopeV2;
use tokio::io::DuplexStream;
use tokio::io::duplex;
use tokio::task::JoinHandle;
use tokio::time::timeout;

const TEST_DEADLINE: Duration = Duration::from_secs(3);
const REQUEST: &[u8] = b"GET /api/hepta/runtime HTTP/1.1\r\nHost: localhost\r\nAccept: application/x-hepta-wire; version=2\r\n\r\n";

#[derive(Debug)]
struct FixtureAdapter;

impl RuntimeStateAdapter for FixtureAdapter {
    fn status(&self) -> RuntimeStateStatus {
        RuntimeStateStatus {
            adapter: "fixture",
            schema_version: 5,
            outcome_generation: 0,
            preference_generation: 0,
            runtime_snapshot_version: 1,
            runtime_snapshot_generation: 0,
            integrity_binding_present: true,
            integrity_verification: "hmac-sha256-v1-key-id-and-row-macs-verified",
            open_mode: "immutable-query-only-open-existing",
        }
    }
}

fn runtime() -> Result<Arc<HeptaRuntime>> {
    Ok(Arc::new(HeptaRuntime::from_adapter(
        HeptaStateRoot::parse(std::env::temp_dir().join("hepta-bounded-gateway-test"))?,
        Arc::new(FixtureAdapter),
    )))
}

async fn start() -> Result<(SocketAddr, DuplexStream, JoinHandle<Result<()>>)> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let runtime = runtime()?;
    let (stop, mut stopped) = duplex(1);
    let server = tokio::spawn(connection_loop::serve(
        listener,
        runtime,
        /*max_connections*/ 1,
        async move {
            let mut signal = [0_u8; 1];
            stopped.read_exact(&mut signal).await?;
            Ok(())
        },
    ));
    Ok((address, stop, server))
}

fn assert_wire_response(response: &[u8]) -> Result<()> {
    assert!(response.starts_with(b"HTTP/1.1 200 OK"));
    let body = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .context("wire response headers")?
        + 4;
    let envelope = WireEnvelopeV2::decode(&response[body..])?;
    assert_eq!(envelope.schema().as_str(), "hepta.runtime.status.v1");
    let status: serde_json::Value = serde_json::from_slice(envelope.payload())?;
    assert_eq!(status["authority"]["outbound"], false);
    Ok(())
}

#[tokio::test]
async fn http_accept_saturated_listener_defers_next_request_then_reuses_reaped_slot() -> Result<()> {
    let (address, mut stop, server) = start().await?;
    let mut first = TcpStream::connect(address).await?;
    first.write_all(&REQUEST[..1]).await?;
    let mut second = TcpStream::connect(address).await?;
    second.write_all(REQUEST).await?;
    let mut second_response = Vec::new();
    assert!(
        timeout(
            Duration::from_millis(100),
            second.read_to_end(&mut second_response),
        )
        .await
        .is_err()
    );
    assert!(second_response.is_empty());
    first.write_all(&REQUEST[1..]).await?;
    let mut first_response = Vec::new();
    timeout(TEST_DEADLINE, first.read_to_end(&mut first_response)).await??;
    assert_wire_response(&first_response)?;
    timeout(TEST_DEADLINE, second.read_to_end(&mut second_response)).await??;
    assert_wire_response(&second_response)?;
    stop.write_all(&[1]).await?;
    timeout(TEST_DEADLINE, server).await???;
    Ok(())
}

#[tokio::test]
async fn http_accept_shutdown_reaps_stalled_connections_without_waiting_for_header_timeout() -> Result<()> {
    let (address, mut stop, server) = start().await?;
    let mut client = TcpStream::connect(address).await?;
    client.write_all(&REQUEST[..1]).await?;
    stop.write_all(&[1]).await?;
    timeout(TEST_DEADLINE, server).await???;
    let mut response = Vec::new();
    // Dropping a socket with unread bytes may yield either EOF or reset.
    let _ = timeout(TEST_DEADLINE, client.read_to_end(&mut response)).await?;
    assert!(response.is_empty());
    Ok(())
}

#[tokio::test]
async fn http_accept_malformed_request_releases_its_slot_for_the_normal_wire_route() -> Result<()> {
    let (address, mut stop, server) = start().await?;
    let mut malformed = TcpStream::connect(address).await?;
    malformed.write_all(b"\xff\r\n\r\n").await?;
    let mut rejected = Vec::new();
    let _ = timeout(TEST_DEADLINE, malformed.read_to_end(&mut rejected)).await?;
    assert!(rejected.is_empty());
    let mut valid = TcpStream::connect(address).await?;
    valid.write_all(REQUEST).await?;
    let mut response = Vec::new();
    timeout(TEST_DEADLINE, valid.read_to_end(&mut response)).await??;
    assert_wire_response(&response)?;
    stop.write_all(&[1]).await?;
    timeout(TEST_DEADLINE, server).await???;
    Ok(())
}

#[tokio::test]
async fn http_accept_private_limit_cannot_disable_or_exceed_the_connection_ceiling() -> Result<()> {
    for maximum in [0, connection_loop::MAX_CONNECTIONS + 1] {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let result = timeout(
            TEST_DEADLINE,
            connection_loop::serve(listener, runtime()?, maximum, std::future::pending()),
        )
        .await?;
        assert!(result.is_err());
    }
    Ok(())
}
