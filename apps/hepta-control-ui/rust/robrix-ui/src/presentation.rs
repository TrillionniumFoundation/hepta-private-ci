//! Bounded, borrowed presentation for the Robrix-derived Makepad widgets.
//!
//! The application retains one `ChatWorkspace` in its Scope. This module reads
//! that same model and forwards local UI actions; it introduces no transport,
//! grant, signing, runtime, history owner, or optimistic sent-message insertion.
use hepta_control_core::chat::{Appearance, ChatWorkspace, ComposeStatus, WorkspaceTab};
use hepta_control_core::chat_owner::DeliveryView;
use hepta_control_core::chat_timeline::{MessagePhase, Role};

pub const MAX_VISIBLE_MESSAGES: usize = 128;
pub const MAX_FILTER_BYTES: usize = 512;
pub const MAX_PREVIEW_BYTES: usize = 160;
pub const MAX_NOTE_BYTES: usize = 2048;

/// Stable within one principal presentation. Epoch prevents a recycled local
/// room zero from reusing another principal's widgets or callbacks.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RoomKey {
    pub epoch: u64,
    pub local_id: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RoomSource {
    LocalDraft,
    ObservedHistory,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RoomRow<'a> {
    pub id: RoomKey,
    pub title: &'a str,
    /// Preview of the local composer only, never presented as a sent message.
    pub preview: &'a str,
    pub preview_truncated: bool,
    pub has_local_draft: bool,
    pub source: RoomSource,
    pub selected: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct MessageKey<'a> {
    pub room: RoomKey,
    pub thread_id: &'a str,
    pub turn_id: &'a str,
    pub item_id: &'a str,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MessageRow<'a> {
    pub id: MessageKey<'a>,
    pub role: Role,
    pub text: &'a str,
    pub phase: MessagePhase,
    pub status: &'static str,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimelineWindow {
    Latest { limit: usize },
    Range { start: usize, limit: usize },
}

impl Default for TimelineWindow {
    fn default() -> Self {
        Self::Latest { limit: 64 }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimelineStatus {
    LocalOnly,
    AwaitingHistory,
    Observed,
    ResyncRequired,
}

/// Empty-state UI is separate from the real message list.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EmptyState {
    LocalDraft,
    AwaitingHistory,
    NoObservedMessages,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TimelineView<'a> {
    pub messages: Vec<MessageRow<'a>>,
    pub thread_id: Option<&'a str>,
    pub history_revision: Option<u64>,
    pub event_sequence: Option<u64>,
    pub total: usize,
    pub start: usize,
    pub end: usize,
    pub has_earlier: bool,
    pub has_later: bool,
    pub status: TimelineStatus,
    pub empty_state: Option<EmptyState>,
    pub stick_to_bottom: bool,
    pub show_jump_to_latest: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ComposerView<'a> {
    pub room: RoomKey,
    pub text: &'a str,
    pub status: &'a ComposeStatus,
    pub composing: bool,
    pub has_text: bool,
    pub byte_limit: usize,
    pub can_create_draft: bool,
    pub owner_status: &'static str,
    /// Admission/queue information, never a completed assistant response.
    pub delivery: Option<&'a DeliveryView>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChatPresentation<'a> {
    pub rooms: Vec<RoomRow<'a>>,
    pub active_room: RoomKey,
    pub title: &'a str,
    pub timeline: TimelineView<'a>,
    pub composer: ComposerView<'a>,
    pub tab: WorkspaceTab,
    pub appearance: Appearance,
    pub navigation_open: bool,
    pub filter: &'a str,
    pub filter_valid: bool,
    pub presentation_note: Option<&'a str>,
    pub note_truncated: bool,
}

/// Borrow text from the already bounded core history. Only visible row metadata
/// is allocated; this is not a second transcript cache or authority snapshot.
pub fn project(
    workspace: &ChatWorkspace,
    now_ms: u64,
    window: TimelineWindow,
) -> ChatPresentation<'_> {
    let active_room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    let filter_valid =
        workspace.filter.len() <= MAX_FILTER_BYTES && !workspace.filter.contains('\0');
    let filter = prefix(&workspace.filter, MAX_FILTER_BYTES);
    let needle = filter.to_lowercase();
    let rooms = workspace
        .drafts()
        .take(hepta_control_core::chat::MAX_LOCAL_DRAFTS)
        .filter_map(|(id, draft)| {
            let title = workspace.title_for(id).unwrap_or(&draft.title);
            if !filter_valid || !title.to_lowercase().contains(&needle) {
                return None;
            }
            let preview = prefix(&draft.text, MAX_PREVIEW_BYTES);
            Some(RoomRow {
                id: RoomKey {
                    epoch: active_room.epoch,
                    local_id: id,
                },
                title,
                preview,
                preview_truncated: preview.len() != draft.text.len(),
                has_local_draft: !draft.text.trim().is_empty(),
                source: if workspace.has_history(id) {
                    RoomSource::ObservedHistory
                } else {
                    RoomSource::LocalDraft
                },
                selected: id == active_room.local_id,
            })
        })
        .collect();
    let timeline = workspace.timeline();
    let history = timeline.and_then(|value| value.history());
    let total = history.map_or(0, |value| value.messages.len());
    let (start, limit) = match window {
        TimelineWindow::Latest { limit } => {
            let limit = limit.clamp(1, MAX_VISIBLE_MESSAGES);
            (total.saturating_sub(limit), limit)
        }
        TimelineWindow::Range { start, limit } => {
            (start.min(total), limit.clamp(1, MAX_VISIBLE_MESSAGES))
        }
    };
    let end = start.saturating_add(limit).min(total);
    let messages = history.map_or_else(Vec::new, |history| {
        history.messages[start..end]
            .iter()
            .map(|message| MessageRow {
                id: MessageKey {
                    room: active_room,
                    thread_id: &history.thread_id,
                    turn_id: &message.turn_id,
                    item_id: &message.id,
                },
                role: message.role,
                text: &message.text,
                phase: message.phase,
                status: message.phase.label(),
            })
            .collect()
    });
    let status = if timeline.is_some_and(|value| value.needs_resync) {
        TimelineStatus::ResyncRequired
    } else if history.is_some() {
        TimelineStatus::Observed
    } else if timeline.is_some() {
        TimelineStatus::AwaitingHistory
    } else {
        TimelineStatus::LocalOnly
    };
    let empty_state = if total > 0 {
        None
    } else {
        Some(match status {
            TimelineStatus::LocalOnly => EmptyState::LocalDraft,
            TimelineStatus::AwaitingHistory => EmptyState::AwaitingHistory,
            TimelineStatus::Observed | TimelineStatus::ResyncRequired => {
                EmptyState::NoObservedMessages
            }
        })
    };
    let note = workspace.presentation_note.as_deref();
    let bounded_note = note.map(|text| prefix(text, MAX_NOTE_BYTES));
    ChatPresentation {
        rooms,
        active_room,
        title: workspace
            .title_for(active_room.local_id)
            .unwrap_or("Conversation"),
        timeline: TimelineView {
            messages,
            thread_id: history.map(|value| value.thread_id.as_str()),
            history_revision: history.map(|value| value.revision),
            event_sequence: history.map(|value| value.event_sequence),
            total,
            start,
            end,
            has_earlier: start > 0,
            has_later: end < total,
            status,
            empty_state,
            stick_to_bottom: timeline.is_none_or(|value| value.scroll.at_end),
            show_jump_to_latest: timeline
                .is_some_and(|value| !value.scroll.at_end && value.scroll.new_activity),
        },
        composer: ComposerView {
            room: active_room,
            text: &workspace.draft().text,
            status: &workspace.draft().status,
            composing: workspace.composing,
            has_text: !workspace.draft().text.trim().is_empty(),
            byte_limit: hepta_control_core::chat::MAX_DRAFT_BYTES,
            can_create_draft: workspace.can_create_draft(),
            owner_status: workspace.owner_status(now_ms),
            delivery: workspace.delivery_for(active_room.local_id, now_ms),
        },
        tab: workspace.tab,
        appearance: workspace.appearance,
        navigation_open: workspace.navigation_open,
        filter,
        filter_valid,
        presentation_note: bounded_note,
        note_truncated: note
            .zip(bounded_note)
            .is_some_and(|(full, short)| full.len() != short.len()),
    }
}

/// Capture the source room from the rendered view. Every action is rejected if
/// a newer principal epoch or room selection superseded that view.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PresentationAction {
    pub source: RoomKey,
    pub command: PresentationCommand,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PresentationCommand {
    SelectRoom(RoomKey),
    NewRoom,
    Edit(String),
    Clear,
    SetFilter(String),
    SetComposing(bool),
    RequestSend,
    SelectTab(WorkspaceTab),
    SetAppearance(Appearance),
    SetNavigationOpen(bool),
    UserScrolled { at_end: bool },
    JumpToLatest,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ActionResult {
    Applied,
    Ignored,
    Stale,
    Rejected,
    SendUnavailable,
}

/// Local presentation commands only. An installed host must separately use the
/// existing typed owner admission API; RequestSend never fabricates a dispatch.
pub fn apply_action(workspace: &mut ChatWorkspace, action: PresentationAction) -> ActionResult {
    if action.source.epoch != workspace.presentation_epoch()
        || action.source.local_id != workspace.active_id()
    {
        return ActionResult::Stale;
    }
    let changed = match action.command {
        PresentationCommand::SelectRoom(target) => {
            if target.epoch != action.source.epoch {
                return ActionResult::Stale;
            }
            if workspace.select(target.local_id) {
                workspace.tab = WorkspaceTab::Conversations;
                true
            } else {
                false
            }
        }
        PresentationCommand::NewRoom => {
            if workspace.new_draft() {
                workspace.tab = WorkspaceTab::Conversations;
                true
            } else {
                false
            }
        }
        PresentationCommand::Edit(text) => {
            if !workspace.edit(text) {
                return ActionResult::Rejected;
            }
            true
        }
        PresentationCommand::Clear => workspace.clear(),
        PresentationCommand::SetFilter(filter) => {
            if filter.len() > MAX_FILTER_BYTES || filter.contains('\0') {
                return ActionResult::Rejected;
            }
            workspace.filter = filter;
            true
        }
        PresentationCommand::SetComposing(composing) => {
            workspace.composing = composing;
            true
        }
        PresentationCommand::RequestSend => {
            if workspace.composing {
                return ActionResult::Ignored;
            }
            workspace.request_send();
            return ActionResult::SendUnavailable;
        }
        PresentationCommand::SelectTab(tab) => {
            if workspace.composing {
                return ActionResult::Ignored;
            }
            workspace.tab = tab;
            true
        }
        PresentationCommand::SetAppearance(appearance) => {
            workspace.appearance = appearance;
            true
        }
        PresentationCommand::SetNavigationOpen(open) => {
            workspace.navigation_open = open;
            true
        }
        PresentationCommand::UserScrolled { at_end } => {
            workspace.user_scrolled(action.source.local_id, at_end);
            true
        }
        PresentationCommand::JumpToLatest => {
            workspace.jump_to_latest(action.source.local_id);
            true
        }
    };
    if changed {
        ActionResult::Applied
    } else {
        ActionResult::Ignored
    }
}

fn prefix(text: &str, max_bytes: usize) -> &str {
    let mut end = max_bytes.min(text.len());
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    &text[..end]
}

#[cfg(test)]
#[path = "presentation_tests.rs"]
mod tests;
