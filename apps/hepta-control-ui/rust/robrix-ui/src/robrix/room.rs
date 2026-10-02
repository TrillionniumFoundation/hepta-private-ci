// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Source: src/home/room_screen.rs:235–383,654–740. Adapted message profile/content
// hierarchy, virtual PortalList and room timeline/composer ownership. No Matrix behavior.
use crate::presentation::{
    PresentationAction, PresentationCommand, RoomKey, TimelineStatus, TimelineWindow, apply_action,
    project,
};
use hepta_control_core::{
    chat::{ChatWorkspace, ComposeStatus},
    chat_timeline::Role,
};
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 mod.widgets.Message = View {
  width: Fill height: Fit margin: 0 flow: Down spacing: 0
  body := View {
   width: Fill height: Fit flow: Right
   padding: Inset{top: 0, bottom: 10, left: 10, right: 10}
   profile := View {
    align: Align{x: 0.5, y: 0.0} width: 65 height: Fit
    margin: Inset{top: 4.5, right: 10} flow: Down
    avatar := Label {width: 48 height: 48 text: "H" draw_text.color: COLOR_TEXT}
   }
   content := View {
    width: Fill height: Fit flow: Down padding: 0
    username := Label {
     width: Fill max_lines: 1 text_overflow: Ellipsis
     margin: Inset{bottom: 9, top: 20, right: 10}
     draw_text +: {text_style: USERNAME_TEXT_STYLE {} color: COLOR_TEXT}
    }
    message := Label {
     width: Fill height: Fit flow: Flow.Right{wrap: true}
     draw_text +: {text_style: MESSAGE_TEXT_STYLE {} color: COLOR_TEXT}
    }
    send_status_indicator := Label {width: Fill draw_text.color: TIMESTAMP_TEXT_COLOR}
   }
  }
 }
 mod.widgets.Timeline = View {
  width: Fill height: Fill align: Align{x: 0.5, y: 0.0} flow: Overlay new_batch: true
  list := PortalList {
   height: Fill width: Fill flow: Down
   scroll_bar: ListScrollBar {}
   auto_tail: true bounce_at_start: false bounce_at_end: true
   emit_scroll_actions: true reached_start_margin: 2
   Message := mod.widgets.Message {}
  }
 }
 mod.widgets.RoomScreen = #(RoomScreen::register_widget(vm)) {
  width: Fill height: Fill cursor: MouseCursor.Default flow: Down spacing: 0
  presentation_note := Label {visible: false width: Fill padding: 10 flow: Flow.Right{wrap:true} draw_text.color: COLOR_TEXT}
  room_actions := Label {width: Fill padding: 16 text: "New conversation" draw_text.color: COLOR_TEXT}
  room_screen_wrapper := SolidView {
   width: Fill height: Fill flow: Overlay draw_bg.color: COLOR_PRIMARY_DARKER
   timeline_and_input_bar := View {
    width: Fill height: Fill flow: Down
    empty_state := Label {width: Fill height: Fit padding: 24 flow: Flow.Right{wrap: true} draw_text.color: COLOR_TEXT text: "Start with a local draft. No authenticated conversation history is available."}
    timeline := mod.widgets.Timeline {}
    jump_to_latest := Button {visible: false text: "Jump to latest"}
    room_input_bar := mod.widgets.RoomInputBar {}
   }
  }
 }
}
#[derive(Default)]
struct RoomViewMemory {
    positions: std::collections::HashMap<RoomKey, (usize, f64, bool)>,
    last_widget: Option<WidgetUid>,
    epoch: Option<u64>,
}
#[derive(Script, ScriptHook, Widget)]
pub struct RoomScreen {
    #[deref]
    view: View,
    #[rust]
    active_key: Option<RoomKey>,
}
impl Widget for RoomScreen {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        self.view.handle_event(cx, event, scope);
        let Some(workspace) = scope.data.get_mut::<ChatWorkspace>() else {
            return;
        };
        let Some(source) = self.active_key else {
            return;
        };
        let input = self.view.text_input(cx, ids!(message_input));
        let mut apply = |command| apply_action(workspace, PresentationAction { source, command });
        apply(PresentationCommand::SetComposing(input.is_composing()));
        if let Event::Actions(actions) = event {
            let list = self.view.portal_list(cx, ids!(list));
            if list.scrolled(actions) {
                apply(PresentationCommand::UserScrolled {
                    at_end: list.is_at_end(),
                });
            }
            if self.view.button(cx, ids!(jump_to_latest)).clicked(actions) {
                apply(PresentationCommand::JumpToLatest);
                list.scroll_to_end(cx);
            }
            if let Some(text) = input.changed(actions) {
                apply(PresentationCommand::Edit(text));
                self.view.redraw(cx);
            }
            if input.returned(actions).is_some() && !input.is_composing() {
                apply(PresentationCommand::RequestSend);
                self.view.redraw(cx);
            }
        }
    }
    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
        if let Some(workspace) = scope.data.get_mut::<ChatWorkspace>() {
            let key = RoomKey {
                epoch: workspace.presentation_epoch(),
                local_id: workspace.active_id(),
            };
            let widget_id = self.widget_uid();
            let switch_view = cx.global::<RoomViewMemory>().last_widget != Some(widget_id);
            if self.active_key != Some(key) || switch_view {
                let list = self.view.portal_list(cx, ids!(list));
                let memory = cx.global::<RoomViewMemory>();
                if memory.epoch != Some(key.epoch) {
                    memory.positions.clear();
                    memory.epoch = Some(key.epoch);
                }
                let saved = memory.positions.get(&key).copied();
                memory.last_widget = Some(widget_id);
                if let Some((first, offset, tail)) = saved {
                    list.set_first_id_and_scroll(first, offset);
                    list.set_tail_range(tail);
                } else {
                    list.set_first_id_and_scroll(0, 0.0);
                    list.set_tail_range(true);
                }
                let input = self.view.text_input(cx, ids!(message_input));
                // The upstream save/restore boundary carries undo state. A fresh state here
                // prevents previous-room/principal undo from revealing another draft.
                if self.active_key.is_some_and(|old| old.epoch != key.epoch) {
                    cx.set_key_focus(Area::Empty);
                }
                input.restore_state(cx, TextInputState::default());
                input.set_text(cx, &workspace.draft().text);
                input.set_submit_on_enter(true);
                self.active_key = Some(key);
            }
            let input = self.view.text_input(cx, ids!(message_input));
            if !input.is_composing() && input.text() != workspace.draft().text {
                input.restore_state(cx, TextInputState::default());
                input.set_text(cx, &workspace.draft().text);
            }
            let presentation = project(
                workspace,
                (Cx::time_now() * 1000.0) as u64,
                TimelineWindow::default(),
            );
            self.view
                .label(cx, ids!(presentation_note))
                .set_visible(cx, presentation.presentation_note.is_some());
            self.view
                .label(cx, ids!(presentation_note))
                .set_text(cx, presentation.presentation_note.unwrap_or(""));
            let status = match presentation.composer.status {
                ComposeStatus::InputLimit => {
                    "Draft exceeds the input limit or contains an unsupported NUL. Last valid text retained."
                }
                ComposeStatus::TransportUnavailable => {
                    "Send unavailable. Nothing was dispatched; the draft remains local."
                }
                ComposeStatus::LocalDraft => presentation.composer.owner_status,
            };
            self.view
                .label(cx, ids!(cannot_send_notice))
                .set_text(cx, status);
            self.view
                .button(cx, ids!(jump_to_latest))
                .set_visible(cx, !presentation.timeline.stick_to_bottom);
            self.view.label(cx, ids!(room_actions)).set_text(
                cx,
                workspace
                    .title_for(workspace.active_id())
                    .unwrap_or("New conversation"),
            );
            let show_notice = presentation.timeline.empty_state.is_some()
                || presentation.timeline.status == TimelineStatus::ResyncRequired;
            self.view
                .widget(cx, ids!(empty_state))
                .set_visible(cx, show_notice);
            self.view.label(cx, ids!(empty_state)).set_text(cx, if presentation.timeline.status == TimelineStatus::ResyncRequired {"History is incomplete. Waiting for an authoritative refresh; partial output is unconfirmed."} else {"Start with a local draft. No authenticated conversation history is available."});
        }
        while let Some(widget) = self.view.draw_walk(cx, scope, walk).step() {
            let portal = widget.as_portal_list();
            let Some(mut list) = portal.borrow_mut() else {
                continue;
            };
            let Some(workspace) = scope.data.get::<ChatWorkspace>() else {
                continue;
            };
            let count = project(
                workspace,
                (Cx::time_now() * 1000.0) as u64,
                TimelineWindow::default(),
            )
            .timeline
            .total;
            list.set_item_range(cx, 0, count);
            while let Some(index) = list.next_visible_item(cx) {
                let presentation = project(
                    workspace,
                    (Cx::time_now() * 1000.0) as u64,
                    TimelineWindow::Range {
                        start: index,
                        limit: 1,
                    },
                );
                let Some(message) = presentation.timeline.messages.first() else {
                    continue;
                };
                let item = list.item(cx, index, id!(Message));
                let (name, initial) = match message.role {
                    Role::User => ("You", "Y"),
                    Role::Assistant => ("Assistant", "H"),
                    Role::System => ("System", "S"),
                };
                item.label(cx, ids!(username)).set_text(cx, name);
                item.label(cx, ids!(avatar)).set_text(cx, initial);
                item.label(cx, ids!(message)).set_text(cx, message.text);
                item.label(cx, ids!(send_status_indicator))
                    .set_text(cx, message.status);
                item.draw_all(cx, &mut Scope::empty());
            }
        }
        if let Some(key) = self.active_key {
            let list = self.view.portal_list(cx, ids!(list));
            if let Some(inner) = list.borrow() {
                cx.global::<RoomViewMemory>().positions.insert(
                    key,
                    (inner.first_id(), inner.first_scroll(), inner.is_at_end()),
                );
            }
        }
        DrawStep::done()
    }
}
