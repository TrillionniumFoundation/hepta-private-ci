use super::*;
use hepta_control_core::chat_owner::{
    CHAT_OWNER_PROTOCOL, ChatCapability, DeliveryState, OwnerDeliveryObservation,
    OwnerDeliveryState, OwnerScope, OwnerSession, SignedEnvelopeMetadata, SignedTextRef,
    SubmissionAdmission,
};
use hepta_control_core::chat_timeline::{History, Message, ProjectionError, ViewFence};

fn source(workspace: &ChatWorkspace) -> RoomKey {
    project(workspace, 1000, TimelineWindow::default()).active_room
}

fn act(workspace: &mut ChatWorkspace, command: PresentationCommand) -> ActionResult {
    let source = source(workspace);
    apply_action(workspace, PresentationAction { source, command })
}

fn scope(principal: &str) -> OwnerScope {
    OwnerScope {
        principal_id: principal.into(),
        session_id: format!("session:{principal}"),
        connection_generation: 1,
        permission_revision: 1,
        agent_id: "agent:one".into(),
        agent_generation: 3,
        thread_id: "thread:one".into(),
    }
}

fn install(workspace: &mut ChatWorkspace, principal: &str) {
    workspace
        .install_owner(
            OwnerSession {
                protocol: CHAT_OWNER_PROTOCOL.into(),
                scope: scope(principal),
                expires_at_ms: 100_000,
                capabilities: vec![
                    ChatCapability::SubmitSignedText,
                    ChatCapability::ReadDeliveryStatus,
                ],
            },
            1000,
        )
        .unwrap();
}

fn history(workspace: &mut ChatWorkspace, count: usize) -> hepta_control_core::chat::HistoryTicket {
    let ticket = workspace
        .begin_history(
            workspace.active_id(),
            "thread:one",
            ViewFence {
                owner_session: "session:human:one".into(),
                generation: 1,
            },
        )
        .unwrap();
    workspace
        .receive_history(
            &ticket,
            History {
                thread_id: "thread:one".into(),
                title: "Observed conversation".into(),
                revision: 1,
                event_sequence: 1,
                messages: (0..count)
                    .map(|index| Message {
                        id: format!("item:{index}"),
                        turn_id: format!("turn:{index}"),
                        role: Role::Assistant,
                        text: format!("Observed message {index}"),
                        phase: MessagePhase::Streaming,
                    })
                    .collect(),
            },
        )
        .unwrap();
    ticket
}

#[test]
fn default_workspace_has_one_local_room_and_separate_empty_state() {
    let workspace = ChatWorkspace::default();
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert_eq!(
        view.rooms,
        vec![RoomRow {
            id: RoomKey {
                epoch: 0,
                local_id: 0
            },
            title: "New conversation",
            preview: "",
            preview_truncated: false,
            has_local_draft: false,
            source: RoomSource::LocalDraft,
            selected: true,
        }]
    );
    assert_eq!(
        view.timeline,
        TimelineView {
            messages: vec![],
            thread_id: None,
            history_revision: None,
            event_sequence: None,
            total: 0,
            start: 0,
            end: 0,
            has_earlier: false,
            has_later: false,
            status: TimelineStatus::LocalOnly,
            empty_state: Some(EmptyState::LocalDraft),
            stick_to_bottom: true,
            show_jump_to_latest: false,
        }
    );
    assert!(view.composer.delivery.is_none());
    assert!(view.composer.owner_status.contains("unavailable"));
}

#[test]
fn edits_and_repeated_unavailable_send_never_insert_optimistic_messages() {
    let mut workspace = ChatWorkspace::default();
    assert_eq!(
        act(&mut workspace, PresentationCommand::Edit("本地草稿".into())),
        ActionResult::Applied
    );
    for _ in 0..4 {
        assert_eq!(
            act(&mut workspace, PresentationCommand::RequestSend),
            ActionResult::SendUnavailable
        );
    }
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert_eq!(view.composer.text, "本地草稿");
    assert_eq!(view.composer.status, &ComposeStatus::TransportUnavailable);
    assert_eq!(view.timeline.total, 0);
    assert!(view.timeline.messages.is_empty());
    assert!(view.rooms[0].has_local_draft);
}

