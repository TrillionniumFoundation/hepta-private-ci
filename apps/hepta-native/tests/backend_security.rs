use hepta_native::backend::{BackendAdapter, LoopbackGatewayBackend};
use hepta_native::model::EndpointManifest;
use std::io::{Read as _, Write as _};
use std::net::TcpListener;
const KEY: &str = "test-keyring-secret-never-sent-to-listeners";

#[test]
fn rogue_loopback_listener_gets_no_secret_and_cannot_authenticate_health() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut wire = Vec::new();
        let mut buffer = [0; 1024];
        loop {
            let n = stream.read(&mut buffer).unwrap();
            if n == 0 {
                break;
            }
            wire.extend_from_slice(&buffer[..n]);
            if wire.windows(4).any(|w| w == b"\r\n\r\n") {
                break;
            }
        }
        let body = r#"{"product":"hepta","status":"ok","native_auth":"keyring_mac_v2","native_protocol_version":2}"#;
        write!(
            stream,
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        )
        .unwrap();
        String::from_utf8(wire).unwrap()
    });
    let manifest = EndpointManifest {
        endpoint_id: "test.endpoint".into(),
        address: address.to_string(),
        manifest_digest: "1".repeat(64),
        protocol_version: 2,
    };
    let mut backend = LoopbackGatewayBackend::new(address, KEY.into()).unwrap();
    assert!(
        backend
            .connect(&manifest)
            .unwrap_err()
            .to_string()
            .contains("no server proof")
    );
    let request = server.join().unwrap();
    assert!(!request.contains(KEY));
    assert!(!request.contains("Authorization: Bearer"));
    assert!(backend.runtime_status().is_err());
}
