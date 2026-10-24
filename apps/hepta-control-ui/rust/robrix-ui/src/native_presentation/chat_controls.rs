//! Original widget actions and capabilities, scoped to the rendered room.
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
}

#[derive(Clone, Default, PartialEq, Eq)]
pub(crate) struct Controls {
    pub(crate) room: Option<RoomKey>,
    pub(crate) availability: NativeChatAvailability,
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
}

#[derive(Default)]
pub(crate) struct RenderedControls {
    last: Option<(WidgetUid, bool, bool)>,
}

impl RenderedControls {
    pub(crate) fn draw(&mut self, cx: &mut Cx, view: &View, workspace: &ChatWorkspace, room: RoomKey) {
        let controls = cx.global::<Controls>().clone();
        let send = controls.permits_submit(room, workspace);
        let interrupt = controls.permits_interrupt(room, workspace);
        let button = view.button(cx, ids!(send_message_button));
        let key = (button.widget_uid(), send, interrupt);
        if self.last != Some(key) {
            button.set_enabled(cx, send);
            view.button(cx, ids!(interrupt_message_button)).set_enabled(cx, interrupt);
            view.button(cx, ids!(interrupt_message_button)).set_visible(cx, interrupt);
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
    if (returned || view.button(cx, ids!(send_message_button)).clicked(actions))
        && controls.permits_submit(room, workspace)
    {
        cx.widget_action(view.widget_uid(), ChatIntent::Submit(room));
        return true;
    }
    if view.button(cx, ids!(interrupt_message_button)).clicked(actions)
        && controls.permits_interrupt(room, workspace)
    {
        cx.widget_action(view.widget_uid(), ChatIntent::Interrupt(room));
        return true;
    }
    false
}

#[cfg(test)]
#[path = "chat_controls_tests.rs"]
mod tests;