#[test]
fn room_identity_survives_filtering_without_becoming_a_list_index() {
    let mut workspace = ChatWorkspace::default();
    act(&mut workspace, PresentationCommand::Edit("Alpha".into()));
    let first = source(&workspace);
    act(&mut workspace, PresentationCommand::NewRoom);
    act(&mut workspace, PresentationCommand::Edit("Beta".into()));
    let second = source(&workspace);
    act(
        &mut workspace,
        PresentationCommand::SetFilter("aLpHa".into()),
    );
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert_eq!(view.rooms.len(), 1);
    assert_eq!(view.rooms[0].id, first);
    assert_eq!(view.active_room, second);
    assert_eq!(
        act(&mut workspace, PresentationCommand::SelectRoom(first)),
        ActionResult::Applied
    );
    assert_eq!(workspace.draft().text, "Alpha");
}

#[test]
fn stale_room_and_principal_callbacks_cannot_edit_recycled_widgets() {
    let mut workspace = ChatWorkspace::default();
    act(
        &mut workspace,
        PresentationCommand::Edit("Anonymous draft".into()),
    );
    let anonymous = source(&workspace);
    install(&mut workspace, "human:one");
    let first = source(&workspace);
    assert_eq!(first.local_id, anonymous.local_id);
    assert_ne!(first.epoch, anonymous.epoch);
    assert_eq!(
        apply_action(
            &mut workspace,
            PresentationAction {
                source: anonymous,
                command: PresentationCommand::Edit("late old text".into()),
            }
        ),
        ActionResult::Stale
    );
    act(
        &mut workspace,
        PresentationCommand::Edit("Private first-person draft".into()),
    );
    history(&mut workspace, 1);
    install(&mut workspace, "human:two");
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert!(view.composer.text.is_empty());
    assert!(view.timeline.messages.is_empty());
    assert!(
        !view
            .rooms
            .iter()
            .any(|room| room.preview.contains("Private"))
    );
    assert_eq!(
        apply_action(
            &mut workspace,
            PresentationAction {
                source: first,
                command: PresentationCommand::RequestSend,
            }
        ),
        ActionResult::Stale
    );
    install(&mut workspace, "human:one");
    assert_eq!(workspace.draft().text, "Private first-person draft");
    assert!(
        project(&workspace, 1000, TimelineWindow::default())
            .timeline
            .messages
            .is_empty()
    );
}

#[test]
fn newer_room_selection_rejects_old_composer_callbacks() {
    let mut workspace = ChatWorkspace::default();
    let original = source(&workspace);
    act(&mut workspace, PresentationCommand::NewRoom);
    assert_eq!(
        apply_action(
            &mut workspace,
            PresentationAction {
                source: original,
                command: PresentationCommand::Edit("late composition".into()),
            }
        ),
        ActionResult::Stale
    );
    assert!(workspace.draft().text.is_empty());
}

#[test]
fn successful_room_navigation_returns_to_conversations_but_rejections_do_not() {
    let mut workspace = ChatWorkspace::default();
    let first = source(&workspace);
    act(
        &mut workspace,
        PresentationCommand::SelectTab(WorkspaceTab::Console),
    );
    assert_eq!(
        act(&mut workspace, PresentationCommand::NewRoom),
        ActionResult::Applied
    );
    assert_eq!(workspace.tab, WorkspaceTab::Conversations);
    act(
        &mut workspace,
        PresentationCommand::SelectTab(WorkspaceTab::Console),
    );
    assert_eq!(
        act(&mut workspace, PresentationCommand::SelectRoom(first)),
        ActionResult::Applied
    );
    assert_eq!(workspace.tab, WorkspaceTab::Conversations);
    act(
        &mut workspace,
        PresentationCommand::SelectTab(WorkspaceTab::Console),
    );
    act(&mut workspace, PresentationCommand::SetComposing(true));
    assert_eq!(
        act(&mut workspace, PresentationCommand::NewRoom),
        ActionResult::Ignored
    );
    assert_eq!(
        act(&mut workspace, PresentationCommand::SelectRoom(first)),
        ActionResult::Ignored
    );
    assert_eq!(workspace.tab, WorkspaceTab::Console);
    act(&mut workspace, PresentationCommand::SetComposing(false));
    let missing = RoomKey {
        epoch: first.epoch,
        local_id: 999,
    };
    assert_eq!(
        act(&mut workspace, PresentationCommand::SelectRoom(missing)),
        ActionResult::Ignored
    );
    let stale = RoomKey {
        epoch: first.epoch.saturating_add(1),
        local_id: first.local_id,
    };
    assert_eq!(
        act(&mut workspace, PresentationCommand::SelectRoom(stale)),
        ActionResult::Stale
    );
    assert_eq!(workspace.tab, WorkspaceTab::Console);
}

