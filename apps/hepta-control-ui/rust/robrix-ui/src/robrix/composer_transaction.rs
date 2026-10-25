//! Roll back a rejected edit using the original SDK editor checkpoint.
//! Text, selection and undo history stay together and never cross a RoomKey.
use crate::presentation::ActionResult;
use crate::presentation::PresentationAction;
use crate::presentation::PresentationCommand;
use crate::presentation::RoomKey;
use crate::presentation::apply_action;
use hepta_control_core::chat::ChatWorkspace;
#[cfg(feature = "native-ime-sdk")]
use makepad_widgets::text_input::{TextEditOutcome, TextEditPhase};
use makepad_widgets::*;

#[derive(Default)]
pub(crate) struct ComposerTransaction {
    saved: Option<(RoomKey, TextInputState)>,
    #[cfg(feature = "native-ime-sdk")]
    origin: Option<(RoomKey, u64)>,
    #[cfg(feature = "native-ime-sdk")]
    sequence: u64,
}

impl ComposerTransaction {
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
            #[cfg(feature = "native-ime-sdk")]
            {
                self.origin = None;
                self.sequence = 0;
            }
        }
        #[cfg(feature = "native-ime-sdk")]
        let settled = self
            .origin
            .is_none_or(|(_, token)| input.edit_position() == (token, self.sequence));
        #[cfg(not(feature = "native-ime-sdk"))]
        let settled = true;
        if settled
            && rendered == Some(current)
            && !input.is_composing()
            && input.text() == workspace.draft().text
        {
            self.saved = Some((current, input.save_state()));
            #[cfg(feature = "native-ime-sdk")]
            if self.origin.is_none() {
                // Bind once BEFORE dispatch; queued actions carry this token.
                self.origin = Some((current, input.begin_edit_scope()));
                self.sequence = 0;
            }
        }
    }

    #[cfg(any(not(feature = "native-ime-sdk"), test))]
    pub(crate) fn edit(
        &mut self,
        cx: &mut Cx,
        input: &TextInputRef,
        workspace: &mut ChatWorkspace,
        source: RoomKey,
        text: String,
    ) -> ActionResult {
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

    #[cfg(feature = "native-ime-sdk")]
    pub(crate) fn outcome(
        &mut self,
        cx: &mut Cx,
        input: &TextInputRef,
        workspace: &mut ChatWorkspace,
        outcome: TextEditOutcome,
    ) -> ActionResult {
        let Some((source, token)) = self.origin else {
            return ActionResult::Stale;
        };
        if token != outcome.scope
            || source.epoch != workspace.presentation_epoch()
            || source.local_id != workspace.active_id()
        {
            return ActionResult::Stale;
        }
        if outcome.sequence != self.sequence + 1 {
            // Missing/reordered actions cannot establish a valid edit chain.
            self.rollback_and_rebind(cx, input, source);
            return ActionResult::Rejected;
        }
        self.sequence = outcome.sequence;
        match outcome.phase {
            TextEditPhase::Preview => ActionResult::Ignored,
            TextEditPhase::Cancelled => {
                // Snapshot was captured at cancellation, not at batch consumption.
                self.saved = Some((source, outcome.state));
                ActionResult::Ignored
            }
            TextEditPhase::Committed => {
                let Some(before) = outcome.before else {
                    self.rollback_and_rebind(cx, input, source);
                    return ActionResult::Rejected;
                };
                if before.text() != workspace.draft().text {
                    self.rollback_and_rebind(cx, input, source);
                    return ActionResult::Rejected;
                }
                // Preserve selection-only changes made after cancellation, even
                // when the next oversized edit was produced in this same batch.
                self.saved = Some((source, before));
                let result = apply_action(
                    workspace,
                    PresentationAction {
                        source,
                        command: PresentationCommand::Edit(outcome.state.text().to_owned()),
                    },
                );
                if result == ActionResult::Applied {
                    self.saved = Some((source, outcome.state));
                } else if result == ActionResult::Rejected {
                    self.rollback_and_rebind(cx, input, source);
                }
                result
            }
        }
    }

    #[cfg(feature = "native-ime-sdk")]
    fn rollback_and_rebind(&mut self, cx: &mut Cx, input: &TextInputRef, source: RoomKey) {
        if let Some((key, state)) = &self.saved
            && *key == source
        {
            input.restore_checkpoint(cx, state.clone());
        }
        // All later outcomes already produced from the rejected editor are stale.
        self.origin = Some((source, input.begin_edit_scope()));
        self.sequence = 0;
    }

    pub(crate) fn reset(&mut self) {
        self.saved = None;
        #[cfg(feature = "native-ime-sdk")]
        {
            self.origin = None;
            self.sequence = 0;
        }
    }
}

#[cfg(test)]
#[path = "composer_transaction_tests.rs"]
mod tests;
