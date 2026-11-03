use super::*;
use pretty_assertions::assert_eq;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::thread;
fn credentials() -> MemoryCredentials {
    MemoryCredentials::new("session=test".into(), "csrf-test".into()).unwrap()
}
fn server(status: &str, body: &str) -> (String, thread::JoinHandle<String>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let reply = format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let handle = thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let mut bytes = Vec::new();
        let mut chunk = [0; 4096];
        loop {
            let count = socket.read(&mut chunk).unwrap();
            bytes.extend_from_slice(&chunk[..count]);
            if let Some(split) = bytes.windows(4).position(|window| window == b"\r\n\r\n") {
                let text = String::from_utf8_lossy(&bytes[..split]);
                let len = text
                    .lines()
                    .find_map(|line| {
                        line.to_lowercase()
                            .strip_prefix("content-length: ")
                            .map(str::to_owned)
                    })
                    .map_or(0, |len| len.parse::<usize>().unwrap());
                if bytes.len() >= split + 4 + len {
                    break;
                }
            }
        }
        socket.write_all(reply.as_bytes()).unwrap();
        String::from_utf8(bytes).unwrap()
    });
    (format!("http://{address}/api/ui-control/v1/"), handle)
}
#[test]
fn real_http_binds_same_origin_credentials_csrf_and_exact_operation_id() {
    let (base, server) = server("200 OK", "{\"accepted\":true}");
    let mut transport = HttpTransport::new(&base, credentials(), Duration::from_secs(2)).unwrap();
    assert_eq!(
        transport
            .request("runtime/stop", &json!({"operationId":"op.1"}))
            .unwrap(),
        json!({"accepted":true})
    );
    let sent = server.join().unwrap().to_lowercase();
    assert!(sent.starts_with("post /api/ui-control/v1/operations http/1.1"));
    assert!(sent.contains("x-hepta-request-id: op.1"));
    assert!(sent.contains("x-hepta-csrf-token: csrf-test"));
    assert!(sent.contains("cookie: session=test"));
}
#[test]
fn rejects_insecure_remote_redirects_unknown_methods_and_header_injection() {
    assert!(
        HttpTransport::new(
            "http://example.com/api/",
            credentials(),
            Duration::from_secs(1)
        )
        .is_err()
    );
    assert!(MemoryCredentials::new("cookie\r\nx: evil".into(), "csrf".into()).is_err());
    let mut transport = HttpTransport::new(
        "https://example.com/api/",
        credentials(),
        Duration::from_secs(1),
    )
    .unwrap();
    assert_eq!(
        transport
            .request("runtime/stop", &json!({"method":"runtime/start"}))
            .unwrap_err()
            .request_dispatched,
        Some(false)
    );
    let (base, server) = server("302 Found", "{}");
    let mut transport = HttpTransport::new(&base, credentials(), Duration::from_secs(1)).unwrap();
    assert_eq!(
        transport.connect(&json!({})).unwrap_err().code,
        ErrorCode::Transport
    );
    server.join().unwrap();
}
#[test]
fn duplicate_response_keys_and_oversize_requests_fail_closed() {
    let (base, server) = server("200 OK", "{\"accepted\":false,\"accepted\":true}");
    let mut transport = HttpTransport::new(&base, credentials(), Duration::from_secs(1)).unwrap();
    assert_eq!(
        transport.connect(&json!({})).unwrap_err().code,
        ErrorCode::Transport
    );
    server.join().unwrap();
    assert_eq!(
        transport
            .request(
                "runtime/stop",
                &json!({"reason":"a".repeat(MAX_REQUEST_BYTES)})
            )
            .unwrap_err()
            .request_dispatched,
        Some(false)
    );
}