#[test]
fn virtualized_windows_are_bounded_and_keep_complete_source_ids() {
    let mut workspace = ChatWorkspace::default();
    history(&mut workspace, 200);
    let view = project(
        &workspace,
        1000,
        TimelineWindow::Latest { limit: usize::MAX },
    );
    assert_eq!(
        (view.timeline.start, view.timeline.end, view.timeline.total),
        (72, 200, 200)
    );
    assert_eq!(view.timeline.messages.len(), MAX_VISIBLE_MESSAGES);
    assert_eq!(
        view.timeline.messages[0].id,
        MessageKey {
            room: source(&workspace),
            thread_id: "thread:one",
            turn_id: "turn:72",
            item_id: "item:72",
        }
    );
    assert!(view.timeline.has_earlier);
    assert!(!view.timeline.has_later);
    assert_eq!(view.rooms[0].source, RoomSource::ObservedHistory);
    let middle = project(
        &workspace,
        1000,
        TimelineWindow::Range {
            start: 10,
            limit: 5,
        },
    );
    assert_eq!((middle.timeline.start, middle.timeline.end), (10, 15));
    assert!(middle.timeline.has_earlier && middle.timeline.has_later);
    let outside = project(
        &workspace,
        1000,
        TimelineWindow::Range {
            start: usize::MAX,
            limit: usize::MAX,
        },
    );
    assert!(outside.timeline.messages.is_empty());
    assert_eq!(outside.timeline.empty_state, None);
    assert_eq!((outside.timeline.start, outside.timeline.end), (200, 200));
}

#[test]
fn stream_updates_preserve_ids_and_resync_scroll_semantics() {
    let mut workspace = ChatWorkspace::default();
    let ticket = history(&mut workspace, 1);
    let before = project(&workspace, 1000, TimelineWindow::default())
        .timeline
        .messages[0]
        .id
        .item_id
        .to_owned();
    act(
        &mut workspace,
        PresentationCommand::UserScrolled { at_end: false },
    );
    workspace
        .receive_delta(&ticket, "item:0", 2, " + delta")
        .unwrap();
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert_eq!(view.timeline.messages[0].id.item_id, before);
    assert_eq!(view.timeline.messages[0].text, "Observed message 0 + delta");
    assert!(view.timeline.show_jump_to_latest);
    assert!(!view.timeline.stick_to_bottom);
    assert_eq!(
        workspace.receive_delta(&ticket, "item:0", 4, "dropped?"),
        Err(ProjectionError::Gap)
    );
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert_eq!(view.timeline.status, TimelineStatus::ResyncRequired);
    assert!(!view.timeline.messages[0].text.contains("dropped?"));
    act(&mut workspace, PresentationCommand::JumpToLatest);
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert!(view.timeline.stick_to_bottom);
    assert!(!view.timeline.show_jump_to_latest);
}

