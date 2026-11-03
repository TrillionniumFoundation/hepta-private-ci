use pretty_assertions::assert_eq;

use std::collections::BTreeMap;

use codex_history::{TurnRecoveryHistoryBoundary, TurnRecoveryReplayV1, TurnRecoveryStartState};
use codex_protocol::ResponseItemId;
use codex_protocol::models::ContentItem;
use codex_protocol::protocol::{ItemStartedEvent, TurnStartedEvent};

use super::*;
use crate::hosted_turn::HostedTurnProvenance;

struct Fixture {
    thread_id: ThreadId,
    input: Vec<UserInput>,
    original: TurnRecoveryRequestBinding,
    queue: HostedQueueBinding,
    response: ResponseItem,
}

impl Fixture {
    fn new() -> CodexResult<Self> {
        let input = vec![UserInput::Text { text: "the signed original input".to_owned(), text_elements: Vec::new() }];
        let queue = HostedQueueBinding { queued_item_id: "queued-original".to_owned(), client_id: "client-original".to_owned(),
            payload_sha256: user_input_payload_sha256(&input).map_err(|error| invalid(&error.to_string()))? };
        let provenance = HostedTurnProvenance { executor_id: "fixture.original-owner".to_owned(),
            correlation: BTreeMap::from([("run".to_owned(), "original-run".to_owned())]), queue: queue.clone() };
        let boundary = TurnRecoveryHistoryBoundary { item_count: 0, prefix_sha256: "a".repeat(64) };
        let original = TurnRecoveryRequestBinding {
            turn_id: "turn-original".to_owned(), generation: 1, fingerprint_sha256: "b".repeat(64),
            history_boundary: Some(boundary.clone()), replay_applied_from_generation: None,
            replay: Some(TurnRecoveryReplayV1 { history_boundary: boundary, turn_context_sha256: "c".repeat(64),
                start: TurnRecoveryStartState { final_output_json_schema: None, parent_turn_id: None, root_turn_id: None,
                    responses_metadata_extra: provenance.metadata()? }, environments: Vec::new() }),
        };
        let response = ResponseItem::Message { id: None, role: "user".to_owned(),
            content: vec![ContentItem::InputText { text: "the signed original input".to_owned() }],
            phase: None, internal_chat_message_metadata_passthrough: None };
        Ok(Self { thread_id: ThreadId::new(), input, original, queue, response })
    }

    fn prefix(&self) -> Vec<RolloutItem> {
        vec![RolloutItem::EventMsg(EventMsg::TurnStarted(TurnStartedEvent {
            turn_id: self.original.turn_id.clone(), trace_id: None, started_at: None,
            model_context_window: None, collaboration_mode_kind: Default::default(),
        })), RolloutItem::TurnRecoveryRequestBinding(self.original.clone())]
    }

    fn body(&self) -> RolloutItem {
        let mut response = self.response.clone();
        response.set_id(Some(ResponseItemId::with_suffix("msg", "original-input")));
        response.set_turn_id_if_missing(&self.original.turn_id);
        RolloutItem::ResponseItem(response.into())
    }

    fn user(&self) -> UserMessageItem {
        UserMessageItem { id: "item-original".to_owned(), client_id: Some(self.queue.client_id.clone()), content: self.input.clone() }
    }

    fn completed_event(&self) -> EventMsg {
        EventMsg::ItemCompleted(ItemCompletedEvent { thread_id: self.thread_id, turn_id: self.original.turn_id.clone(),
            item: TurnItem::UserMessage(self.user()), started_at_ms: Some(1), completed_at_ms: 2 })
    }

    fn completed(&self) -> RolloutItem { RolloutItem::EventMsg(self.completed_event()) }

    fn started(&self) -> RolloutItem {
        RolloutItem::EventMsg(EventMsg::ItemStarted(ItemStartedEvent { thread_id: self.thread_id,
            turn_id: self.original.turn_id.clone(), item: TurnItem::UserMessage(self.user()), started_at_ms: 1 }))
    }

    fn observe(&self, suffix: Vec<RolloutItem>, mode: ThreadHistoryMode) -> CodexResult<OriginalInputState> {
        let mut scan = InputHistoryScan::new(self.thread_id, &self.original, &self.queue, &self.input, &self.response, mode)?;
        for item in self.prefix().into_iter().chain(suffix) { scan.observe(&item)?; }
        scan.finish()
    }
}

