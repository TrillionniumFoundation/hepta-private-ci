//! Protocol fixtures validate bounded recovery parsing; they do not establish
//! a production Root owner or model connection.
use super::*;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

async fn response(
    listener: &tokio::net::UnixListener,
    value: serde_json::Value,
) -> serde_json::Value {
    let (mut stream, _) = listener.accept().await.unwrap();
    let length = stream.read_u32().await.unwrap() as usize;
    assert!(length <= 32768);
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes).await.unwrap();
    let request = serde_json::from_slice(&bytes).unwrap();
    let bytes = serde_json::to_vec(&value).unwrap();
    stream
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .await
        .unwrap();
    stream.write_all(&bytes).await.unwrap();
    request
}

fn owner() -> TextOwnerReceipt {
    TextOwnerReceipt {
        schema_version: 1,
        protocol: "hepta.ui-chat-owner.v1".into(),
        principal_id: "human".into(),
        session_id: "session".into(),
        permission_revision: 1,
        expires_at_ms: u64::MAX,
        route: AgentdTextSessionConfig {
            control_socket: "/original/agentd.sock".into(),
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
            spawn_generation: 2,
            thread_id: "original-thread".into(),
            app_server_session_id: "original-session".into(),
            codex_home: "/original/home".into(),
        },
        can_interrupt: false,
        can_resolve_approvals: false,
        intent_namespace: "text:human-scope".into(),
        next_intent_sequence: 3,
    }
}

#[test]
fn old_owner_receipt_does_not_gain_approval_permission_on_decode_or_reconnect() {
    let original = owner();
    let mut wire = serde_json::to_value(&original).unwrap();
    wire.as_object_mut()
        .unwrap()
        .remove("can_resolve_approvals");
    let decoded: TextOwnerReceipt = serde_json::from_value(wire).unwrap();
    assert_eq!(decoded, original);
    let mut changed = decoded;
    changed.can_resolve_approvals = true;
    assert!(!original.same_authorization(&changed));
}

fn entry(namespace: &str, number: u64) -> serde_json::Value {
    serde_json::json!({ "request_id": format!("{namespace}:{number}"), "envelope": {
        "issuer_id": "original", "key_epoch": 1, "message_id": format!("original:{number}"),
        "sequence": number, "expires_at_ms": 1, "signature_hex": "00".repeat(64),
        "body": {"spawn_generation":1,"thread_id":"original-thread","text":"retained original input"}
    }})
}

#[tokio::test]
async fn recovery_pages_original_namespace_without_requesting_a_new_signature() {
    let directory = tempfile::tempdir().unwrap();
    let socket_path = directory.path().join("protocol-fixture.sock");
    let listener = tokio::net::UnixListener::bind(&socket_path).unwrap();
    let server = tokio::spawn(async move {
        let first = response(&listener, serde_json::json!({"schema_version":1,"operation":"pending","through_sequence":2,"entry":entry("text:human-scope",1)})).await;
        let second = response(&listener, serde_json::json!({"schema_version":1,"operation":"pending","through_sequence":2,"entry":null})).await;
        assert_eq!(
            first,
            serde_json::json!({"schema_version":1,"operation":"pending","after_sequence":0,"through_sequence":2})
        );
        assert_eq!(
            second,
            serde_json::json!({"schema_version":1,"operation":"pending","after_sequence":1,"through_sequence":2})
        );
    });
    let endpoint = TextSignerEndpoint {
        socket_path,
        owner_uid: unsafe { libc::geteuid() },
        owner_pid: std::process::id(),
    };
    let observed = pending(&endpoint, &owner()).await.unwrap();
    assert_eq!(observed.len(), 1);
    assert_eq!(observed[0].request_id, "text:human-scope:1");
    assert_eq!(observed[0].envelope.body.spawn_generation, 1);
    server.await.unwrap();
}

#[tokio::test]
async fn recovery_rejects_another_namespace_or_a_number_above_hello_watermark() {
    for (namespace, number) in [("other-human", 1), ("text:human-scope", 3)] {
        let directory = tempfile::tempdir().unwrap();
        let socket_path = directory.path().join("invalid-fixture.sock");
        let listener = tokio::net::UnixListener::bind(&socket_path).unwrap();
        let value = entry(namespace, number);
        let server = tokio::spawn(async move {
            response(&listener, serde_json::json!({"schema_version":1,"operation":"pending","through_sequence":2,"entry":value})).await;
        });
        let endpoint = TextSignerEndpoint {
            socket_path,
            owner_uid: unsafe { libc::geteuid() },
            owner_pid: std::process::id(),
        };
        assert!(matches!(
            pending(&endpoint, &owner()).await,
            Err(TextSessionError::Identity)
        ));
        server.await.unwrap();
    }
}
