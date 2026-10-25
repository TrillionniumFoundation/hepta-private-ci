//! Original widget actions and capabilities, scoped to the rendered room.
use super::NativeApprovalDecision;
use super::NativeApprovalView;
use super::NativeChatAvailability;
use crate::presentation::RoomKey;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::*;

#[derive(Clone, Debug, Default)]
pub(crate) enum ChatIntent {
    #[default]
    None,
    Submit(RoomKey),
    Interrupt(RoomKey),
    EarlierHistory(RoomKey),
    LatestHistory(RoomKey),
    Approval(RoomKey, String, NativeApprovalDecision),
}

#[derive(Clone, Default, PartialEq, Eq)]
pub(crate) struct Controls {
    pub(crate) room: Option<RoomKey>,
    pub(crate) availability: NativeChatAvailability,
    pub(crate) approval: Option<NativeApprovalView>,
}

impl Controls {
    pub(crate) fn permits_submit(&self, room: RoomKey, workspace: &ChatWorkspace) -> bool {
        self.room == Some(room)
            && room.epoch == workspace.presentation_epoch()
            && room.local_id == workspace.active_id()
            && self.availability.can_submit
            && !workspace.composing
            && workspace.draft().status != hepta_control_core::chat::ComposeStatus::InputLimit
            && !workspace.draft().text.trim().is_empty()
            && workspace.draft().text.len() <= hepta_control_core::chat_owner::MAX_SIGNED_TEXT_BYTES
    }

    pub(crate) fn permits_interrupt(&self, room: RoomKey, workspace: &ChatWorkspace) -> bool {
        self.room == Some(room)
            && room.epoch == workspace.presentation_epoch()
            && room.local_id == workspace.active_id()
            && self.availability.can_interrupt
            && !workspace.composing
    }

    pub(crate) fn permits_earlier_history(&self, room: RoomKey, workspace: &ChatWorkspace) -> bool {
        self.room == Some(room)
            && room.epoch == workspace.presentation_epoch()
            && room.local_id == workspace.active_id()
            && !workspace.composing
            && self.availability.can_load_earlier
    }

    pub(crate) fn permits_latest_history(&self, room: RoomKey, workspace: &ChatWorkspace) -> bool {
        self.room == Some(room)
            && room.epoch == workspace.presentation_epoch()
            && room.local_id == workspace.active_id()
            && !workspace.composing
            && self.availability.can_load_latest
    }

    pub(crate) fn permits_approval(
        &self,
        room: RoomKey,
        id: &str,
        decision: NativeApprovalDecision,
        workspace: &ChatWorkspace,
    ) -> bool {
        self.room == Some(room)
            && room.epoch == workspace.presentation_epoch()
            && room.local_id == workspace.active_id()
            && !workspace.composing
            && self.approval.as_ref().is_some_and(|approval| {
                approval.id == id
                    && !approval.busy
                    && match decision {
                        NativeApprovalDecision::AcceptOnce => approval.can_accept,
                        NativeApprovalDecision::Decline => approval.can_decline,
                    }
            })
    }
}

#[derive(Default)]
pub(crate) struct RenderedControls {
    last: Option<(WidgetUid, bool, bool, bool, bool)>,
    approval: Option<NativeApprovalView>,
}

impl RenderedControls {
    pub(crate) fn draw(
        &mut self,
        cx: &mut Cx,
        view: &View,
        workspace: &ChatWorkspace,
        room: RoomKey,
    ) {
        let controls = cx.global::<Controls>().clone();
        let mut approval = controls.approval.clone();
        if let Some(view) = &mut approval {
            view.can_accept = controls.permits_approval(
                room,
                &view.id,
                NativeApprovalDecision::AcceptOnce,
                workspace,
            );
            view.can_decline = controls.permits_approval(
                room,
                &view.id,
                NativeApprovalDecision::Decline,
                workspace,
            );
        }
        if self.approval != approval {
            view.view(cx, ids!(original_approval))
                .set_visible(cx, approval.is_some());
            if let Some(approval) = &approval {
                view.label(cx, ids!(original_approval_title))
                    .set_text(cx, &approval.title);
                view.label(cx, ids!(original_approval_details))
                    .set_text(cx, &approval.details);
                view.button(cx, ids!(original_approval_accept))
                    .set_enabled(cx, approval.can_accept);
                view.button(cx, ids!(original_approval_decline))
                    .set_enabled(cx, approval.can_decline);
            }
            self.approval = approval;
        }
        let send = controls.permits_submit(room, workspace);
        let interrupt = controls.permits_interrupt(room, workspace);
        let earlier = controls.permits_earlier_history(room, workspace);
        let latest = controls.permits_latest_history(room, workspace);
        let button = view.button(cx, ids!(send_message_button));
        let key = (button.widget_uid(), send, interrupt, earlier, latest);
        if self.last != Some(key) {
            button.set_enabled(cx, send);
            view.button(cx, ids!(interrupt_message_button))
                .set_enabled(cx, interrupt);
            view.button(cx, ids!(interrupt_message_button))
                .set_visible(cx, interrupt);
            view.view(cx, ids!(history_navigation))
                .set_visible(cx, earlier || latest);
            view.button(cx, ids!(earlier_history_button))
                .set_visible(cx, earlier);
            view.button(cx, ids!(earlier_history_button))
                .set_enabled(cx, earlier);
            view.button(cx, ids!(latest_history_button))
                .set_visible(cx, latest);
            view.button(cx, ids!(latest_history_button))
                .set_enabled(cx, latest);
            self.last = Some(key);
        }
    }
}

/// Returns true only when the original widgets emitted an authenticated-host
/// intent. The receiver revalidates it after the ordinary widget dispatch.
pub(crate) fn dispatch(
    cx: &mut Cx,
    view: &View,
    actions: &Actions,
    returned: bool,
    workspace: &ChatWorkspace,
    room: RoomKey,
) -> bool {
    let controls = cx.global::<Controls>().clone();
    if let Some(approval) = &controls.approval {
        for (button, decision) in [
            (
                view.button(cx, ids!(original_approval_accept)),
                NativeApprovalDecision::AcceptOnce,
            ),
            (
                view.button(cx, ids!(original_approval_decline)),
                NativeApprovalDecision::Decline,
            ),
        ] {
            if button.clicked(actions)
                && controls.permits_approval(room, &approval.id, decision, workspace)
            {
                cx.widget_action(
                    view.widget_uid(),
                    ChatIntent::Approval(room, approval.id.clone(), decision),
                );
                return true;
            }
        }
    }
    if (returned || view.button(cx, ids!(send_message_button)).clicked(actions))
        && controls.permits_submit(room, workspace)
    {
        cx.widget_action(view.widget_uid(), ChatIntent::Submit(room));
        return true;
    }
    if view
        .button(cx, ids!(interrupt_message_button))
        .clicked(actions)
        && controls.permits_interrupt(room, workspace)
    {
        cx.widget_action(view.widget_uid(), ChatIntent::Interrupt(room));
        return true;
    }
    if view
        .button(cx, ids!(earlier_history_button))
        .clicked(actions)
        && controls.permits_earlier_history(room, workspace)
    {
        cx.widget_action(view.widget_uid(), ChatIntent::EarlierHistory(room));
        return true;
    }
    if view
        .button(cx, ids!(latest_history_button))
        .clicked(actions)
        && controls.permits_latest_history(room, workspace)
    {
        cx.widget_action(view.widget_uid(), ChatIntent::LatestHistory(room));
        return true;
    }
    false
}

#[cfg(test)]
#[path = "chat_controls_tests.rs"]
mod tests;
