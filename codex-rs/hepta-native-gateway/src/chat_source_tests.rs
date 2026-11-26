#![allow(clippy::expect_used, clippy::unwrap_used)]
use super::*;
use crate::chat_protocol::root::NativeChatBinding;
use crate::chat_protocol::wire::ChatRequest;
use crate::chat_protocol::wire::ChatResponse;
use crate::chat_protocol::wire::ChatResult;
use crate::chat_protocol::wire::SubmissionState;
use codex_hepta_contracts::native_gateway::chat::NATIVE_GATEWAY_CHAT_PATH;
use std::os::unix::fs::MetadataExt;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::net::UnixListener;

fn attach() -> NativeChatRootRequest {
    NativeChatRootRequest::Attach {
        binding: NativeChatBinding {
            agent_id: "00000000-0000-4000-8000-000000000001".into(),
            supervisor_process_id: 10,
            agent_process_id: 11,
            control_fence: serde_json::json!({"full": "current-original-fence"}),
        },
        session_id: "native-session".into(),
    }
}
fn proof(
    auth: &GatewayAuth,
    key: &str,
    request: &NativeChatRootRequest,
    nonce: u8,
) -> NativeGatewayChatRequestV2 {
    NativeGatewayChatRequestV2::sign(
        key.as_bytes(),
        "POST",
        NATIVE_GATEWAY_CHAT_PATH,
        operation(request),
        &serde_json::to_vec(request).unwrap(),
        [nonce; 32],
        crate::native_mac::now_unix_ms().unwrap(),
        auth.server_incarnation,
    )
    .unwrap()
}
fn frame(header: &str, body: &[u8]) -> Vec<u8> {
    let mut bytes = format!("POST {NATIVE_GATEWAY_CHAT_PATH} HTTP/1.1\r\nAuthorization: {header}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n", body.len()).into_bytes();
    bytes.extend_from_slice(body);
    bytes
}
fn body(response: &[u8]) -> &[u8] {
    let (_, split) = crate::native_mac::response_parts(response).unwrap();
    &response[split + 4..]
}
fn verify(response: &[u8], signed: &NativeGatewayChatRequestV2, key: &str) {
    let (status, split) = crate::native_mac::response_parts(response).unwrap();
    let head = std::str::from_utf8(&response[..split]).unwrap();
    let tag = head
        .lines()
        .find_map(|line| line.strip_prefix("X-Hepta-Response-MAC: "))
        .unwrap();
    signed
        .verify_response(key.as_bytes(), status, body(response), tag)
        .unwrap();
}

