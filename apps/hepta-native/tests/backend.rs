use std::io::Read as _;
use std::io::Write as _;
use std::net::TcpListener;
use std::thread;

use hepta_native::backend::BackendAdapter;
use hepta_native::backend::LoopbackGatewayBackend;
use hepta_native::model::EndpointManifest;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
const TOKEN: &str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

fn manifest(address: std::net::SocketAddr) -> EndpointManifest {
    EndpointManifest {
        endpoint_id: "runtime.local".to_owned(),
        address: address.to_string(),
        manifest_digest: D1.to_owned(),
        protocol_version: 2,
    }
}

fn serve_health(listener: TcpListener, body: &'static str) -> thread::JoinHandle<String> {
    thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = Vec::new();
        let mut buffer = [0_u8; 1024];
        loop {
            let read = stream.read(&mut buffer).unwrap();
            if read == 0 {
                break;
            }
            request.extend_from_slice(&buffer[..read]);
            if request.windows(4).any(|window| window == b"\r\n\r\n") {
                break;
            }
        }
        let request_text = String::from_utf8(request.clone()).unwrap();
        let header = request_text
            .lines()
            .find_map(|line| line.strip_prefix("Authorization: "))
            .unwrap();
        let proof =
            codex_hepta_contracts::native_gateway::NativeGatewayRequestV2::parse_header(header)
                .unwrap();
        let tag = proof
            .response_tag(TOKEN.as_bytes(), 200, body.as_bytes())
            .unwrap();
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nX-Hepta-Response-MAC: {tag}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        stream.write_all(response.as_bytes()).unwrap();
        String::from_utf8(request).unwrap()
    })
}

#[test]
fn authenticated_gateway_health_is_required() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = serve_health(
        listener,
        r#"{"product":"hepta","status":"ok","native_auth":"keyring_mac_v2","native_protocol_version":2,"native_incarnation":"2222222222222222222222222222222222222222222222222222222222222222"}"#,
    );
    let mut backend = LoopbackGatewayBackend::new(address, TOKEN.to_owned()).unwrap();
    let session = backend.connect(&manifest(address)).unwrap();
    assert_eq!(session.endpoint_id, "runtime.local");
    let request = server.join().unwrap();
    assert!(request.contains("Authorization: Hepta-MAC-V2 "));
    assert!(!request.contains(TOKEN));
}

#[test]
fn unauthenticated_legacy_gateway_is_rejected_by_product_shell() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = serve_health(
        listener,
        r#"{"product":"hepta","status":"ok","native_auth":"disabled"}"#,
    );
    let mut backend = LoopbackGatewayBackend::new(address, TOKEN.to_owned()).unwrap();
    let error = backend.connect(&manifest(address)).unwrap_err();
    assert!(error.to_string().contains("health identity"));
    let _ = server.join().unwrap();
}

#[test]
fn gateway_protocol_must_match_the_signed_manifest() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = serve_health(
        listener,
        r#"{"product":"hepta","status":"ok","native_auth":"keyring_mac_v2","native_protocol_version":3}"#,
    );
    let mut backend = LoopbackGatewayBackend::new(address, TOKEN.to_owned()).unwrap();
    let error = backend.connect(&manifest(address)).unwrap_err();
    assert!(error.to_string().contains("protocol version mismatch"));
    let _ = server.join().unwrap();
}

#[test]
fn gateway_protocol_identity_is_required() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = serve_health(
        listener,
        r#"{"product":"hepta","status":"ok","native_auth":"keyring_mac_v2"}"#,
    );
    let mut backend = LoopbackGatewayBackend::new(address, TOKEN.to_owned()).unwrap();
    let error = backend.connect(&manifest(address)).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("missing the native protocol version")
    );
    let _ = server.join().unwrap();
}

#[test]
fn each_authenticated_connection_gets_a_fresh_session_identity() {
    fn connect_once() -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = serve_health(
            listener,
            r#"{"product":"hepta","status":"ok","native_auth":"keyring_mac_v2","native_protocol_version":2,"native_incarnation":"2222222222222222222222222222222222222222222222222222222222222222"}"#,
        );
        let mut backend = LoopbackGatewayBackend::new(address, TOKEN.to_owned()).unwrap();
        let session_id = backend.connect(&manifest(address)).unwrap().session_id;
        let _ = server.join().unwrap();
        session_id
    }

    let first = connect_once();
    let second = connect_once();
    assert_ne!(first, second);
    assert!(first.starts_with("native."));
    assert_eq!(first.len(), "native.".len() + 64);
}

#[test]
fn stale_close_cannot_invalidate_a_reconnected_gateway() {
    const HEALTH: &str = r#"{"product":"hepta","status":"ok","native_auth":"keyring_mac_v2","native_protocol_version":2,"native_incarnation":"2222222222222222222222222222222222222222222222222222222222222222"}"#;
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let mut backend = LoopbackGatewayBackend::new(address, TOKEN.to_owned()).unwrap();
    let server = serve_health(listener.try_clone().unwrap(), HEALTH);
    let first = backend.connect(&manifest(address)).unwrap();
    server.join().unwrap();
    assert!(backend.connect(&manifest(address)).is_err());
    backend.close(&first).unwrap();
    backend.close(&first).unwrap();

    let server = serve_health(listener.try_clone().unwrap(), HEALTH);
    let current = backend.connect(&manifest(address)).unwrap();
    server.join().unwrap();
    assert!(backend.close(&first).is_err());
    let server = serve_health(listener, r#"{"state":{"runtime_snapshot_generation":1}}"#);
    assert_eq!(
        backend.runtime_status().unwrap().value,
        serde_json::json!({"state": {"runtime_snapshot_generation": 1}})
    );
    server.join().unwrap();
    backend.close(&current).unwrap();
    assert!(backend.runtime_status().is_err());
}
