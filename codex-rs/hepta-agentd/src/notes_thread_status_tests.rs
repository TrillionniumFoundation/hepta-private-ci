//! Read-only Core response fixtures, not Root/Human/model/effect evidence.
use std::collections::VecDeque;

use codex_app_server_protocol::DynamicToolCallStatus;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadItemEntry;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnStatus;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::*;

fn route() -> AgentdTextSessionConfig {
    AgentdTextSessionConfig {
        control_socket: "/fixture/agentd.sock".into(),
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18").unwrap(),
        spawn_generation: 2,
        thread_id: "original-thread".into(),
        app_server_session_id: "original-session".into(),
        codex_home: "/fixture/home".into(),
    }
}

fn lost_reply(call: &str, tool: &str) -> ThreadItem {
    ThreadItem::DynamicToolCall {
        id: call.into(),
        namespace: None,
        tool: tool.into(),
        arguments: if tool == REPLACE_TOOL {
            json!({"text":"原笔记","expected_revision":0})
        } else {
            json!({})
        },
        status: DynamicToolCallStatus::Failed,
        content_items: None,
        success: None,
        duration_ms: None,
    }
}

fn page(turn: &str, items: Vec<ThreadItem>, next: Option<String>) -> ThreadItemsListResponse {
    ThreadItemsListResponse {
        data: items
            .into_iter()
            .map(|item| ThreadItemEntry {
                turn_id: turn.into(),
                item,
            })
            .collect(),
        next_cursor: next,
        backwards_cursor: None,
    }
}

struct History {
    turns: Option<ThreadTurnsListResponse>,
    pages: VecDeque<(String, ThreadItemsListResponse)>,
    calls: usize,
}
impl History {
    fn new(turns: &[&str], pages: Vec<(&str, ThreadItemsListResponse)>) -> Self {
        Self {
            turns: Some(ThreadTurnsListResponse {
                data: turns
                    .iter()
                    .map(|id| Turn {
                        id: (*id).into(),
                        items: vec![],
                        items_view: TurnItemsView::NotLoaded,
                        status: TurnStatus::Completed,
                        error: None,
                        started_at: None,
                        completed_at: None,
                        duration_ms: None,
                    })
                    .collect(),
                next_cursor: None,
                backwards_cursor: None,
            }),
            pages: pages
                .into_iter()
                .map(|(turn, page)| (turn.into(), page))
                .collect(),
            calls: 0,
        }
    }
}
impl OriginalStatusHistory for History {
    async fn turns(
        &mut self,
        params: ThreadTurnsListParams,
    ) -> Result<ThreadTurnsListResponse, AgentdError> {
        assert_eq!(params.thread_id, route().thread_id);
        assert_eq!(params.sort_direction, Some(SortDirection::Desc));
        assert_eq!(params.items_view, Some(TurnItemsView::NotLoaded));
        self.calls += 1;
        Ok(self.turns.take().unwrap())
    }
    async fn items(
        &mut self,
        params: ThreadItemsListParams,
    ) -> Result<ThreadItemsListResponse, AgentdError> {
        assert_eq!(params.thread_id, route().thread_id);
        assert_eq!(params.sort_direction, Some(SortDirection::Asc));
        assert_eq!(params.limit, Some(64));
        self.calls += 1;
        let (turn, page) = self.pages.pop_front().unwrap();
        assert_eq!(params.turn_id.as_deref(), Some(turn.as_str()));
        Ok(page)
    }
}

