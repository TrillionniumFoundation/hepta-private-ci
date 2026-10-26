//! Tab navigation for the original active widget tree. The pinned SDK requires
//! an existing nav-stop focus, includes disabled buttons, and cannot visit our
//! conversation rows. Run only after the original IME routing decision.
use crate::robrix::rooms::RoomsListEntry;
use makepad_widgets::*;
use std::collections::BTreeSet;

pub(crate) fn handle_tab(cx: &mut Cx, root: &WidgetRef, event: &Event) -> bool {
    let Event::KeyDown(key) = event else {
        return false;
    };
    if key.key_code != KeyCode::Tab {
        return false;
    }
    // The platform has already processed this event; this App/Dock defines no
    // Ctrl/Alt/Logo+Tab shortcut. Do not reinterpret them as unmodified Tab in
    // the SDK's modifier-insensitive fallback.
    if key.modifiers.control || key.modifiers.alt || key.modifiers.logo {
        return true;
    }
    let mut stops = Vec::new();
    let mut visited = BTreeSet::new();
    let mut stack = vec![root.clone()];
    for _ in 0..4096 {
        let Some(widget) = stack.pop() else { break };
        if !visited.insert(widget.widget_uid()) {
            continue;
        }
        let mut children = Vec::new();
        // This original SDK hook excludes inactive Dock, PageFlip and adaptive
        // branches. Window additionally requires its actual native focus.
        if !widget.visit_cancel(&mut |_, child| children.push(child)) {
            continue;
        }
        let area = widget.area();
        if area.is_valid(cx) {
            let rect = area.clipped_rect_union(cx);
            if rect.size.x <= 0.0
                || rect.size.y <= 0.0
                || ![rect.pos.x, rect.pos.y, rect.size.x, rect.size.y]
                    .iter()
                    .all(|value| value.is_finite())
            {
                continue;
            }
            let input = widget.as_text_input().borrow().is_some();
            let button = widget.as_button().borrow().map(|button| button.enabled());
            let row = widget
                .borrow::<RoomsListEntry>()
                .and_then(|row| row.rendered_room());
            if input || button.is_some() || row.is_some() {
                if button != Some(false) {
                    stops.push(widget);
                }
                continue;
            }
        }
        stack.extend(children.into_iter().rev());
    }
    // A truncated tree cannot define a complete reversible focus cycle.
    if !stack.is_empty() || stops.is_empty() {
        return true;
    }
    let current = stops.iter().position(|widget| widget.key_focus(cx));
    let next = match (current, key.modifiers.shift) {
        (Some(0) | None, true) => stops.len() - 1,
        (Some(index), true) => index - 1,
        (Some(index), false) => (index + 1) % stops.len(),
        (None, false) => 0,
    };
    let target = &stops[next];
    let input = target.as_text_input();
    if input.borrow().is_some() {
        // Restore the real editor's caret/IME visuals through its SDK API.
        input.take_key_focus(cx);
    } else {
        target.set_key_focus(cx);
    }
    root.redraw(cx);
    // Space/Return and every resulting action remain in the original widgets,
    // including their disabled, room/epoch and visible-proposal guards.
    true
}

#[cfg(test)]
#[path = "keyboard_navigation_tests.rs"]
mod tests;