#[test]
fn original_input_absence_is_distinct_from_complete_paginated_input() {
    let fixture = Fixture::new().expect("original input fixture");
    assert_eq!(fixture.observe(Vec::new(), ThreadHistoryMode::Paginated).unwrap(), OriginalInputState::Absent);
    assert_eq!(fixture.observe(vec![fixture.body(), fixture.completed()], ThreadHistoryMode::Paginated).unwrap(),
        OriginalInputState::Complete, "ItemStarted is transient under the original persistence policy");
}

#[test]
fn partial_original_input_never_becomes_permission_to_append_again() {
    let fixture = Fixture::new().expect("original input fixture");
    for suffix in [vec![fixture.body()], vec![fixture.started()], vec![fixture.completed()], vec![fixture.body(), fixture.started()]] {
        assert!(fixture.observe(suffix, ThreadHistoryMode::Paginated).is_err());
    }
}

#[test]
fn duplicated_changed_or_reordered_original_input_is_held() {
    let fixture = Fixture::new().expect("original input fixture");
    for suffix in [vec![fixture.body(), fixture.body(), fixture.completed()],
        vec![fixture.body(), fixture.completed(), fixture.completed()],
        vec![fixture.completed(), fixture.body()]]
    {
        assert!(fixture.observe(suffix, ThreadHistoryMode::Paginated).is_err());
    }
    let mut altered = fixture.body();
    if let RolloutItem::ResponseItem(envelope) = &mut altered
        && let ResponseItem::Message { content, .. } = &mut envelope.item
    {
        *content = vec![ContentItem::InputText { text: "other input".to_owned() }];
    }
    assert!(fixture.observe(vec![altered, fixture.completed()], ThreadHistoryMode::Paginated).is_err());
    let mut changed = fixture.completed();
    if let RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) = &mut changed
        && let TurnItem::UserMessage(input) = &mut event.item
    {
        input.content = vec![UserInput::Text { text: "other input".to_owned(), text_elements: Vec::new() }];
    }
    assert!(fixture.observe(vec![fixture.body(), changed], ThreadHistoryMode::Paginated).is_err());
}

#[test]
fn original_input_cannot_cross_client_thread_turn_or_event_identity() {
    let fixture = Fixture::new().expect("original input fixture");
    for change in 0..4 {
        let mut completed = fixture.completed();
        if let RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) = &mut completed {
            if let TurnItem::UserMessage(input) = &mut event.item {
                if change == 0 { input.client_id = Some("another-client".to_owned()); }
                if change == 3 { input.id = "another-item".to_owned(); }
            }
            if change == 1 { event.thread_id = ThreadId::new(); }
            if change == 2 { event.turn_id = "another-turn".to_owned(); }
        }
        assert!(fixture.observe(vec![fixture.body(), fixture.started(), completed], ThreadHistoryMode::Paginated).is_err());
    }
}

#[test]
fn legacy_input_requires_the_original_exact_payload_projection() {
    let fixture = Fixture::new().expect("original input fixture");
    let legacy = fixture.completed_event().as_legacy_events(false).into_iter()
        .find(|event| matches!(event, EventMsg::UserMessage(_))).expect("original legacy projection");
    assert_eq!(fixture.observe(vec![fixture.body(), RolloutItem::EventMsg(legacy.clone())], ThreadHistoryMode::Legacy).unwrap(),
        OriginalInputState::Complete);
    let mut incomplete = legacy;
    if let EventMsg::UserMessage(event) = &mut incomplete { event.payload_sha256 = None; }
    assert!(fixture.observe(vec![fixture.body(), RolloutItem::EventMsg(incomplete)], ThreadHistoryMode::Legacy).is_err());
}

#[test]
fn a_missing_or_changed_original_provenance_never_classifies_input_as_absent() {
    let fixture = Fixture::new().expect("original input fixture");
    let scan = InputHistoryScan::new(fixture.thread_id, &fixture.original, &fixture.queue,
        &fixture.input, &fixture.response, ThreadHistoryMode::Paginated).unwrap();
    assert!(scan.finish().is_err());
    let mut scan = InputHistoryScan::new(fixture.thread_id, &fixture.original, &fixture.queue,
        &fixture.input, &fixture.response, ThreadHistoryMode::Paginated).unwrap();
    let mut changed = fixture.original.clone();
    changed.fingerprint_sha256 = "d".repeat(64);
    assert!(scan.observe(&RolloutItem::TurnRecoveryRequestBinding(changed)).is_err());
}
