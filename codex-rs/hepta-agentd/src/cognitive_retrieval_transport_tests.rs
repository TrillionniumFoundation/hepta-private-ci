//! Local framing/deadline tests, not external-owner persistence qualification.
use super::*;
use serde_json::json;
use std::net::TcpListener;

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000731").expect("owner")
}

fn response() -> serde_json::Value {
    json!({
        "schema": SCHEMA,
        "owner": owner().as_str(),
        "body_generation": 9,
        "authority_epoch": 7,
        "sequence": 1,
        "publication_digest": null,
        "expires_unix_ms": 1000,
        "challenge": hex(&[7_u8; 32]),
        "signature": hex(&[0_u8; 64])
    })
}

#[test]
fn canonical_frame_preserves_revocation_and_signature_bytes() {
    let body = serde_json::to_vec(&response()).expect("JSON");
    let result = decode(&body, &owner(), 9, [7; 32]).expect("frame");
    assert_eq!(
        result,
        MemoryRetrievalFrontierV1 {
            owner: owner(),
            body_generation: 9,
            authority_epoch: 7,
            sequence: 1,
            publication_digest: None,
            expires_unix_ms: 1000,
            challenge: [7; 32],
            signature: [0; 64],
        }
    );
}

#[test]
fn wrong_protocol_owner_generation_and_challenge_are_rejected() {
    for (key, value) in [
        ("schema", json!("another-service.v1")),
        ("owner", json!("00000000-0000-4000-8000-000000000732")),
        ("body_generation", json!(10)),
        ("challenge", json!(hex(&[8_u8; 32]))),
    ] {
        let mut value_to_decode = response();
        value_to_decode[key] = value;
        let body = serde_json::to_vec(&value_to_decode).expect("JSON");
        assert!(decode(&body, &owner(), 9, [7; 32]).is_err(), "{key}");
    }
}

#[test]
fn unknown_duplicate_and_trailing_fields_are_rejected() {
    let mut unknown = response();
    unknown["trusted"] = json!(true);
    assert!(
        decode(
            &serde_json::to_vec(&unknown).expect("JSON"),
            &owner(),
            9,
            [7; 32]
        )
        .is_err()
    );
    let body = serde_json::to_string(&response()).expect("JSON");
    let duplicate = body.replacen('{', "{\"sequence\":1,", 1);
    assert!(decode(duplicate.as_bytes(), &owner(), 9, [7; 32]).is_err());
    let trailing = format!("{body}{{}}");
    assert!(decode(trailing.as_bytes(), &owner(), 9, [7; 32]).is_err());
}

#[test]
fn noncanonical_hex_and_oversized_documents_are_rejected() {
    for value in ["ff".to_string(), "GG".repeat(64), "AA".repeat(64)] {
        let mut fixture = response();
        fixture["signature"] = json!(value);
        assert!(
            decode(
                &serde_json::to_vec(&fixture).expect("JSON"),
                &owner(),
                9,
                [7; 32]
            )
            .is_err()
        );
    }
    assert!(decode(&vec![b' '; MAX_FRAME_BYTES + 1], &owner(), 9, [7; 32]).is_err());
}

#[test]
fn endpoint_and_total_timeout_are_protected_configuration() {
    for endpoint in ["192.0.2.1:80", "0.0.0.0:80", "127.0.0.1:0"] {
        assert!(
            LoopbackFrontierClient::new(endpoint.parse().expect("address"), Duration::from_secs(1))
                .is_err()
        );
    }
    let address = "127.0.0.1:12345".parse().expect("address");
    for timeout in [
        Duration::ZERO,
        Duration::from_millis(9),
        Duration::from_secs(6),
    ] {
        assert!(LoopbackFrontierClient::new(address, timeout).is_err());
    }
}