#[test]
fn observed_outcomes_are_preserved_without_inferred_completion() {
    let mut workspace = ChatWorkspace::default();
    let ticket = history(&mut workspace, 0);
    let phases = [
        MessagePhase::Observed,
        MessagePhase::Streaming,
        MessagePhase::Completed,
        MessagePhase::Failed,
        MessagePhase::Interrupted,
        MessagePhase::Indeterminate,
    ];
    workspace
        .receive_history(
            &ticket,
            History {
                thread_id: "thread:one".into(),
                title: "Real observed phases".into(),
                revision: 2,
                event_sequence: 2,
                messages: phases
                    .iter()
                    .enumerate()
                    .map(|(index, phase)| Message {
                        id: format!("item:{index}"),
                        turn_id: format!("turn:{index}"),
                        role: Role::Assistant,
                        text: "Owner supplied text".into(),
                        phase: *phase,
                    })
                    .collect(),
            },
        )
        .unwrap();
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert_eq!(
        view.timeline
            .messages
            .iter()
            .map(|row| row.phase)
            .collect::<Vec<_>>(),
        phases.to_vec()
    );
    assert_eq!(
        view.timeline.messages.last().unwrap().status,
        "Outcome unknown"
    );
}

#[test]
fn ime_blocks_destructive_actions_without_clearing_draft() {
    let mut workspace = ChatWorkspace::default();
    act(&mut workspace, PresentationCommand::Edit("正在输入".into()));
    act(&mut workspace, PresentationCommand::SetComposing(true));
    for command in [
        PresentationCommand::Clear,
        PresentationCommand::NewRoom,
        PresentationCommand::RequestSend,
        PresentationCommand::SelectTab(WorkspaceTab::Console),
    ] {
        assert_eq!(act(&mut workspace, command), ActionResult::Ignored);
    }
    assert_eq!(workspace.draft().text, "正在输入");
    assert_eq!(workspace.tab, WorkspaceTab::Conversations);
    act(&mut workspace, PresentationCommand::SetComposing(false));
    assert_eq!(
        act(
            &mut workspace,
            PresentationCommand::SelectTab(WorkspaceTab::Console)
        ),
        ActionResult::Applied
    );
}

#[test]
fn unicode_previews_notes_and_filter_inputs_are_bounded() {
    let mut workspace = ChatWorkspace::default();
    let text = "界".repeat(100);
    act(&mut workspace, PresentationCommand::Edit(text.clone()));
    workspace.presentation_note = Some("🙂".repeat(1000));
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert!(view.rooms[0].preview.len() <= MAX_PREVIEW_BYTES);
    assert!(view.rooms[0].preview_truncated);
    assert_eq!(view.composer.text, text);
    assert!(view.presentation_note.unwrap().len() <= MAX_NOTE_BYTES);
    assert!(view.note_truncated);
    assert_eq!(
        act(
            &mut workspace,
            PresentationCommand::SetFilter("x".repeat(MAX_FILTER_BYTES + 1))
        ),
        ActionResult::Rejected
    );
    assert!(workspace.filter.is_empty());
    workspace.filter = "x".repeat(MAX_FILTER_BYTES + 1);
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert!(!view.filter_valid);
    assert!(view.rooms.is_empty());
}

#[test]
fn queue_ack_and_lost_reply_are_composer_status_not_synthetic_messages() {
    let mut workspace = ChatWorkspace::default();
    install(&mut workspace, "human:one");
    history(&mut workspace, 0);
    act(&mut workspace, PresentationCommand::Edit("hello".into()));
    let mut payload = [0; 32];
    for (index, byte) in payload.iter_mut().enumerate() {
        *byte = u8::from_str_radix(
            &"5199ff1b793db00920c18f9b0299725de3514a1e2921ebe69c0dc97aeca09c79"
                [index * 2..index * 2 + 2],
            16,
        )
        .unwrap();
    }
    let envelope = SignedTextRef::new(
        scope("human:one"),
        SignedEnvelopeMetadata {
            host_reference: "fixture:envelope".into(),
            issuer_id: "fixture:issuer".into(),
            key_epoch: 1,
            message_id: "message:one".into(),
            sequence: 1,
            expires_at_ms: 50_000,
            payload_sha256: payload,
            envelope_sha256: [2; 32],
        },
        "hello".into(),
    )
    .unwrap();
    workspace
        .stage_authorized_text(workspace.active_id(), envelope)
        .unwrap();
    let SubmissionAdmission::Dispatch(first) = workspace
        .begin_authorized_submit(workspace.active_id(), 1000)
        .unwrap()
    else {
        panic!("expected fixture dispatch")
    };
    workspace.delivery_unknown(&first).unwrap();
    let view = project(&workspace, 1000, TimelineWindow::default());
    assert_eq!(
        view.composer.delivery.unwrap().state,
        DeliveryState::Unknown
    );
    assert!(view.timeline.messages.is_empty());
    let SubmissionAdmission::Dispatch(retry) =
        workspace.retry_exact_initial("message:one", 1001).unwrap()
    else {
        panic!("expected exact fixture retry")
    };
    workspace
        .observe_delivery(
            &retry,
            OwnerDeliveryObservation {
                observer: retry.observer().clone(),
                message_id: "message:one".into(),
                payload_sha256: payload,
                envelope_sha256: [2; 32],
                delivery_id: [3; 32],
                state: OwnerDeliveryState::QueueAccepted,
                delivery_attempts: 1,
                queue_receipt_digest: Some([4; 32]),
            },
            1001,
        )
        .unwrap();
    let view = project(&workspace, 1001, TimelineWindow::default());
    assert_eq!(
        view.composer.delivery.unwrap().state,
        DeliveryState::QueueAccepted
    );
    assert!(view.timeline.messages.is_empty());
    assert_eq!(view.composer.text, "hello");
    assert!(
        view.composer
            .owner_status
            .contains("not a completed response")
    );
}

