use super::*;
use pretty_assertions::assert_eq;
fn thread(workspace: &AbsolutePathBuf) -> Thread {
    serde_json::from_value(serde_json::json!({
        "id":"t", "sessionId":"s", "preview":"hello", "ephemeral":false,
        "projectId":"p", "modelProvider":"fixture", "createdAt":1,"updatedAt":1,
        "status":{"type":"idle"},"cwd":workspace.as_path(),"cliVersion":"fixture",
        "source":"appServer","threadSource":"hepta-ui-chat","turns":[]
    }))
    .unwrap()
}
#[test]
fn rejects_project_workspace_source_and_ephemeral_scope_drift() {
    let workspace =
        AbsolutePathBuf::from_absolute_path(std::env::temp_dir().join("hepta-chat-fixture"))
            .unwrap();
    let mut value = thread(&workspace);
    assert!(belongs_to_scope(&value, "p", &workspace));
    value.project_id = Some("other".into());
    assert!(!belongs_to_scope(&value, "p", &workspace));
    value = thread(&workspace);
    value.cwd =
        AbsolutePathBuf::from_absolute_path(std::env::temp_dir().join("hepta-chat-other")).unwrap();
    assert!(!belongs_to_scope(&value, "p", &workspace));
    value = thread(&workspace);
    value.thread_source = Some(ThreadSource::Feature("matrix".into()));
    assert!(!belongs_to_scope(&value, "p", &workspace));
    value = thread(&workspace);
    value.ephemeral = true;
    assert!(!belongs_to_scope(&value, "p", &workspace));
}
#[test]
fn bounds_unicode_without_splitting_codepoints() {
    let value = "你".repeat(MAX_CHAT_TEXT_BYTES);
    let result = bounded(value);
    assert_eq!(result.len(), MAX_CHAT_TEXT_BYTES / 3 * 3);
    assert!(result.chars().all(|character| character == '你'));
}
#[test]
fn projects_only_user_facing_message_content() {
    let value = ThreadItemEntry {
        turn_id: "turn".into(),
        item: ThreadItem::UserMessage {
            id: "message".into(),
            client_id: Some("client".into()),
            content: vec![UserInput::Text {
                text: "hello".into(),
                text_elements: vec![],
            }],
        },
    };
    assert_eq!(
        message(value),
        Some(ChatMessage {
            id: "message".into(),
            turn_id: "turn".into(),
            sender: "user".into(),
            body: "hello".into()
        })
    );
}

#[cfg(unix)]
#[tokio::test]
async fn local_ingress_rejects_wrong_agent_generation_and_fenced_health() {
    use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
    use codex_hepta_agentd::AgentdPayload;
    use codex_hepta_agentd::AgentdResponse;
    use codex_hepta_agentd::HealthSnapshot;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::AgentLifecycle;
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncWriteExt;
    use tokio::io::BufReader;
    let expected = AgentId::parse("11111111-1111-4111-8111-111111111111").unwrap();
    for scenario in ["wrong-agent", "wrong-generation", "fenced", "not-ready"] {
        let directory = tempfile::tempdir().unwrap();
        let socket = directory.path().join("agent.sock");
        let mut listener = codex_uds::UnixListener::bind(&socket).await.unwrap();
        let owner = expected.clone();
        let peer = tokio::spawn(async move {
            let stream = listener.accept().await.unwrap();
            let mut stream = BufReader::new(stream);
            let mut line = String::new();
            stream.read_line(&mut line).await.unwrap();
            let request: serde_json::Value = serde_json::from_str(&line).unwrap();
            let reply = AgentdResponse {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: request["request_id"].as_u64().unwrap(),
                agent_id: if scenario == "wrong-agent" {
                    AgentId::parse("22222222-2222-4222-8222-222222222222").unwrap()
                } else {
                    owner
                },
                spawn_generation: if scenario == "wrong-generation" { 8 } else { 7 },
                current_generation: 7,
                payload: AgentdPayload::Health(HealthSnapshot {
                    promotion_ready: true,
                    ready: scenario != "not-ready",
                    fenced: scenario == "fenced",
                    lifecycle: AgentLifecycle::Running,
                    process_id: 1,
                    workspace: "/fixture".into(),
                    home_root: "/fixture-home".into(),
                    run_root: "/fixture-run".into(),
                }),
            };
            let mut bytes = serde_json::to_vec(&reply).unwrap();
            bytes.push(b'\n');
            stream.get_mut().write_all(&bytes).await.unwrap();
        });
        let result = AgentChatSession::connect(
            MatrixAgentdConnectArgs::new(socket, expected.clone(), 7, "fixture"),
            "p".into(),
            AbsolutePathBuf::from_absolute_path("/fixture").unwrap(),
            "frontend-session".into(),
            1,
        )
        .await;
        assert!(
            result.is_err(),
            "{scenario} must stop before App Server connection"
        );
        peer.await.unwrap();
    }
}
