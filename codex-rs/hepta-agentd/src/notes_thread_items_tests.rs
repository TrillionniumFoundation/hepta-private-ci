//! Actual navigator with synthetic Core pages. These controls create no human
//! proof, Root registration, enrollment, journal operation or material read.
use std::collections::VecDeque;

use codex_app_server_protocol::DynamicToolCallStatus;
use codex_app_server_protocol::ThreadItemEntry;
use codex_app_server_protocol::ThreadItemsListResponse;
use codex_app_server_protocol::ThreadTurnsListParams;
use codex_app_server_protocol::ThreadTurnsListResponse;
use codex_app_server_protocol::UserInput;
use pretty_assertions::assert_eq;

use super::*;

fn user(delivery: Digest32) -> ThreadItem {
    ThreadItem::UserMessage {
        id: format!("item-{delivery}"),
        client_id: Some(format!("hepta.authbus:{delivery}")),
        content: vec![UserInput::Text {
            text: "explicit protocol fixture".into(),
            text_elements: vec![],
        }],
    }
}

fn call(id: &str) -> ThreadItem {
    ThreadItem::DynamicToolCall {
        id: id.into(),
        namespace: None,
        tool: REPLACE_TOOL.into(),
        arguments: json!({"text":"fixture", "expected_revision":0}),
        status: DynamicToolCallStatus::Failed,
        content_items: None,
        success: None,
        duration_ms: None,
    }
}

fn page(items: Vec<ThreadItem>) -> ThreadItemsListResponse {
    ThreadItemsListResponse {
        data: items
            .into_iter()
            .map(|item| ThreadItemEntry {
                turn_id: "original-turn".into(),
                item,
            })
            .collect(),
        next_cursor: None,
        backwards_cursor: None,
    }
}

struct History {
    pages: VecDeque<ThreadItemsListResponse>,
    requests: Vec<ThreadItemsListParams>,
}

impl History {
    fn new(pages: Vec<ThreadItemsListResponse>) -> Self {
        Self {
            pages: pages.into(),
            requests: vec![],
        }
    }
}

impl status::OriginalStatusHistory for History {
    async fn turns(
        &mut self,
        _: ThreadTurnsListParams,
    ) -> Result<ThreadTurnsListResponse, AgentdError> {
        panic!("exact turn navigation must not discover a different turn");
    }

    async fn items(
        &mut self,
        params: ThreadItemsListParams,
    ) -> Result<ThreadItemsListResponse, AgentdError> {
        self.requests.push(params);
        self.pages
            .pop_front()
            .ok_or_else(|| invalid("unexpected Core read"))
    }
}

#[tokio::test]
async fn paired_delivery_selects_the_original_later_user_across_pages() {
    let delivery = Digest32::of_bytes(b"authorized later delivery");
    let expected = user(delivery);
    let mut first = page(vec![
        user(Digest32::of_bytes(b"earlier unrelated input")),
        call(&format!("hepta.authbus:{delivery}")),
    ]);
    first.next_cursor = Some("next-original-page".into());
    let mut history = History::new(vec![first, page(vec![expected.clone()])]);
    let actual = find_original_item(
        "original-thread",
        "original-turn",
        OriginalItemSelection::UserInput(OriginalHumanInput::ExactDelivery(delivery)),
        &mut history,
    )
    .await
    .unwrap();
    assert_eq!(actual, expected);
    let expected_requests: Vec<_> = [None, Some("next-original-page".into())]
        .into_iter()
        .map(|cursor| ThreadItemsListParams {
            thread_id: "original-thread".into(),
            turn_id: Some("original-turn".into()),
            cursor,
            limit: Some(128),
            sort_direction: Some(SortDirection::Asc),
        })
        .collect();
    assert_eq!(
        serde_json::to_value(&history.requests).unwrap(),
        serde_json::to_value(expected_requests).unwrap()
    );
    assert!(history.pages.is_empty());
}

#[tokio::test]
async fn missing_paired_delivery_never_substitutes_another_message_or_tool() {
    let delivery = Digest32::of_bytes(b"missing original delivery");
    let mut direct = user(delivery);
    if let ThreadItem::UserMessage { client_id, .. } = &mut direct {
        *client_id = None;
    }
    let mut history = History::new(vec![page(vec![
        user(Digest32::of_bytes(b"different delivery")),
        direct,
        call(&format!("hepta.authbus:{delivery}")),
    ])]);
    assert!(
        find_original_item(
            "original-thread",
            "original-turn",
            OriginalItemSelection::UserInput(OriginalHumanInput::ExactDelivery(delivery)),
            &mut history
        )
        .await
        .is_err()
    );
    assert_eq!(history.requests.len(), 1);
}

#[tokio::test]
async fn an_exact_delivery_does_not_bypass_page_scope_or_size() {
    let delivery = Digest32::of_bytes(b"original delivery");
    let mut foreign = page(vec![user(delivery), user(Digest32::of_bytes(b"foreign"))]);
    foreign.data[1].turn_id = "another-turn".into();
    let oversized = page(vec![user(delivery); 129]);
    for rejected in [foreign, oversized] {
        let mut history = History::new(vec![rejected]);
        assert!(
            find_original_item(
                "original-thread",
                "original-turn",
                OriginalItemSelection::UserInput(OriginalHumanInput::ExactDelivery(delivery)),
                &mut history
            )
            .await
            .is_err()
        );
        assert_eq!(history.requests.len(), 1);
    }
}

#[tokio::test]
async fn exact_delivery_keeps_the_original_sixteen_page_bound() {
    let delivery = Digest32::of_bytes(b"outside the original window");
    let mut pages: Vec<_> = (0..16)
        .map(|i| {
            let mut empty = page(vec![]);
            empty.next_cursor = Some(format!("original-page-{i}"));
            empty
        })
        .collect();
    pages.push(page(vec![user(delivery)]));
    let mut history = History::new(pages);
    assert!(
        find_original_item(
            "original-thread",
            "original-turn",
            OriginalItemSelection::UserInput(OriginalHumanInput::ExactDelivery(delivery)),
            &mut history
        )
        .await
        .is_err()
    );
    assert_eq!(history.requests.len(), 16);
    assert_eq!(history.pages.len(), 1);
}

#[tokio::test]
async fn ordinary_notes_keep_first_user_first_replace_and_exact_call_selection() {
    let first = user(Digest32::of_bytes(b"first original human input"));
    let later = user(Digest32::of_bytes(b"later original human input"));
    let mut namespaced = call("namespaced");
    if let ThreadItem::DynamicToolCall { namespace, .. } = &mut namespaced {
        *namespace = Some("other-tool-owner".into());
    }
    for (selection, expected) in [
        (
            OriginalItemSelection::UserInput(OriginalHumanInput::First),
            first.clone(),
        ),
        (OriginalItemSelection::FirstReplace, call("first-write")),
        (
            OriginalItemSelection::Call("later-write"),
            call("later-write"),
        ),
    ] {
        let mut history = History::new(vec![page(vec![
            first.clone(),
            later.clone(),
            namespaced.clone(),
            call("first-write"),
            call("later-write"),
        ])]);
        assert_eq!(
            find_original_item("original-thread", "original-turn", selection, &mut history)
                .await
                .unwrap(),
            expected
        );
        assert_eq!(history.requests.len(), 1);
    }
}