#[test]
fn font_reflow_does_not_replace_user_scroll_intent_and_jump_restores_tail() {
    let mut workspace = ChatWorkspace::default();
    history(&mut workspace, 64);
    let mut tracker = UserScrollTracker::default();
    tracker.reset(0.0);
    assert!(workspace.timeline().unwrap().scroll.at_end);
    // A late font changes viewport geometry, with no user counter movement.
    assert_eq!(tracker.observe(0.0, false), None);
    assert!(workspace.timeline().unwrap().scroll.at_end);
    // Real wheel/drag movement produces a counter delta and leaves the end.
    let at_end = tracker.observe(180.0, false).unwrap();
    act(&mut workspace, PresentationCommand::UserScrolled { at_end });
    assert!(!workspace.timeline().unwrap().scroll.at_end);
    assert_eq!(tracker.observe(180.0, false), None);
    // Explicit Jump restores the owner's presentation intent. Reflow must not undo it.
    act(&mut workspace, PresentationCommand::JumpToLatest);
    assert!(workspace.timeline().unwrap().scroll.at_end);
    assert_eq!(tracker.observe(180.0, false), None);
    assert_eq!(tracker.observe(180.0, true), Some(true));
    // A following real upward gesture can opt out again.
    assert_eq!(tracker.observe(220.0, false), Some(false));
}

#[test]
fn tail_reflow_restore_never_overrides_new_user_input_or_scrollback() {
    let mut tracker = UserScrollTracker::default();
    assert!(tracker.restore_tail(true, 0.0, false));
    assert!(!tracker.restore_tail(true, 0.0, true));
    // A wheel event can arrive before its coalesced viewport action.
    assert!(!tracker.restore_tail(true, 80.0, false));
    assert_eq!(tracker.observe(80.0, false), Some(false));
    assert!(!tracker.restore_tail(false, 80.0, false));
    // Explicit Jump re-enables following at the same observed travel value.
    assert!(tracker.restore_tail(true, 80.0, false));
    assert!(!tracker.restore_tail(true, 81.0, false));
    assert!(!tracker.restore_tail(true, f64::NAN, false));
    assert!(!tracker.restore_tail(true, f64::INFINITY, false));
    tracker.reset(123.0);
    assert!(tracker.restore_tail(true, 123.0, false));
}

#[test]
fn tail_anchor_leaves_empty_lists_and_oversized_last_item_offsets_alone() {
    assert_eq!(UserScrollTracker::tail_anchor(0, 0), None);
    assert_eq!(UserScrollTracker::tail_anchor(0, 1), None);
    assert_eq!(UserScrollTracker::tail_anchor(52, 64), Some(63));
    // After reanchoring, the SDK can keep a negative offset into a tall last row.
    assert_eq!(UserScrollTracker::tail_anchor(63, 64), None);
    // A new room/range gets its own terminal index; no previous-room offset is used.
    assert_eq!(UserScrollTracker::tail_anchor(0, 12), Some(11));
}
