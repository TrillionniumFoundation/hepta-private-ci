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
fn original_mixed_input_history_keeps_chinese_text_and_allows_the_next_stream() {
    let (mut workspace, binding) = workspace();
    workspace.edit("下一条中文草稿\n保留输入法已提交的文字".into());
    let draft = workspace.draft().clone();
    let turn = json!({"id":"history-turn","status":"completed","items":[
        {"type":"userMessage","id":"mixed-input","clientId":"original-client","content":[
            {"type":"text","text":"  请看附件\n你好，世界。  ","text_elements":[]},
            {"type":"image","url":"data:image/png;base64,DO_NOT_EXPAND"},
            {"type":"localImage","path":"/private/do-not-open.png"},
            {"type":"audio","url":"https://example.invalid/do-not-fetch.wav"},
            {"type":"localAudio","path":"/private/do-not-open.wav"},
            {"type":"skill","name":"do-not-invoke","path":"/private/skill.md"},
            {"type":"mention","name":"do-not-resolve","path":"connector://private"},
            {"type":"text","text":"原始后文。","text_elements":[]}
        ]}
    ]});
    workspace
        .receive_app_server_history(&binding, 11, &[turn], 11)
        .unwrap();
    let original_input = Message {
        id: "mixed-input".into(),
        turn_id: "history-turn".into(),
        role: Role::User,
        text: concat!(
            "  请看附件\n你好，世界。  \n",
            "[Original image attachment; preview unavailable]\n",
            "[Original local image attachment; preview unavailable]\n",
            "[Original audio attachment; preview unavailable]\n",
            "[Original local audio attachment; preview unavailable]\n",
            "[Original skill reference; details remain in App Server]\n",
            "[Original mention reference; details remain in App Server]\n",
            "原始后文。"
        )
        .into(),
        phase: MessagePhase::Observed,
    };
    assert_eq!(
        workspace.timeline().unwrap().history().unwrap().messages,
        vec![original_input.clone()]
    );
    for notification in [
        json!({"method":"item/started","params":{
            "threadId":"thread","turnId":"next-turn","startedAtMs":12,
            "item":{"type":"agentMessage","id":"next-reply","text":""}
        }}),
        json!({"method":"item/agentMessage/delta","params":{
            "threadId":"thread","turnId":"next-turn","itemId":"next-reply","delta":"中文继续"
        }}),
        json!({"method":"turn/completed","params":{
            "threadId":"thread","turn":{"id":"next-turn","status":"completed","items":[]}
        }}),
    ] {
        workspace
            .receive_app_server_notification(&binding, 11, &notification, 12)
            .unwrap();
    }
    let history = workspace.timeline().unwrap().history().unwrap();
    assert_eq!(history.thread_id, "thread");
    assert_eq!(
        history.messages,
        vec![
            original_input,
            Message {
                id: "next-reply".into(),
                turn_id: "next-turn".into(),
                role: Role::Assistant,
                text: "中文继续".into(),
                phase: MessagePhase::Completed,
            },
        ]
    );
    assert_eq!(workspace.draft(), &draft);
    assert!(
        workspace
            .authenticated_chat_scope(ChatCapability::SubmitSignedText, 12)
            .is_err()
    );
}

#[test]
fn future_original_input_is_explicitly_unsupported_and_never_expands_its_payload() {
    let (mut workspace, binding) = workspace();
    let turn = json!({"id":"future-turn","status":"completed","items":[
        {"type":"userMessage","id":"future-input","content":[
            {"type":"futureEffect","payload":"private-attachment-data".repeat(1_000)},
            {"type":"text","text":"仍保留原始中文"}
        ]}
    ]});
    workspace
        .receive_app_server_history(&binding, 11, &[turn.clone()], 11)
        .unwrap();
    let expected = Message {
        id: "future-input".into(),
        turn_id: "future-turn".into(),
        role: Role::User,
        text: "[Unsupported original content; retained by App Server]\n仍保留原始中文".into(),
        phase: MessagePhase::Observed,
    };
    assert_eq!(
        workspace.timeline().unwrap().history().unwrap().messages,
        vec![expected.clone()]
    );
    workspace
        .receive_app_server_turn(&binding, 11, &turn, 12)
        .unwrap();
    assert_eq!(
        workspace.timeline().unwrap().history().unwrap().messages,
        vec![expected]
    );
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