#[tokio::test]
async fn discovery_recovers_first_original_identity_without_tool_reply_or_model_context() {
    // Neither old tool result nor old IDs are provided by the caller. The
    // newest turn has no write; original persisted items supply the identity.
    let mut history = History::new(
        &["new-status", "old-write"],
        vec![
            (
                "new-status",
                page("new-status", vec![lost_reply("new-state", READ_TOOL)], None),
            ),
            (
                "old-write",
                page(
                    "old-write",
                    vec![
                        lost_reply("first", REPLACE_TOOL),
                        lost_reply("retry", REPLACE_TOOL),
                    ],
                    None,
                ),
            ),
        ],
    );
    let StatusDiscovery::Found(found) = discover_latest_original_replace(&route(), &mut history)
        .await
        .unwrap()
    else {
        panic!("original item must remain observable")
    };
    assert_eq!(
        (
            found.original_item().turn_id(),
            found.original_item().call_id()
        ),
        ("old-write", "first")
    );
    assert_eq!(history.calls, 3);
    let mut old_route = route();
    old_route.spawn_generation = 1;
    assert_eq!(
        found.original_item().turn_intent_id(&old_route).unwrap(),
        found.original_item().turn_intent_id(&route()).unwrap()
    );
}

#[tokio::test]
async fn absent_original_items_cannot_be_replaced_by_model_result_text() {
    let mut invented = lost_reply("state", READ_TOOL);
    if let ThreadItem::DynamicToolCall { content_items, .. } = &mut invented {
        *content_items = Some(vec![
            codex_app_server_protocol::DynamicToolCallOutputContentItem::InputText {
                text:
                    json!({"turn_id":"invented-old","call_id":"invented-call","state":"Committed"})
                        .to_string(),
            },
        ]);
    }
    let mut history = History::new(
        &["new-status"],
        vec![("new-status", page("new-status", vec![invented], None))],
    );
    assert!(matches!(
        discover_latest_original_replace(&route(), &mut history)
            .await
            .unwrap(),
        StatusDiscovery::Unknown(StatusUnknownReason::OriginalReplaceNotObserved)
    ));
    let mut history = History::new(&[], vec![]);
    history.turns.as_mut().unwrap().next_cursor = Some("older-turns".into());
    assert!(matches!(
        discover_latest_original_replace(&route(), &mut history)
            .await
            .unwrap(),
        StatusDiscovery::Unknown(StatusUnknownReason::WindowExhausted)
    ));
}

#[tokio::test]
async fn incomplete_newer_turn_never_falls_back_to_an_older_write() {
    let mut history = History::new(
        &["newer", "older-write"],
        (0..4)
            .map(|i| {
                (
                    "newer",
                    page(
                        "newer",
                        vec![lost_reply("state", READ_TOOL)],
                        Some(format!("page-{i}")),
                    ),
                )
            })
            .collect(),
    );
    assert!(matches!(
        discover_latest_original_replace(&route(), &mut history)
            .await
            .unwrap(),
        StatusDiscovery::Unknown(StatusUnknownReason::WindowExhausted)
    ));
    assert_eq!(history.calls, 5);
    let mut history = History::new(
        &["original"],
        vec![(
            "original",
            page("foreign", vec![lost_reply("first", REPLACE_TOOL)], None),
        )],
    );
    assert!(
        discover_latest_original_replace(&route(), &mut history)
            .await
            .is_err()
    );
}

#[test]
fn selector_and_exact_references_are_exclusive_and_cannot_supply_authority() {
    for value in [
        json!({"turn_id":"old","call_id":"call"}),
        json!({"selector":{"kind":"latest_original_replace"}}),
    ] {
        serde_json::from_value::<StatusArguments>(value)
            .unwrap()
            .validate()
            .unwrap();
    }
    for value in [
        json!({"turn_id":"old","call_id":"call","selector":{"kind":"latest_original_replace"}}),
        json!({"selector":{"kind":"latest_original_replace","target":"forged"}}),
        json!({"selector":{"kind":"latest_original_replace"},"thread_id":"foreign"}),
        json!({"selector":{"kind":"all_threads"}}),
    ] {
        assert!(serde_json::from_value::<StatusArguments>(value).is_err());
    }
    assert!(
        serde_json::from_value::<StatusArguments>(json!({"turn_id":"","call_id":"call"}))
            .unwrap()
            .validate()
            .is_err()
    );
}
