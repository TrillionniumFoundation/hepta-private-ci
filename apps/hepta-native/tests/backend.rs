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
        protocol_version: 1,
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
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
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
        r#"{"product":"hepta","status":"ok","native_auth":"keyring_bearer_v1"}"#,
    );
    let mut backend = LoopbackGatewayBackend::new(address, TOKEN.to_owned()).unwrap();
    let session = backend.connect(&manifest(address)).unwrap();
    assert_eq!(session.endpoint_id, "runtime.local");
    let request = server.join().unwrap();
    assert!(request.contains(&format!("Authorization: Bearer {TOKEN}\r\n")));
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
