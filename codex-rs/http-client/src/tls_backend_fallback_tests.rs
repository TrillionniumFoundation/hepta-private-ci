use std::io;

use pretty_assertions::assert_eq;

use super::MAX_CACHED_RUSTLS_DESTINATIONS;
use super::RustlsClientCache;
use super::SCHANNEL_PROTOCOL_VERSION_ERROR;
use super::has_retryable_tls_error;
use super::has_windows_status;
use crate::HttpClientBuilder;
use crate::OutboundProxyRoute;

#[derive(Debug)]
struct NegotiationWithSource(io::Error);

impl std::fmt::Display for NegotiationWithSource {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("native protocol error 0x80090302")
    }
}

impl std::error::Error for NegotiationWithSource {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.0)
    }
}

#[test]
fn localized_certificate_status_in_source_dominates_negotiation_text() {
    for code in [
        0x8009_0322_u32,
        0x8009_0325,
        0x8009_0327,
        0x8009_0328,
        0x8009_2010,
        0x8009_2012,
        0x8009_2013,
        0x800B_0101,
        0x800B_0109,
        0x800B_010A,
        0x800B_010C,
        0x800B_010E,
        0x800B_010F,
        0x800B_0110,
    ] {
        let error = NegotiationWithSource(io::Error::from_raw_os_error(/*code*/ code as i32));
        assert!(
            !has_retryable_tls_error(&error),
            "certificate status {code:#010x}"
        );
    }
}

#[test]
fn generic_illegal_message_status_is_not_native_tls_provenance() {
    for error in [
        io::Error::from_raw_os_error(/*code*/ 0x8009_0326_u32 as i32),
        io::Error::other(
            "The message received was unexpected or badly formatted. (os error -2146893018)",
        ),
        io::Error::other("Schannel status 0x80090326"),
    ] {
        assert!(!has_retryable_tls_error(&error));
    }
}

#[test]
fn native_status_text_matches_exact_observed_code_only() {
    for (text, expected) in [
        (
            "The message received was unexpected or badly formatted. (os error -2146893018)",
            true,
        ),
        ("Schannel status 0x80090326", true),
        ("Schannel status 0x800903260", false),
        ("Schannel status 0x80090327", false),
        (
            "The message received was unexpected or badly formatted.",
            false,
        ),
    ] {
        let error = io::Error::other(text);
        assert_eq!(
            has_windows_status(&error, text, /*code*/ 0x8009_0326_u32 as i32),
            expected
        );
    }
}

#[test]
fn recognizes_platform_specific_tls_protocol_negotiation_failures() {
    let errors = [
        ("client error (Connect): bad protocol version", true),
        ("BAD PROTOCOL VERSION", true),
        (
            "error:0A00042E:SSL routines:ssl3_read_bytes:tlsv1 alert protocol version",
            true,
        ),
        ("TLSV1 ALERT PROTOCOL VERSION", true),
        (
            "The function requested is not supported. (os error -2146893054)",
            true,
        ),
        ("Schannel protocol error 0x80090302", true),
        ("SCHANNEL PROTOCOL ERROR 0X80090302", true),
        ("certificate validation failed: bad protocol version", false),
        ("bad protocol version: certificate has expired", false),
        (
            "certificate validation failed: tlsv1 alert protocol version",
            false,
        ),
        (
            "tlsv1 alert protocol version: certificate has expired",
            false,
        ),
        (
            "certificate validation failed (os error -2146893054)",
            false,
        ),
        ("certificate validation failed: 0x80090302", false),
        ("unknown issuer", false),
        ("self-signed certificate", false),
        ("hostname mismatch", false),
        ("connection refused", false),
        ("connection reset", false),
        ("dns lookup failed", false),
        ("tls handshake failed", false),
        ("unsupported protocol", false),
        ("wrong version number", false),
        ("The function requested is not supported.", false),
        (
            "The client and server cannot communicate. (os error -2146893007)",
            false,
        ),
        ("operation timed out", false),
        ("407 Proxy Authentication Required", false),
    ];

    for (message, expected) in errors {
        let error = io::Error::other(message);
        assert_eq!(has_retryable_tls_error(&error), expected, "{message}");
    }
}

