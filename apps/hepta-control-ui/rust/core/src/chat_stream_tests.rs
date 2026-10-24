use super::*;
use crate::chat_owner::CHAT_OWNER_PROTOCOL;
use crate::chat_owner::OwnerScope;
use crate::chat_owner::OwnerSession;
use serde_json::json;

fn workspace() -> (ChatWorkspace, StreamBinding) {
    let mut workspace = ChatWorkspace::default();
    workspace
        .install_owner(
            OwnerSession {
                protocol: CHAT_OWNER_PROTOCOL.into(),
                scope: OwnerScope {
                    principal_id: "human".into(),
                    session_id: "owner".into(),
                    connection_generation: 3,
                    permission_revision: 1,
                    agent_id: "agent".into(),
                    agent_generation: 1,
                    thread_id: "thread".into(),
                },
                expires_at_ms: 1000,
                capabilities: vec![ChatCapability::ReadHistory, ChatCapability::Subscribe],
            },
            10,
        )
        .unwrap();
    let binding = workspace.begin_stream(0, 11, 10).unwrap();
    (workspace, binding)
}

#[test]
fn original_history_pages_replace_the_visible_window_without_changing_drafts() {
    let (mut workspace, binding) = workspace();
    workspace.edit("local draft stays local".into());
    let recent = json!({"id":"recent-turn","status":"completed","items":[
        {"type":"userMessage","id":"recent-input","content":[{"type":"text","text":"recent original input"}]},
        {"type":"agentMessage","id":"recent-output","text":"recent original output"}
    ]});
    workspace
        .receive_app_server_history(&binding, 11, &[recent], 11)
        .unwrap();
    assert_eq!(
        workspace.timeline().unwrap().history().unwrap().messages[0].id,
        "recent-input"
    );
    let earlier = json!({"id":"earlier-turn","status":"completed","items":[
        {"type":"agentMessage","id":"earlier-output","text":"earlier original output"}
    ]});
    workspace
        .receive_app_server_history(&binding, 11, &[earlier.clone()], 12)
        .unwrap();
    assert_eq!(
        workspace
            .timeline()
            .unwrap()
            .history()
            .unwrap()
            .messages
            .len(),
        1
    );
    assert_eq!(
        workspace.timeline().unwrap().history().unwrap().messages[0].id,
        "earlier-output"
    );
    assert_eq!(workspace.draft().text, "local draft stays local");
    let before = workspace.timeline().unwrap().history().cloned();
    assert_eq!(
        workspace.receive_app_server_history(&binding, 10, &[earlier], 13),
        Err(E::Stale)
    );
    assert_eq!(workspace.timeline().unwrap().history().cloned(), before);
}

#[test]
fn a_large_tool_display_has_an_explicit_utf8_safe_preview_without_new_effects() {
    let (mut workspace, binding) = workspace();
    let turn = json!({"id":"large-tool-turn","status":"completed","items":[
        {"type":"commandExecution","id":"original-tool-item","aggregatedOutput":"界".repeat(15_000)}
    ]});
    workspace
        .receive_app_server_turn(&binding, 11, &turn, 11)
        .unwrap();
    let message = &workspace.timeline().unwrap().history().unwrap().messages[0];
    assert_eq!(message.id, "original-tool-item");
    assert_eq!(message.phase, MessagePhase::Completed);
    assert!(message.text.len() < 33 * 1024);
    assert!(message.text.contains("[Desktop preview:"));
    assert!(message.text.ends_with("original App Server item.]"));
}

#[test]
fn original_stream_and_reconciliation_share_the_same_timeline_and_item_identity() {
    let (mut workspace, binding) = workspace();
    workspace
        .receive_app_server_notification(
            &binding,
            11,
            &json!({
                "method":"item/started", "params":{"threadId":"thread","turnId":"turn",
                "item":{"type":"agentMessage","id":"reply","text":""}}
            }),
            11,
        )
        .unwrap();
    workspace.receive_app_server_notification(&binding, 11, &json!({
        "method":"item/agentMessage/delta", "params":{"threadId":"thread","turnId":"turn","itemId":"reply","delta":"你好"}
    }), 12).unwrap();
    assert_eq!(
        workspace.timeline().unwrap().history().unwrap().messages[0].text,
        "你好"
    );
    let turn = json!({"id":"turn","status":"completed","items":[
        {"type":"userMessage","id":"input","content":[{"type":"text","text":"hello"}]},
        {"type":"agentMessage","id":"reply","text":"你好！"},
        {"type":"fileChange","id":"artifact","changes":[{"path":"result.txt"}],"status":"completed"}
    ]});
    workspace
        .receive_app_server_turn(&binding, 11, &turn, 13)
        .unwrap();
    workspace
        .receive_app_server_turn(&binding, 11, &turn, 14)
        .unwrap();
    let history = workspace.timeline().unwrap().history().unwrap();
    assert_eq!(history.messages.len(), 3);
    assert_eq!(
        history.messages[1],
        Message {
            id: "reply".into(),
            turn_id: "turn".into(),
            role: Role::Assistant,
            text: "你好！".into(),
            phase: MessagePhase::Completed
        }
    );
    assert_eq!(history.messages[2].role, Role::System);
    assert!(history.messages[2].text.contains("result.txt"));
}

#[test]
fn connection_rotation_and_owner_expiry_refuse_late_updates_without_touching_draft() {
    let (mut workspace, binding) = workspace();
    workspace.edit("keep my draft".into());
    let turn = json!({"id":"turn","status":"completed","items":[]});
    assert_eq!(
        workspace.receive_app_server_turn(&binding, 12, &turn, 20),
        Err(E::Stale)
    );
    assert_eq!(
        workspace.receive_app_server_turn(&binding, 11, &turn, 1000),
        Err(E::WrongOwner)
    );
    assert_eq!(workspace.draft().text, "keep my draft");
    let _next = workspace.begin_stream(0, 12, 30).unwrap();
    assert_eq!(
        workspace.receive_app_server_turn(&binding, 11, &turn, 31),
        Err(E::Stale)
    );
}

#[test]
fn a_socket_connection_cannot_create_a_chat_owner() {
    let mut workspace = ChatWorkspace::default();
    assert!(matches!(
        workspace.begin_stream(0, 1, 10),
        Err(E::WrongOwner)
    ));
}