#[tokio::test]
async fn purpose_mac_actual_http_and_uds_preserve_binding_and_reject_replay_substitution()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("ctl");
    let listener = UnixListener::bind(&socket)?;
    let calls = Arc::new(AtomicUsize::new(0));
    let seen = calls.clone();
    let original = attach();
    let expected = original.clone();
    let owner = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        let (reader, mut writer) = stream.into_split();
        let mut bytes = Vec::new();
        BufReader::new(reader).read_to_end(&mut bytes).await?;
        assert_eq!(
            serde_json::from_slice::<NativeChatRootRequest>(&bytes)?,
            expected
        );
        seen.fetch_add(1, Ordering::SeqCst);
        let NativeChatRootRequest::Attach {
            binding,
            session_id,
        } = expected
        else {
            panic!("expected attach")
        };
        let mut reply = serde_json::to_vec(&NativeChatRootResponse::Attached {
            binding,
            session_id,
            connection_generation: 1,
        })?;
        reply.push(b'\n');
        writer.write_all(&reply).await?;
        writer.shutdown().await?;
        Ok::<_, anyhow::Error>(())
    });
    let auth = Arc::new(GatewayAuth::new("r".repeat(64))?);
    let key = "h".repeat(64);
    let source = Arc::new(ChatSource::with_capability(
        socket,
        std::fs::metadata(directory.path())?.uid(),
        key.clone(),
        &auth,
        Some(b"independent-lifecycle-key"),
    )?);
    let tcp = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let address = tcp.local_addr()?;
    let gateway_auth = auth.clone();
    let gateway = tokio::spawn(async move {
        for _ in 0..4 {
            let (mut stream, _) = tcp.accept().await?;
            let bytes = crate::lifecycle_http::read(&mut stream).await?;
            let response = source
                .route(crate::lifecycle_http::parse(&bytes)?, &gateway_auth)
                .await?;
            stream.write_all(&response).await?;
            stream.shutdown().await?;
        }
        Ok::<_, anyhow::Error>(())
    });
    let body = serde_json::to_vec(&original)?;
    let signed = proof(&auth, &key, &original, 1);
    async fn send(address: std::net::SocketAddr, bytes: Vec<u8>) -> Result<Vec<u8>> {
        let mut stream = tokio::net::TcpStream::connect(address).await?;
        stream.write_all(&bytes).await?;
        stream.shutdown().await?;
        let mut response = Vec::new();
        stream.read_to_end(&mut response).await?;
        Ok(response)
    }
    let response = send(address, frame(&signed.header_value(), &body)).await?;
    verify(&response, &signed, &key);
    assert_eq!(
        serde_json::from_slice::<NativeChatRootResponse>(self::body(&response))?,
        NativeChatRootResponse::Attached {
            binding: original.binding().clone(),
            session_id: "native-session".into(),
            connection_generation: 1
        }
    );
    for rejected in [
        frame(&signed.header_value(), &body),
        frame(
            &proof(&auth, &"r".repeat(64), &original, 2).header_value(),
            &body,
        ),
        frame(
            &NativeGatewayChatRequestV2::sign(
                key.as_bytes(),
                "POST",
                NATIVE_GATEWAY_CHAT_PATH,
                NativeGatewayChatOperationV2::Send,
                &body,
                [3; 32],
                crate::native_mac::now_unix_ms()?,
                auth.server_incarnation,
            )?
            .header_value(),
            &body,
        ),
    ] {
        let response = send(address, rejected).await?;
        assert!(response.starts_with(b"HTTP/1.1 401"));
    }
    owner.await??;
    gateway.await??;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn wrong_root_peer_writes_zero_protocol_bytes_and_reports_known_no_effect() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("ctl");
    let listener = UnixListener::bind(&socket)?;
    let owner = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).await?;
        assert_eq!(bytes, Vec::<u8>::new());
        Ok::<_, anyhow::Error>(())
    });
    let auth = GatewayAuth::new("r".repeat(64))?;
    let key = "h".repeat(64);
    let source = ChatSource::with_capability(
        socket,
        std::fs::metadata(directory.path())?.uid().wrapping_add(1),
        key.clone(),
        &auth,
        None,
    )?;
    let request = attach();
    let signed = proof(&auth, &key, &request, 4);
    let frame = frame(&signed.header_value(), &serde_json::to_vec(&request)?);
    let response = source
        .route(crate::lifecycle_http::parse(&frame)?, &auth)
        .await?;
    verify(&response, &signed, &key);
    assert_eq!(
        serde_json::from_slice::<NativeChatRootResponse>(body(&response))?,
        NativeChatRootResponse::Rejected {
            code: "bridge_transport_unavailable".into(),
            outcome_unknown: false
        }
    );
    owner.await??;
    Ok(())
}