#[test]
fn recognizes_schannel_protocol_version_error_codes() {
    let protocol_error = io::Error::from_raw_os_error(SCHANNEL_PROTOCOL_VERSION_ERROR);
    let another_schannel_error = io::Error::from_raw_os_error(/*code*/ -2_146_893_007);

    assert_eq!(
        (
            has_retryable_tls_error(&protocol_error),
            has_retryable_tls_error(&another_schannel_error),
        ),
        (true, false)
    );
}

#[test]
fn certificate_errors_in_an_error_source_never_enable_fallback() {
    for message in [
        "certificate verification failed: bad protocol version",
        "certificate verification failed: tlsv1 alert protocol version",
        "certificate verification failed (os error -2146893054)",
        "certificate verification failed: 0x80090302",
    ] {
        let error = io::Error::other(io::Error::other(message));

        assert!(!has_retryable_tls_error(&error), "{message}");
    }
}

#[test]
fn rustls_fallback_decisions_are_scoped_to_origin_and_outbound_route() {
    let cache = RustlsClientCache::default();
    let destination = reqwest::Url::parse("https://mcp.example.com/first").expect("valid URL");
    let same_origin = reqwest::Url::parse("https://mcp.example.com/second").expect("valid URL");
    let another_host = reqwest::Url::parse("https://another.example.com/first").expect("valid URL");
    let another_port =
        reqwest::Url::parse("https://mcp.example.com:8443/first").expect("valid URL");
    let insecure = reqwest::Url::parse("http://mcp.example.com/first").expect("valid URL");
    let direct = OutboundProxyRoute::Direct;
    let proxy = OutboundProxyRoute::Proxy {
        url: "http://proxy.example.com".to_string(),
        no_proxy: None,
    };

    let client = HttpClientBuilder::new()
        .with_rustls_tls()
        .build_direct()
        .expect("rustls client should build without proxy autodiscovery");
    cache.remember(&destination, &direct, client);

    assert_eq!(
        [
            cache.requires_rustls(&destination, &direct),
            cache.requires_rustls(&same_origin, &direct),
            cache.requires_rustls(&another_host, &direct),
            cache.requires_rustls(&another_port, &direct),
            cache.requires_rustls(&destination, &proxy),
            cache.requires_rustls(&insecure, &direct),
        ],
        [true, true, false, false, false, false]
    );
}

#[test]
fn cached_rustls_clients_are_reused_for_the_same_outbound_route() {
    let cache = RustlsClientCache::default();
    let first_destination =
        reqwest::Url::parse("https://first.example.com").expect("valid first URL");
    let second_destination =
        reqwest::Url::parse("https://second.example.com").expect("valid second URL");
    let direct = OutboundProxyRoute::Direct;
    let client = HttpClientBuilder::new()
        .with_rustls_tls()
        .build_direct()
        .expect("rustls client should build without proxy autodiscovery");

    cache.remember(&first_destination, &direct, client.clone());
    cache.remember(&second_destination, &direct, client);

    assert_eq!(
        (
            cache.requires_rustls(&first_destination, &direct),
            cache.requires_rustls(&second_destination, &direct),
            cache.client_for_route(&direct).is_some(),
            cache
                .state
                .lock()
                .expect("rustls client cache lock")
                .clients
                .len(),
        ),
        (true, true, true, 1)
    );
}

#[test]
fn cached_rustls_destinations_remain_bounded_while_sharing_a_route_client() {
    let cache = RustlsClientCache::default();
    let client = HttpClientBuilder::new()
        .with_rustls_tls()
        .build_direct()
        .expect("rustls client should build without proxy autodiscovery");

    for index in 0..=MAX_CACHED_RUSTLS_DESTINATIONS {
        let destination =
            reqwest::Url::parse(&format!("https://mcp-{index}.example.com")).expect("valid URL");
        cache.remember(&destination, &OutboundProxyRoute::Direct, client.clone());
    }

    let state = cache.state.lock().expect("rustls client cache lock");
    assert_eq!(
        (state.destinations.len(), state.clients.len()),
        (MAX_CACHED_RUSTLS_DESTINATIONS, 1)
    );
}

