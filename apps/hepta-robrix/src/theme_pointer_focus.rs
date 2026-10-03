//! Pointer-only focus continuity for the existing theme action. Keyboard theme
//! activation retains its own navigation focus; no observer participates here.
use super::*;

pub(super) struct Pending {
    room: SelectedRoom,
    tab: SelectedTab,
    editor: WidgetUid,
    button: WidgetUid,
    user: Option<OwnedUserId>,
}

impl App {
    pub(super) fn remember_theme_pointer(&mut self, cx: &mut Cx, event: &Event) {
        if matches!(event, Event::KeyDown(_) | Event::WindowGeomChange(_)) {
            self.theme_pointer_focus = None;
        }
        if let Event::Actions(actions) = event {
            if actions.iter().any(|a| a.downcast_ref::<LoginAction>().is_some()
                || a.downcast_ref::<LogoutAction>().is_some()
                || a.downcast_ref::<NavigationBarAction>().is_some()
                || a.downcast_ref::<AppStateAction>().is_some()) {
                self.theme_pointer_focus = None;
            }
        }
        let Event::MouseDown(mouse) = event else { return; };
        self.theme_pointer_focus = None;
        if mouse.button != MouseButton::PRIMARY || !self.app_state.logged_in
            || cx.fingers.blocked_scrolling_exception_area().is_some() { return; }
        let editor = self.ui.widget(cx, ids!(room_input_bar.mentionable_text_input.text_input));
        let area = editor.area();
        if !area.is_valid(cx) || !cx.has_key_focus(area) { return; }
        let Some(room) = self.app_state.selected_room.clone() else { return; };
        for path in [ids!(theme_a), ids!(theme_b), ids!(theme_c)] {
            let button = self.ui.widget(cx, path);
            let area = button.area();
            if area.is_valid(cx) && area.clipped_rect(cx).contains(mouse.abs) {
                self.theme_pointer_focus = Some(Pending {
                    room, tab: self.app_state.selected_tab.clone(),
                    editor: editor.widget_uid(), button: button.widget_uid(), user: current_user_id(),
                });
                break;
            }
        }
    }

    pub(super) fn restore_theme_pointer(&mut self, cx: &mut Cx, button: WidgetUid) {
        let Some(pending) = self.theme_pointer_focus.take() else { return; };
        if !self.app_state.logged_in || pending.button != button || pending.user != current_user_id()
            || self.app_state.selected_room.as_ref() != Some(&pending.room)
            || self.app_state.selected_tab != pending.tab
            || cx.fingers.blocked_scrolling_exception_area().is_some() { return; }
        let editor = self.ui.widget(cx, ids!(room_input_bar.mentionable_text_input.text_input));
        let area = editor.area();
        let focus = cx.key_focus();
        let theme_has_focus = [ids!(theme_a), ids!(theme_b), ids!(theme_c)].into_iter()
            .any(|path| { let w = self.ui.widget(cx, path); w.widget_uid() == button && w.area() == focus });
        if !focus.is_empty() && focus != area && !theme_has_focus { return; }
        if editor.widget_uid() == pending.editor && area.is_valid(cx)
            && area.clipped_rect(cx).size.x > 0.0 && area.clipped_rect(cx).size.y > 0.0 {
            cx.set_key_focus(area);
        }
    }
}
