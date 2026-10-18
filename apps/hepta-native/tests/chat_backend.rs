//! Actual loopback transport tests; scripted Root replies confer no product authority.
#![allow(clippy::unwrap_used, clippy::expect_used)]
use codex_hepta_contracts::native_gateway::chat::*;
use codex_hepta_contracts::native_gateway::*;
use hepta_native::backend::BackendAdapter;
use hepta_native::backend::LoopbackGatewayBackend;
use hepta_native::chat_protocol::root::*;
use hepta_native::model::EndpointManifest;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::net::TcpStream;
const READ: &str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
const CHAT: &str = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC";
fn receive(stream: &mut TcpStream) -> (String, Vec<u8>) {
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(3)))
        .unwrap();
    let mut bytes = Vec::new();
    let mut buffer = [0; 4096];
    loop {
        let count = stream.read(&mut buffer).unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&buffer[..count]);
        if let Some(end) = bytes.windows(4).position(|p| p == b"\r\n\r\n") {
            let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
            let length = headers
                .lines()
                .find_map(|line| line.strip_prefix("Content-Length: "))
                .map(|n| n.parse::<usize>().unwrap())
                .unwrap_or(0);
            if bytes.len() == end + 4 + length {
                return (headers, bytes[end + 4..].to_vec());
            }
        }
    }
}
fn response(stream: &mut TcpStream, body: &[u8], mac: String) {
    let headers = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nX-Hepta-Response-MAC: {mac}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(headers.as_bytes()).unwrap();
    stream.write_all(body).unwrap();
}
fn request() -> NativeChatRootRequest {
    NativeChatRootRequest::Attach {
        binding: NativeChatBinding {
            agent_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".into(),
            supervisor_process_id: 2,
            agent_process_id: 3,
            control_fence: serde_json::json!({"original":"fence"}),
        },
        session_id: "frontend-original".into(),
    }
}
#[test]
fn real_http_uses_chat_purpose_and_authenticates_exact_original_response_binding() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let expected = request();
    let owner = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let (headers, _) = receive(&mut stream);
        let header = headers
            .lines()
            .find_map(|line| line.strip_prefix("Authorization: "))
            .unwrap();
        let proof = NativeGatewayRequestV2::parse_header(header).unwrap();
        let health=serde_json::to_vec(&serde_json::json!({"product":"hepta","status":"ok","native_auth":"keyring_mac_v2","native_protocol_version":2,"native_incarnation":"2".repeat(64),"chat_control":true})).unwrap();
        response(
            &mut stream,
            &health,
            proof.response_tag(READ.as_bytes(), 200, &health).unwrap(),
        );
        drop(stream);
        let (mut stream, _) = listener.accept().unwrap();
        let (headers, body) = receive(&mut stream);
        assert!(headers.starts_with("POST /api/hepta/agents/chat HTTP/1.1"));
        assert!(!headers.contains(CHAT));
        assert!(!headers.contains(READ));
        let header = headers
            .lines()
            .find_map(|line| line.strip_prefix("Authorization: "))
            .unwrap();
        let proof = NativeGatewayChatRequestV2::parse_header(header).unwrap();
        proof
            .verify(
                CHAT.as_bytes(),
                "POST",
                NATIVE_GATEWAY_CHAT_PATH,
                NativeGatewayChatOperationV2::Attach,
                &body,
                hepta_native::security::now_unix_ms().unwrap(),
                &[0x22; 32],
            )
            .unwrap();
        assert!(NativeGatewayRequestV2::parse_header(header).is_err());
        assert_eq!(
            serde_json::from_slice::<NativeChatRootRequest>(&body).unwrap(),
            expected
        );
        let NativeChatRootRequest::Attach {
            binding,
            session_id,
        } = expected.clone()
        else {
            panic!("attach expected")
        };
        let result = serde_json::to_vec(&NativeChatRootResponse::Attached {
            binding,
            session_id,
            connection_generation: 7,
        })
        .unwrap();
        response(
            &mut stream,
            &result,
            proof.response_tag(CHAT.as_bytes(), 200, &result).unwrap(),
        );
        drop(stream);
        let (mut stream, _) = listener.accept().unwrap();
        let (headers, body) = receive(&mut stream);
        let header = headers
            .lines()
            .find_map(|line| line.strip_prefix("Authorization: "))
            .unwrap();
        let proof = NativeGatewayChatRequestV2::parse_header(header).unwrap();
        assert_eq!(
            serde_json::from_slice::<NativeChatRootRequest>(&body).unwrap(),
            expected
        );
        // A read-purpose key cannot authenticate even a structurally valid chat reply.
        response(
            &mut stream,
            &result,
            proof.response_tag(READ.as_bytes(), 200, &result).unwrap(),
        );
    });
    let mut backend = LoopbackGatewayBackend::new(address, READ.into())
        .unwrap()
        .with_chat_capability(CHAT.into())
        .unwrap();
    backend
        .connect(&EndpointManifest {
            endpoint_id: "runtime.fleet".into(),
            address: address.to_string(),
            manifest_digest: "1".repeat(64),
            protocol_version: 2,
        })
        .unwrap();
    assert!(backend.chat_available());
    assert!(matches!(
        backend.chat(&request()).unwrap(),
        NativeChatRootResponse::Attached {
            connection_generation: 7,
            ..
        }
    ));
    assert!(backend.chat(&request()).is_err());
    owner.join().unwrap();
}
#[test]
fn chat_read_and_lifecycle_keys_cannot_cross_purposes_in_either_configuration_order() {
    let address = "127.0.0.1:7373".parse().unwrap();
    assert!(
        LoopbackGatewayBackend::new(address, READ.into())
            .unwrap()
            .with_chat_capability(READ.into())
            .is_err()
    );
    assert!(
        LoopbackGatewayBackend::new(address, READ.into())
            .unwrap()
            .with_fleet_lifecycle_capability(CHAT.into())
            .unwrap()
            .with_chat_capability(CHAT.into())
            .is_err()
    );
    assert!(
        LoopbackGatewayBackend::new(address, READ.into())
            .unwrap()
            .with_chat_capability(CHAT.into())
            .unwrap()
            .with_fleet_lifecycle_capability(CHAT.into())
            .is_err()
    );
}
