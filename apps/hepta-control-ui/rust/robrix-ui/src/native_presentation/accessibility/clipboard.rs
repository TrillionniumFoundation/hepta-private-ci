//! The original SDK clipboard ticket carries no editor or focus authority.
//! Retain the original semantic request and pass the reply through the same
//! action validation a second time before the original editor is changed.

use super::NativeAccessibility;
use crate::presentation::RoomKey;
use accesskit::Action;
use accesskit::ActionData;
use accesskit::ActionRequest;
use accesskit::NodeId;
use accesskit::TextEdit;
use accesskit::TextEditOperation;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::makepad_platform::clipboard::ClipboardReadError;
use makepad_widgets::makepad_platform::clipboard::ClipboardReadTicket;
use makepad_widgets::*;
use std::time::Duration;
use std::time::Instant;

pub(super) struct PendingPaste {
    target: NodeId,
    room: RoomKey,
    window: WindowId,
    edit: TextEdit,
    ticket: ClipboardReadTicket,
    started: Instant,
}

impl PendingPaste {
    pub(super) fn new(
        target: NodeId,
        room: RoomKey,
        window: WindowId,
        edit: TextEdit,
        ticket: ClipboardReadTicket,
    ) -> Self {
        Self {
            target,
            room,
            window,
            edit,
            ticket,
            started: Instant::now(),
        }
    }
}

impl NativeAccessibility {
    pub(super) fn poll_paste(
        &mut self,
        cx: &mut Cx,
        ui: &WidgetRef,
        workspace: &mut ChatWorkspace,
    ) {
        let Some(pending) = self.pending_paste.as_ref() else {
            return;
        };
        let current = RoomKey {
            epoch: workspace.presentation_epoch(),
            local_id: workspace.active_id(),
        };
        if !self.active
            || pending.room != current
            || workspace.composing
            || Some(pending.window) != ui.window(cx, ids!(main_window)).window_id()
        {
            self.pending_paste = None;
            return;
        }
        let result = match pending.ticket.try_recv() {
            Ok(Some(value)) => value,
            Err(error) => Err(error),
            Ok(None) if pending.started.elapsed() >= Duration::from_secs(3) => {
                Err(ClipboardReadError::Timeout)
            }
            Ok(None) => return,
        };
        let Some(mut pending) = self.pending_paste.take() else {
            return;
        };
        match result {
            Ok(text) => {
                pending.edit.operation = TextEditOperation::Replace(text.into_boxed_str());
                // action() repeats current RoomKey, original visible branch,
                // input/IME state, exact text/run/range and result-size guards.
                // Only original replace_range emits Changed and records undo.
                self.action(
                    cx,
                    ui,
                    workspace,
                    ActionRequest {
                        action: Action::EditText,
                        target: pending.target,
                        data: Some(ActionData::EditText(pending.edit)),
                    },
                );
            }
            Err(error) => {
                workspace.presentation_note =
                    Some(format!("Clipboard paste unavailable: {error:?}"));
                ui.redraw(cx);
            }
        }
    }
}