#[tokio::test]
async fn lost_owner_reply_preserves_original_operation_for_explicit_reconcile_without_resend()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("ctl");
    let listener = UnixListener::bind(&socket)?;
    let original = ChatRequest {
        session_id: "native-session".into(),
        connection_generation: 1,
        command: ChatCommand::Send {
            thread_id: "thread-one".into(),
            operation_id: "original-operation-one".into(),
            text: "same original message".into(),
        },
    };
    let binding = attach().binding().clone();
    let request = NativeChatRootRequest::Dispatch {
        binding: binding.clone(),
        request: original.clone(),
    };
    let expected = original.clone();
    let bound = binding.clone();
    let owner = tokio::spawn(async move {
        for index in 0..2 {
            let (stream, _) = listener.accept().await?;
            let (reader, mut writer) = stream.into_split();
            let mut bytes = Vec::new();
            BufReader::new(reader).read_to_end(&mut bytes).await?;
            let decoded: NativeChatRootRequest = serde_json::from_slice(&bytes)?;
            let NativeChatRootRequest::Dispatch { binding, request } = decoded else {
                panic!("expected dispatch")
            };
            assert_eq!(binding, bound);
            if index == 0 {
                assert_eq!(request, expected);
                continue;
            }
            let ChatCommand::Send {
                thread_id,
                operation_id,
                text,
            } = &expected.command
            else {
                panic!("expected send")
            };
            assert_eq!(
                request.command,
                ChatCommand::Reconcile {
                    thread_id: thread_id.clone(),
                    operation_id: operation_id.clone(),
                    text: text.clone()
                }
            );
            let response = NativeChatRootResponse::Response {
                binding,
                response: ChatResponse {
                    session_id: request.session_id,
                    connection_generation: request.connection_generation,
                    result: ChatResult::Submission {
                        operation_id: operation_id.clone(),
                        state: SubmissionState::Missing,
                    },
                    approval_required: false,
                },
            };
            let mut bytes = serde_json::to_vec(&response)?;
            bytes.push(b'\n');
            writer.write_all(&bytes).await?;
            writer.shutdown().await?;
        }
        Ok::<_, anyhow::Error>(())
    });
    let auth = GatewayAuth::new("r".repeat(64))?;
    let key = "h".repeat(64);
    let source = ChatSource::with_capability(
        socket,
        std::fs::metadata(directory.path())?.uid(),
        key.clone(),
        &auth,
        None,
    )?;
    let signed = proof(&auth, &key, &request, 5);
    let frame = frame(&signed.header_value(), &serde_json::to_vec(&request)?);
    let response = source
        .route(crate::lifecycle_http::parse(&frame)?, &auth)
        .await?;
    verify(&response, &signed, &key);
    assert_eq!(
        serde_json::from_slice::<NativeChatRootResponse>(body(&response))?,
        NativeChatRootResponse::Rejected {
            code: "bridge_transport_unavailable".into(),
            outcome_unknown: true
        }
    );
    let ChatCommand::Send {
        thread_id,
        operation_id,
        text,
    } = original.command
    else {
        panic!("expected send")
    };
    let reconcile = NativeChatRootRequest::Dispatch {
        binding,
        request: ChatRequest {
            session_id: original.session_id.clone(),
            connection_generation: original.connection_generation,
            command: ChatCommand::Reconcile {
                thread_id,
                operation_id: operation_id.clone(),
                text,
            },
        },
    };
    let signed = proof(&auth, &key, &reconcile, 6);
    let bytes = self::frame(&signed.header_value(), &serde_json::to_vec(&reconcile)?);
    let response = source
        .route(crate::lifecycle_http::parse(&bytes)?, &auth)
        .await?;
    verify(&response, &signed, &key);
    assert_eq!(
        serde_json::from_slice::<NativeChatRootResponse>(body(&response))?,
        NativeChatRootResponse::Response {
            binding: reconcile.binding().clone(),
            response: ChatResponse {
                session_id: original.session_id,
                connection_generation: original.connection_generation,
                result: ChatResult::Submission {
                    operation_id,
                    state: SubmissionState::Missing
                },
                approval_required: false
            }
        }
    );
    owner.await??;
    Ok(())
}

#[test]
fn capability_separation_and_response_instance_substitution_fail_closed() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let auth = GatewayAuth::new("r".repeat(64))?;
    assert!(
        ChatSource::with_capability(directory.path().join("ctl"), 0, "r".repeat(64), &auth, None)
            .is_err()
    );
    assert!(
        ChatSource::with_capability(
            directory.path().join("ctl"),
            0,
            "h".repeat(64),
            &auth,
            Some("h".repeat(64).as_bytes())
        )
        .is_err()
    );
    let request = attach();
    let mut substituted = request.binding().clone();
    substituted.agent_process_id += 1;
    let response = NativeChatRootResponse::Attached {
        binding: substituted,
        session_id: "native-session".into(),
        connection_generation: 1,
    };
    assert!(response.validate_for(&request).is_err());
    Ok(())
}
