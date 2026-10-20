use super::*;

#[test]
fn expected_loopback_host_and_same_origin_are_admitted() {
    let address: SocketAddr = "127.0.0.1:7373".parse().expect("fixture");
    for host in ["127.0.0.1:7373", "localhost:7373", "LOCALHOST:7373"] {
        let request = format!(
            "GET /api/hepta/runtime HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\n\r\n"
        );
        assert!(allowed(request.as_bytes(), address));
    }
    assert!(allowed(b"GET /healthz HTTP/1.0\r\n\r\n", address));
    assert!(allowed(
        b"GET / HTTP/1.1\r\nHost: [::1]:7373\r\nOrigin: http://[::1]:7373\r\n\r\n",
        "[::1]:7373".parse().expect("fixture")
    ));
}

#[test]
fn rebinding_cross_origin_ambiguous_and_opaque_hosts_are_rejected() {
    let address: SocketAddr = "127.0.0.1:7373".parse().expect("fixture");
    for headers in [
        "Host: attacker.example:7373",
        "Host: 127.0.0.2:7373",
        "Host: localhost",
        "Host: localhost:0",
        "Host: localhost:+7373",
        "Host: localhost:7373\r\nHost: localhost:7373",
        "Host: localhost:7373\r\nOrigin: https://attacker.example",
        "Host: localhost:7373\r\nOrigin: null",
        "Host: localhost:7373\r\nOrigin: http://127.0.0.1:7373",
        "Host: localhost:7373\r\nOrigin: http://localhost:7373/",
        "Host: localhost:7373\r\nOrigin: http://localhost:7373\r\nOrigin: http://localhost:7373",
        "Host: localhost:7373\r\n Origin: http://attacker.example",
        "Host : localhost:7373",
        "",
        "Host: localhost:7373\nOrigin: http://attacker.example",
    ] {
        let request = format!("GET /api/hepta/runtime HTTP/1.1\r\n{headers}\r\n\r\n");
        assert!(!allowed(request.as_bytes(), address), "{headers:?}");
    }
}
