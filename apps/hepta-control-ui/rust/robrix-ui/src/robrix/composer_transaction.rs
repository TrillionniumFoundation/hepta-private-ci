//! Roll back a rejected edit using the original SDK editor checkpoint.
//! Text, selection and undo history stay together and never cross a RoomKey.
use crate::presentation::ActionResult;
use crate::presentation::PresentationAction;
use crate::presentation::PresentationCommand;
use crate::presentation::RoomKey;
use crate::presentation::apply_action;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::*;

/// A focused SDK preedit awaiting an explicit full-state commit.
pub(crate) struct FullStateCommit {
    widget: WidgetUid,
    preview: String,
}

#[derive(Default)]
pub(crate) struct ComposerTransaction {
    saved: Option<(RoomKey, TextInputState)>,
}

impl ComposerTransaction {
    /// The pinned SDK emits Changed only when full-state text differs. Its
    /// composition-only commit still needs to publish the previously ignored
    /// preedit, but ordinary selection echoes and focus loss must not do so.
    pub(crate) fn capture_full_state_commit(
        cx: &Cx,
        input: &TextInputRef,
        event: &Event,
    ) -> Option<FullStateCommit> {
        let Event::TextInput(event) = event else {
            return None;
        };
        let state = event.full_state_sync.as_ref()?;
        if state.composition.is_some()
            || !input.is_composing()
            || !input.area().is_valid(cx)
            || cx.key_focus() != input.area()
        {
            return None;
        }
        Some(FullStateCommit {
            widget: input.widget_uid(),
            preview: input.text(),
        })
    }

    pub(crate) fn finish_full_state_commit(
        &mut self,
        cx: &mut Cx,
        input: &TextInputRef,
        workspace: &mut ChatWorkspace,
        source: RoomKey,
        commit: FullStateCommit,
    ) -> ActionResult {
        if input.widget_uid() != commit.widget
            || !input.area().is_valid(cx)
            || cx.key_focus() != input.area()
            || input.is_composing()
            || input.text() != commit.preview
        {
            // A text-changing commit/cancel already has the original Changed
            // action. A detached/replaced/composing editor cannot publish here.
            return ActionResult::Ignored;
        }
        self.edit(cx, input, workspace, source, commit.preview)
    }

    /// Run before the widget consumes input. Actions are delivered later, so a
    /// snapshot is valid only while the editor still equals the sole draft.
    pub(crate) fn checkpoint(
        &mut self,
        input: &TextInputRef,
        workspace: &ChatWorkspace,
        rendered: Option<RoomKey>,
    ) {
        let current = RoomKey {
            epoch: workspace.presentation_epoch(),
            local_id: workspace.active_id(),
        };
        if self.saved.as_ref().is_some_and(|(key, _)| *key != current) {
            self.saved = None;
        }
        if rendered == Some(current)
            && !input.is_composing()
            && input.text() == workspace.draft().text
        {
            self.saved = Some((current, input.save_state()));
        }
    }

    pub(crate) fn edit(
        &mut self,
        cx: &mut Cx,
        input: &TextInputRef,
        workspace: &mut ChatWorkspace,
        source: RoomKey,
        text: String,
    ) -> ActionResult {
        // The SDK owns active preedit, including its selection and undo state.
        // Publish only the later committed/cancelled edit; do not checkpoint or
        // roll back a preview while the original input method is composing.
        if input.is_composing() {
            return ActionResult::Ignored;
        }
        let result = apply_action(
            workspace,
            PresentationAction {
                source,
                command: PresentationCommand::Edit(text),
            },
        );
        if result == ActionResult::Rejected
            && let Some((key, state)) = &self.saved
            && *key == source
            && source.epoch == workspace.presentation_epoch()
            && source.local_id == workspace.active_id()
        {
            // restore_state clears preedit but retains the SDK's cursor and
            // history. Do not set_text afterwards: that would erase history.
            input.restore_state(cx, state.clone());
        }
        if result == ActionResult::Applied || result == ActionResult::Rejected {
            self.checkpoint(input, workspace, Some(source));
        }
        result
    }

    pub(crate) fn reset(&mut self) {
        self.saved = None;
    }
}

#[cfg(test)]
#[path = "composer_transaction_tests.rs"]
mod tests;