#[test]
fn evicting_a_destination_removes_its_unshared_route_client() {
    let cache = RustlsClientCache::default();
    let client = HttpClientBuilder::new()
        .with_rustls_tls()
        .build_direct()
        .expect("rustls client should build without proxy autodiscovery");

    for index in 0..=MAX_CACHED_RUSTLS_DESTINATIONS {
        let destination =
            reqwest::Url::parse(&format!("https://mcp-{index}.example.com")).expect("valid URL");
        let route = OutboundProxyRoute::Proxy {
            url: format!("http://proxy-{index}.example.com"),
            no_proxy: None,
        };
        cache.remember(&destination, &route, client.clone());
    }

    let state = cache.state.lock().expect("rustls client cache lock");
    assert_eq!(
        (
            state.destinations.len(),
            state.clients.len(),
            state
                .destinations
                .iter()
                .all(|destination| state.clients.contains_key(&destination.route)),
        ),
        (
            MAX_CACHED_RUSTLS_DESTINATIONS,
            MAX_CACHED_RUSTLS_DESTINATIONS,
            true,
        )
    );
}

#[test]
fn actual_native_tls_certificate_rejection_retains_its_denial() {
    let (url, attempts, stop) =
        crate::route_aware_tls_fixture::spawn_certificate_rejection_server().unwrap();
    let url = reqwest::Url::parse(&url).unwrap();
    let stream = std::net::TcpStream::connect(("127.0.0.1", url.port().unwrap())).unwrap();
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(/*secs*/ 2)))
        .unwrap();
    stream
        .set_write_timeout(Some(std::time::Duration::from_secs(/*secs*/ 2)))
        .unwrap();
    let error = native_tls::TlsConnector::new()
        .unwrap()
        .connect("127.0.0.1", stream)
        .expect_err("native certificate verification must fail");
    let native_tls::HandshakeError::Failure(error) = error else {
        panic!("blocking native handshake must complete");
    };
    eprintln!("TLS_FIXTURE_NATIVE_CERTIFICATE {error:?}");
    let _ = stop.send(());
    let message = error.to_string().to_ascii_lowercase();
    assert!(
        message.contains("certificate")
            || message.contains("untrusted")
            || message.contains("-2146893019")
            || message.contains("-2146762487"),
        "real native certificate rejection: {error:?}"
    );
    assert!(
        !has_retryable_tls_error(&error),
        "native certificate failure must not fall back: {error:?}"
    );
    assert_eq!(attempts.recv().unwrap().unwrap(), 1);
}

#[test]
fn actual_native_tls_protocol_failure_retains_backend_provenance() {
    use std::io::Write;
    let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(/*secs*/ 2);
        crate::route_aware_tls_fixture::read_complete_client_hello(&mut stream, deadline).unwrap();
        stream
            .set_write_timeout(Some(std::time::Duration::from_secs(/*secs*/ 2)))
            .unwrap();
        stream.write_all(&[21, 3, 3, 0, 2, 2, 70]).unwrap();
        stream.flush().unwrap();
    });
    let stream = std::net::TcpStream::connect(address).unwrap();
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(/*secs*/ 2)))
        .unwrap();
    stream
        .set_write_timeout(Some(std::time::Duration::from_secs(/*secs*/ 2)))
        .unwrap();
    let error = native_tls::TlsConnector::new()
        .unwrap()
        .connect("127.0.0.1", stream)
        .expect_err("native protocol alert must fail");
    let native_tls::HandshakeError::Failure(error) = error else {
        panic!("blocking native handshake must complete");
    };
    server.join().unwrap();
    eprintln!("TLS_FIXTURE_NATIVE_PROTOCOL {error:?}");
    assert!(
        has_retryable_tls_error(&error),
        "real native backend error must retain its negotiation classification: {error:?}"
    );
}
