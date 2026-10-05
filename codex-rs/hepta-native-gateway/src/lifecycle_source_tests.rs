use std::os::unix::fs::MetadataExt;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::native_gateway::lifecycle::NATIVE_GATEWAY_LIFECYCLE_PATH;
use codex_hepta_supervisor::SupervisordPayload;
use codex_hepta_supervisor::SupervisordResponse;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

use super::*;

fn request() -> SupervisorControllerRequest {
    serde_json::from_value(serde_json::json!({
        "schema_version":1,"request_id":71,"method":{"type":"stop","fence":{
            "agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
            "supervisor_epoch":"018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12",
            "lifecycle":"running","lifecycle_generation":7,"spawn_generation":5,"runtime_generation":7,
            "current_release":"agentd-v1","previous_release":null,"release_change_pending":false,"state_digest":"a".repeat(64)
        }}})).unwrap()
}

fn frame(proof: &NativeGatewayLifecycleRequestV2, body: &[u8]) -> Vec<u8> {
    let mut frame = format!("POST {NATIVE_GATEWAY_LIFECYCLE_PATH} HTTP/1.1\r\nAuthorization: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n", proof.header_value(), body.len()).into_bytes();
    frame.extend_from_slice(body);
    frame
}

async fn http(address: std::net::SocketAddr, frame: &[u8]) -> Result<Vec<u8>> {
    let mut stream = tokio::net::TcpStream::connect(address).await?;
    stream.write_all(frame).await?;
    stream.shutdown().await?;
    let mut response = Vec::new();
    stream.read_to_end(&mut response).await?;
    Ok(response)
}

#[tokio::test]
async fn lifecycle_actual_uds_mac_http_preserves_original_fence_and_rejects_replay_and_substitution()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("ctl");
    let listener = tokio::net::UnixListener::bind(&path)?;
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&calls);
    let expected = request();
    let original = expected.clone();
    let owner = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        let (reader, mut writer) = stream.into_split();
        let mut line = String::new();
        tokio::io::BufReader::new(reader)
            .read_line(&mut line)
            .await?;
        assert_eq!(
            serde_json::from_str::<SupervisorControllerRequest>(&line)?,
            original
        );
        observed.fetch_add(1, Ordering::SeqCst);
        let response = SupervisordResponse {
            schema_version: 2,
            request_id: original.request_id,
            payload: SupervisordPayload::Error {
                code: "stale_control_fence".into(),
                message: "refresh".into(),
                actual: None,
            },
        };
        let mut bytes = serde_json::to_vec(&response)?;
        bytes.push(b'\n');
        writer.write_all(&bytes).await?;
        Ok::<_, anyhow::Error>(())
    });
    let auth = Arc::new(GatewayAuth::new("r".repeat(64))?);
    let key = "c".repeat(64);
    let source = Arc::new(LifecycleSource::with_capability(
        path,
        std::fs::metadata(directory.path())?.uid(),
        key.clone(),
        &auth,
    )?);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let server_auth = Arc::clone(&auth);
    let gateway = tokio::spawn(async move {
        for _ in 0..4 {
            let (mut stream, _) = listener.accept().await?;
            let bytes = crate::lifecycle_http::read(&mut stream).await?;
            let response = source
                .route(crate::lifecycle_http::parse(&bytes)?, &server_auth)
                .await?;
            stream.write_all(&response).await?;
            stream.shutdown().await?;
        }
        Ok::<_, anyhow::Error>(())
    });
    let body = serde_json::to_vec(&expected)?;
    let proof = NativeGatewayLifecycleRequestV2::sign(
        key.as_bytes(),
        "POST",
        NATIVE_GATEWAY_LIFECYCLE_PATH,
        NativeGatewayLifecycleOperationV2::Stop,
        &body,
        [5; 32],
        crate::native_mac::now_unix_ms()?,
        auth.server_incarnation,
    )?;
    let response = http(address, &frame(&proof, &body)).await?;
    let (status, split) = crate::native_mac::response_parts(&response)?;
    assert_eq!(status, 200);
    let headers = std::str::from_utf8(&response[..split])?;
    let tag = headers
        .lines()
        .find_map(|line| line.strip_prefix("X-Hepta-Response-MAC: "))
        .context("response MAC")?;
    proof.verify_response(key.as_bytes(), status, &response[split + 4..], tag)?;
    assert!(
        proof
            .verify_response(key.as_bytes(), status, b"foreign", tag)
            .is_err()
    );
    assert!(
        serde_json::from_slice::<serde_json::Value>(&response[split + 4..])?["code"]
            == "stale_control_fence"
    );
    assert_eq!(
        crate::native_mac::response_parts(&http(address, &frame(&proof, &body)).await?)?.0,
        401
    );
    let mut changed = expected;
    changed.request_id = 72;
    assert_eq!(
        crate::native_mac::response_parts(
            &http(address, &frame(&proof, &serde_json::to_vec(&changed)?)).await?
        )?
        .0,
        401
    );
    let read_key_proof = NativeGatewayLifecycleRequestV2::sign(
        auth.bearer_token.as_bytes(),
        "POST",
        NATIVE_GATEWAY_LIFECYCLE_PATH,
        NativeGatewayLifecycleOperationV2::Stop,
        &body,
        [6; 32],
        crate::native_mac::now_unix_ms()?,
        auth.server_incarnation,
    )?;
    assert_eq!(
        crate::native_mac::response_parts(&http(address, &frame(&read_key_proof, &body)).await?)?.0,
        401
    );
    gateway.await??;
    owner.await??;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[test]
fn lifecycle_rejects_read_capability_reuse() -> Result<()> {
    let auth = GatewayAuth::new("r".repeat(64))?;
    assert!(
        LifecycleSource::with_capability("/tmp/unused".into(), 0, "r".repeat(64), &auth).is_err()
    );
    Ok(())
}
