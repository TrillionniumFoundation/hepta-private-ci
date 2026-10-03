//! Account-free data for the existing TimelineUiState ownership path.
//! There is no SDK timeline, task, subscription, or composer send context.
use super::*;

fn state(kind: TimelineKind) -> TimelineUiState {
    let (update_sender, update_receiver) = crate::timeline_channel::channel();
    drop(update_sender);
    let (request_sender, request_receiver) = tokio::sync::watch::channel(crate::sliding_sync::TimelineRequest {
        backwards_paginate: Vec::new(), is_timeline_open: false,
    });
    drop(request_receiver);
    TimelineUiState {
        kind, user_power: UserPowerLevels::all(), is_encrypted: false,
        room_members: None, fully_paginated: true, is_paginating: false,
        items: Vector::new(), index_of_last_own_sent: None,
        content_drawn_since_last_update: RangeSet::new(),
        profile_drawn_since_last_update: RangeSet::new(),
        update_receiver, request_sender,
        media_cache: MediaCache::new(None), link_preview_cache: LinkPreviewCache::new(None),
        fetched_thread_summaries: HashMap::new(), pending_thread_summary_fetches: HashSet::new(),
        saved_state: SavedState {first_index_and_scroll: Some((0, 0.0)), was_at_end: false,
            room_input_bar_state: RoomInputBarState::default()},
        message_highlight_animation_state: MessageHighlightAnimationState::default(),
        pending_reached_start: false, num_backwards_pagination_rounds_without_progress: 0,
        last_sent_read_receipt: None, last_sent_fully_read: None, tombstone_info: None,
        pending_downloads: SmallVec::new(), expanded_reply_previews: HashSet::new(),
    }
}

impl RoomScreen {
    pub(super) fn show_synthetic_timeline(&mut self, cx: &mut Cx, room: &RoomNameId, thread: Option<OwnedEventId>) {
        assert!(crate::sliding_sync::get_client().is_none(), "fixture cannot coexist with a Matrix client");
        assert!(room.room_id().server_name().is_some_and(|name| name.as_str() == "example.invalid"));
        let kind = match thread {
            Some(thread_root_event_id) => TimelineKind::Thread {room_id: room.room_id().clone(), thread_root_event_id},
            None => TimelineKind::MainRoom {room_id: room.room_id().clone()},
        };
        if self.synthetic_timeline && self.timeline_kind.as_ref() == Some(&kind) && self.tl_state.is_some() {
            return;
        }
        self.hide_timeline();
        self.synthetic_timeline = true;
        self.room_name_id = Some(room.clone());
        self.timeline_kind = Some(kind.clone());
        let owner = self.widget_uid();
        let mut timeline = match timeline_state_store::take(cx, &kind, owner) {
            timeline_state_store::TakeResult::Taken(existing) => existing,
            timeline_state_store::TakeResult::Missing => {
                timeline_state_store::mark_taken(cx, &kind, owner);
                state(kind)
            }
            timeline_state_store::TakeResult::AlreadyTaken { owner } => {
                panic!("synthetic timeline still belongs to {owner:?}");
            }
        };
        assert_eq!(timeline.request_sender.receiver_count(), 0);
        assert!(timeline.media_cache.timeline_update_sender().is_none());
        self.restore_state(cx, &mut timeline);
        self.tl_state = Some(timeline);
        let composer = self.view.room_input_bar(cx, ids!(room_input_bar));
        composer.prepare_synthetic_composer(cx);
        assert!(composer.synthetic_send_context_unset());
    }
}

#[cfg(test)]
#[path = "synthetic_timeline_tests.rs"]
mod hepta_owner_tests;
