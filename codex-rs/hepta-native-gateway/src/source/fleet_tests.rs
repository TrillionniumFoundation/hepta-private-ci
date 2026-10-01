use std::os::unix::fs::MetadataExt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::native_gateway::NativeGatewayRequestV2;
use codex_hepta_supervisor::RobrixSupervisordRequest;
use codex_hepta_supervisor::RobrixSupervisordResponse;
use codex_hepta_supervisor::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use tokio::io::AsyncReadExt;
use tokio::net::TcpListener;
use tokio::net::UnixListener;

use super::*;

const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";

fn health(epoch: &str) -> RobrixSupervisordPayload {
    serde_json::from_value(serde_json::json!({
        "type": "health", "ready": false, "supervisor_epoch": epoch,
        "process_id": std::process::id(), "registered_agents": 1, "observed_faults": 2,
    }))
    .unwrap()
}

fn roster() -> RobrixSupervisordPayload {
    let agent = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
    let release = "agentd-real-owner";
    serde_json::from_value(serde_json::json!({
        "type": "roster", "agents": [{
            "agent_id": agent, "lifecycle": "failed", "lifecycle_generation": 9,
            "active": false, "healthy": false, "process_id": null,
            "spawn_generation": null, "runtime_generation": null,
            "current_release": release, "previous_release": null, "release_change_pending": false,
            "control_fence": {"agent_id": agent, "supervisor_epoch": EPOCH,
                "lifecycle": "failed", "lifecycle_generation": 9,
                "spawn_generation": null, "runtime_generation": null,
                "current_release": release, "previous_release": null, "release_change_pending": false,
                "state_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
            "matrix": {"configured": false, "active": false, "healthy": false,
                "degraded": false, "process_id": null, "attached_agent_generation": null,
                "binding_revision": null, "restart_attempt": 0, "last_error": null},
        }],
    })).unwrap()
}

async fn observer(
    path: &std::path::Path,
    payloads: Vec<RobrixSupervisordPayload>,
) -> tokio::task::JoinHandle<Result<()>> {
    let listener = UnixListener::bind(path).unwrap();
    tokio::spawn(async move {
        for payload in payloads {
            let (mut stream, _) = listener.accept().await?;
            let mut bytes = Vec::new();
            stream.read_to_end(&mut bytes).await?;
            let request: RobrixSupervisordRequest = serde_json::from_slice(&bytes)?;
            request.validate()?;
            assert!(matches!(
                request.method,
                RobrixSupervisordMethod::Health | RobrixSupervisordMethod::Roster { .. }
            ));
            let response = RobrixSupervisordResponse {
                schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                payload,
            };
            let mut bytes = serde_json::to_vec(&response)?;
            bytes.push(b'\n');
            stream.write_all(&bytes).await?;
            stream.shutdown().await?;
        }
        Ok(())
    })
}

fn request(auth: &GatewayAuth, nonce: u8) -> (Vec<u8>, NativeGatewayRequestV2) {
    let proof = NativeGatewayRequestV2::sign(
        auth.bearer_token.as_bytes(),
        "/api/hepta/runtime",
        [nonce; 32],
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64,
        auth.server_incarnation,
    )
    .unwrap();
    let wire = format!(
        "GET /api/hepta/runtime HTTP/1.1\r\nHost: localhost\r\nAuthorization: {}\r\n\r\n",
        proof.header_value()
    );
    assert!(!wire.contains(auth.bearer_token.as_str()));
    (wire.into_bytes(), proof)
}

fn verified_body<'a>(
    wire: &'a [u8],
    proof: &NativeGatewayRequestV2,
    auth: &GatewayAuth,
    status: u16,
) -> &'a [u8] {
    let split = wire.windows(4).position(|v| v == b"\r\n\r\n").unwrap();
    let header = std::str::from_utf8(&wire[..split]).unwrap();
    let tag = header
        .lines()
        .find_map(|line| line.strip_prefix("X-Hepta-Response-MAC: "))
        .unwrap();
    let body = &wire[split + 4..];
    proof
        .verify_response(auth.bearer_token.as_bytes(), status, body, tag)
        .unwrap();
    assert!(
        proof
            .verify_response(auth.bearer_token.as_bytes(), status, b"forged", tag)
            .is_err()
    );
    body
}

