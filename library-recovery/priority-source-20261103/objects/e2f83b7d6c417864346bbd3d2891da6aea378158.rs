//! Shared, bounded editor selection across the cached desktop/compact hosts.
use crate::editor_memory::EditorMemory;
use crate::presentation::RoomKey;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::text::selection::Selection;
use makepad_widgets::*;

struct ActiveEditor {
    room: RoomKey,
    renderer: WidgetUid,
    input: TextInputRef,
}

#[derive(Default)]
struct EditorInputs {
    epoch: Option<u64>,
    memory: EditorMemory<Selection>,
    active: Option<ActiveEditor>,
}

pub(crate) fn activate(
    cx: &mut Cx,
    renderer: WidgetUid,
    input: TextInputRef,
    workspace: &ChatWorkspace,
) {
    let room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    let state = cx.global::<EditorInputs>();
    state.memory.bind(room.epoch);
    if state.active.as_ref().is_some_and(|active| {
        active.room == room && active.renderer == renderer
    }) {
        return;
    }
    if let Some(previous) = state.active.take()
        && previous.room.epoch == room.epoch
        && !previous.input.is_composing()
        && let Some((_, draft)) = workspace.drafts().find(|(id, _)| *id == previous.room.local_id)
        && previous.input.text() == draft.text
    {
        state.memory.remember(previous.room, &draft.text, previous.input.selection());
    }
    let selection = state.memory.restore(room, &workspace.draft().text);
    state.active = Some(ActiveEditor {
        room,
        renderer,
        input: input.clone(),
    });
    // Never clone the SDK's unbounded private undo history into a room cache.
    input.restore_state(cx, TextInputState::default());
    input.set_text(cx, &workspace.draft().text);
    if let Some(selection) = selection {
        input.set_selection(cx, selection);
    }
    input.set_submit_on_enter(true);
}

/// Clear previous-epoch editor data before dispatching the next UI event.
pub(crate) fn clear_changed_epoch(cx: &mut Cx, root: &WidgetRef, workspace: &mut ChatWorkspace) {
    let epoch = workspace.presentation_epoch();
    let state = cx.global::<EditorInputs>();
    let changed_epoch = state.epoch.is_some_and(|previous| previous != epoch);
    state.epoch = Some(epoch);
    if changed_epoch {
        let previous = state.active.take();
        state.memory.bind(epoch);
        cx.set_key_focus(Area::Empty);
        // The previous composer can be hidden behind Console/navigation.
        if let Some(previous) = previous {
            previous.input.restore_state(cx, TextInputState::default());
        }
        // Clear reachable fields now. The sidebar also clears its search state
        // before drawing after an epoch change, including a previously hidden one.
        let mut stack = vec![root.clone()];
        for _ in 0..4096 {
            let Some(widget) = stack.pop() else {
                break;
            };
            if widget.borrow::<TextInput>().is_some() {
                widget.as_text_input().restore_state(cx, TextInputState::default());
            }
            widget.children(&mut |_, child| stack.push(child));
        }
    }
}

#[cfg(test)]
#[path = "editor_input_tests.rs"]
mod tests;