#[test]
fn loopback_roundtrip_uses_length_framing_and_fresh_request_identity() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("listener");
    let endpoint = listener.local_addr().expect("address");
    let server = std::thread::spawn(move || {
        let (mut socket, _) = listener.accept().expect("accept");
        socket
            .set_read_timeout(Some(Duration::from_secs(2)))
            .expect("read timeout");
        socket
            .set_write_timeout(Some(Duration::from_secs(2)))
            .expect("write timeout");
        let mut header = [0; 4];
        socket.read_exact(&mut header).expect("header");
        let size = usize::try_from(u32::from_be_bytes(header)).expect("size");
        assert!(size <= MAX_FRAME_BYTES);
        let mut body = vec![0; size];
        socket.read_exact(&mut body).expect("body");
        let request: serde_json::Value = serde_json::from_slice(&body).expect("request");
        assert_eq!(
            request,
            json!({
                "schema": SCHEMA, "owner": owner().as_str(),
                "body_generation": 9, "challenge": hex(&[7_u8; 32])
            })
        );
        let reply = serde_json::to_vec(&response()).expect("response");
        socket
            .write_all(&u32::try_from(reply.len()).expect("size").to_be_bytes())
            .expect("header");
        socket.write_all(&reply).expect("reply");
    });
    let client = LoopbackFrontierClient::new(endpoint, Duration::from_secs(2)).expect("client");
    let result = client.observe(&owner(), 9, [7; 32]);
    server.join().expect("server");
    assert_eq!(result.expect("response").publication_digest, None);
}

#[test]
fn oversized_wire_frame_is_rejected_before_allocating_its_body() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("listener");
    let endpoint = listener.local_addr().expect("address");
    let server = std::thread::spawn(move || {
        let (mut socket, _) = listener.accept().expect("accept");
        socket.write_all(&u32::MAX.to_be_bytes()).expect("header");
        std::thread::sleep(Duration::from_millis(100));
    });
    let client = LoopbackFrontierClient::new(endpoint, Duration::from_secs(1)).expect("client");
    let result = client.observe(&owner(), 9, [7; 32]);
    server.join().expect("server");
    assert!(result.is_err());
}

#[test]
fn silent_owner_cannot_hold_retrieval_past_the_total_deadline() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("listener");
    let endpoint = listener.local_addr().expect("address");
    let server = std::thread::spawn(move || {
        let (_socket, _) = listener.accept().expect("accept");
        std::thread::sleep(Duration::from_millis(300));
    });
    let client = LoopbackFrontierClient::new(endpoint, Duration::from_millis(50)).expect("client");
    let started = Instant::now();
    assert!(client.observe(&owner(), 9, [7; 32]).is_err());
    let elapsed = started.elapsed();
    server.join().expect("server");
    assert!(elapsed < Duration::from_secs(2));
}

#[test]
fn expired_request_budget_does_not_contact_the_frontier_owner() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("listener");
    listener.set_nonblocking(true).expect("nonblocking");
    let client = LoopbackFrontierClient::new(
        listener.local_addr().expect("address"),
        Duration::from_secs(5),
    )
    .expect("client");
    assert!(
        client
            .observe_before(&owner(), 9, [7; 32], Instant::now())
            .is_err()
    );
    assert_eq!(
        listener.accept().expect_err("no connection").kind(),
        std::io::ErrorKind::WouldBlock
    );
}

#[test]
fn request_deadline_wins_over_a_long_configured_provider_timeout() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("listener");
    let endpoint = listener.local_addr().expect("address");
    let (released_tx, released_rx) = std::sync::mpsc::channel();
    let server = std::thread::spawn(move || {
        let (mut socket, _) = listener.accept().expect("accept");
        socket
            .set_read_timeout(Some(Duration::from_secs(2)))
            .expect("bound server");
        let mut buffer = [0_u8; 512];
        loop {
            match socket.read(&mut buffer) {
                Ok(0) => break,
                Ok(_) => {}
                Err(_) => return false,
            }
        }
        released_tx.send(()).expect("release observed");
        true
    });
    let client = LoopbackFrontierClient::new(endpoint, Duration::from_secs(5)).expect("client");
    assert!(
        client
            .observe_before(
                &owner(),
                9,
                [7; 32],
                Instant::now() + Duration::from_millis(100)
            )
            .is_err()
    );
    released_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("socket closed after request expiry");
    assert!(server.join().expect("server"));
}