#[tokio::test]
async fn real_uds_to_mac_http_retains_failed_owner_and_never_opens_sqlite() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("observer");
    let uid = temp.path().metadata()?.uid();
    let peer = observer(&path, vec![health(EPOCH), roster(), health(EPOCH)]).await;
    let root = codex_hepta_paths::HeptaStateRoot::parse(temp.path().join("nonexistent-state"))?;
    let source = Arc::new(
        crate::source::RuntimeSource::open(
            root,
            Some(ObserverOptions {
                socket: path,
                owner_uid: uid,
            }),
        )
        .await?,
    );
    let auth = crate::fixture_gateway_auth();
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let server_auth = Arc::clone(&auth);
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        source.serve(stream, server_auth).await
    });
    let (wire, proof) = request(&auth, /*nonce*/ 71);
    let mut client = TcpStream::connect(address).await?;
    client.write_all(&wire).await?;
    let mut response = Vec::new();
    client.read_to_end(&mut response).await?;
    let body: serde_json::Value =
        serde_json::from_slice(verified_body(&response, &proof, &auth, /*status*/ 200))?;
    assert_eq!(body["schema"], "hepta_fleet_observation_v1");
    assert_eq!(body["health"]["supervisor_epoch"], EPOCH);
    assert_eq!(body["health"]["ready"], false);
    assert_eq!(body["agents"][0]["lifecycle"], "failed");
    assert_eq!(body["agents"][0]["lifecycle_generation"], 9);
    assert_eq!(body["observation_revision"], 1);
    assert!(!temp.path().join("nonexistent-state").exists());
    server.await??;
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn owner_change_is_signed_unavailable_then_fresh_read_uses_the_next_revision() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("observer");
    let peer = observer(
        &path,
        vec![
            health(EPOCH),
            roster(),
            health("018f4f72-5f8f-4cc1-8f55-df9fb3aa2c13"),
            health(EPOCH),
            roster(),
            health(EPOCH),
        ],
    )
    .await;
    let source = FleetSource::new(ObserverOptions {
        socket: path,
        owner_uid: temp.path().metadata()?.uid(),
    })?;
    let auth = crate::fixture_gateway_auth();
    let (wire, proof) = request(&auth, /*nonce*/ 72);
    let first = source.route(&wire, &auth).await?;
    let body = verified_body(&first, &proof, &auth, /*status*/ 503);
    assert!(!body.windows(7).any(|bytes| bytes == b"agents\""));
    // Replaying even a failed read cannot enter the observer again.
    assert!(
        source
            .route(&wire, &auth)
            .await?
            .starts_with(b"HTTP/1.1 401")
    );
    let (fresh, proof) = request(&auth, /*nonce*/ 73);
    let second = source.route(&fresh, &auth).await?;
    let body: serde_json::Value =
        serde_json::from_slice(verified_body(&second, &proof, &auth, /*status*/ 200))?;
    assert_eq!(body["observation_revision"], 1);
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn unavailable_or_foreign_peer_has_no_legacy_read_fallback() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("missing");
    let uid = temp.path().metadata()?.uid();
    let auth = crate::fixture_gateway_auth();
    let source = FleetSource::new(ObserverOptions {
        socket: path.clone(),
        owner_uid: uid,
    })?;
    let (wire, proof) = request(&auth, /*nonce*/ 74);
    let response = source.route(&wire, &auth).await?;
    verified_body(&response, &proof, &auth, /*status*/ 503);
    let listener = UnixListener::bind(&path)?;
    let peer = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).await?;
        assert!(bytes.is_empty());
        anyhow::Ok(())
    });
    let foreign = FleetSource::new(ObserverOptions {
        socket: path,
        owner_uid: uid.checked_add(/*rhs*/ 1).unwrap(),
    })?;
    let (wire, proof) = request(&auth, /*nonce*/ 75);
    let response = foreign.route(&wire, &auth).await?;
    verified_body(&response, &proof, &auth, /*status*/ 503);
    peer.await??;
    Ok(())
}
