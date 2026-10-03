// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Source: src/home/rooms_list_entry.rs:37–143 and FullPreview layout:169–210.
// Shader, title/preview hierarchy retained; Hepta local room inputs replace Matrix types.
use crate::presentation::{
    PresentationAction, PresentationCommand, RoomKey, RoomSource, TimelineWindow, apply_action,
    project,
};
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
    mod.widgets.RoomName = Label {
        width: Fill, height: Fit
        flow: Flow.Right{wrap: false},
        padding: 0,
        max_lines: 1
        text_overflow: Ellipsis
        draw_text +: {
            color: COLOR_TEXT,
            text_style: USERNAME_TEXT_STYLE { font_size: 12. }
        }
        text: "[Room name unknown]"
    }

    mod.widgets.RoomsListEntryTimestamp = Label {
        padding: Inset{top: 1},
        width: Fit, height: Fit
        flow: Flow.Right{wrap: false},
        draw_text +: {
            color: (TIMESTAMP_TEXT_COLOR)
            text_style: theme.font_regular { font_size: 7.5 }
        }
    }

    mod.widgets.RoomsListEntryContent = View {

        flow: Right,
        spacing: 10,
        padding: 10,
        width: Fill, height: Fit
        cursor: MouseCursor.Default,

        show_bg: true
        draw_bg +: {
            active: instance(0.0)
            hover: instance(0.0)
            color: instance(#0000)
            color_hover: instance(COLOR_LIST_ITEM_BG_HOVER)
            color_selected: instance(COLOR_ACTIVE_PRIMARY)
            color_selected_hover: instance(COLOR_ACTIVE_PRIMARY_DARKER)
            border_color: instance(#0000)
            border_size: uniform(0.0)
            border_radius: uniform(4.0)
            border_inset: uniform(vec4(0.0))

            get_color: fn() -> vec4 {
                return mix(
                    mix(self.color, self.color_hover, self.hover),
                    mix(self.color_selected, self.color_selected_hover, self.hover),
                    self.active
                )
            }

            pixel: fn() {
                let sdf = Sdf2d.viewport(self.pos * self.rect_size)
                sdf.box(
                    self.border_inset.x + self.border_size,
                    self.border_inset.y + self.border_size,
                    self.rect_size.x - (self.border_inset.x + self.border_inset.z + self.border_size * 2.0),
                    self.rect_size.y - (self.border_inset.y + self.border_inset.w + self.border_size * 2.0),
                    max(1.0, self.border_radius)
                )
                sdf.fill_keep(self.get_color())
                if self.border_size > 0.0 {
                    sdf.stroke(self.border_color, self.border_size)
                }
                return sdf.result;
            }
        }
        animator: Animator{
            selected: {
                default: @off
                off: AnimatorState{
                    from: {all: Snap}
                    apply: {
                        draw_bg: {active: 0.0}
                    }
                }
                on: AnimatorState{
                    from: {all: Snap}
                    apply: {
                        draw_bg: {active: 1.0}
                    }
                }
            }
            bg_hover: {
                default: @off
                off: AnimatorState{
                    from: {all: Snap}
                    apply: {
                        draw_bg: {hover: 0.0}
                    }
                }
                on: AnimatorState{
                    from: {all: Snap}
                    apply: {
                        draw_bg: {hover: 1.0}
                    }
                }
            }
        }
    }


 mod.widgets.RoomsListEntry = #(RoomsListEntry::register_widget(vm)) {
  ..mod.widgets.RoomsListEntryContent
  padding: 10
  avatar_frame := mod.widgets.AuroraAvatar {}
  View {
   flow: Down width: Fill height: 40 align: Align{x: 0.0, y: 0.0}
   top := View {
    width: Fill height: Fit spacing: 3 flow: Right
    room_name := mod.widgets.RoomName {text: "New conversation"}
    timestamp := mod.widgets.RoomsListEntryTimestamp {}
   }
   bottom := View {
    width: Fill height: Fill spacing: 2 flow: Right
    preview := Label {width: Fill margin: Inset{top: 2.5} text: "Local draft" draw_text.color: TIMESTAMP_TEXT_COLOR}
   }
  }
 }
 mod.widgets.RoomsSideBar = #(RoomsSideBar::register_widget(vm)) {
  width: Fill height: Fill flow: Down spacing: 12 padding: 12
  show_bg: true
  draw_bg +: {color: uniform(COLOR_SECONDARY) accent: uniform(COLOR_ROBRIX_PURPLE) pixel: fn() {
   let curve = 0.96 - 0.20 * self.pos.x * self.pos.x
   let light = max(0.0, 1.0 - abs(self.pos.y - curve) * 65.0)
   let second_curve = 1.04 - 0.29 * self.pos.x * self.pos.x
   let fine_edge = max(0.0, 1.0 - abs(self.pos.y - second_curve) * 130.0)
   let haze = max(0.0, 1.0 - length(self.pos - vec2(1.1, 0.85)))
   let upper_depth = max(0.0, 1.0 - length((self.pos - vec2(0.2, 0.0)) * vec2(0.8, 2.0)))
   return mix(self.color, self.accent, light * 0.18 + fine_edge * 0.10 + haze * haze * 0.10 + upper_depth * 0.025)
  }}
  Label {height: Fit padding: Inset{top: 14, bottom: 18} text: "H E P T A" draw_text +: {color: COLOR_TEXT text_style: theme.font_regular{font_size: 15}}}
  room_filter := TextInput {width: Fill height: 40 padding: 10 empty_text: "Find a conversation"}
  new_draft := mod.widgets.AuroraNewConversation {width: Fill text: "+  New draft"}
  list := PortalList {width: Fill height: Fill flow: Down Room := mod.widgets.RoomsListEntry {}}
  theme_switch := mod.widgets.AuroraButton {width: Fill grab_key_focus: false text: "Aurora Graphite"}
 }
}

#[derive(Clone, Debug, Default)]
struct SelectRoomAction(Option<RoomKey>);
#[derive(Script, ScriptHook, Widget, Animator)]
pub struct RoomsListEntry {
    #[source]
    source: ScriptObjectRef,
    #[deref]
    view: View,
    #[apply_default]
    animator: Animator,
    #[rust]
    room: Option<RoomKey>,
}
#[derive(Clone, Copy)]
struct RowState {
    key: RoomKey,
    selected: bool,
}
impl Widget for RoomsListEntry {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        if self.animator_handle_event(cx, event).must_redraw() {
            self.redraw(cx);
        }
        let area = self.view.area();
        let claim = event.pointer_claimed_area();
        let hit = super::hover_highlight::handle_hover_hit(self, cx, event, area, claim, false);
        match hit {
            Hit::FingerDown(_) => cx.set_key_focus(area),
            Hit::FingerUp(hit) if hit.is_over && hit.is_primary_hit() && hit.was_tap() => {
                cx.action(SelectRoomAction(self.room))
            }
            Hit::KeyDown(key)
                if key.key_code == KeyCode::ReturnKey || key.key_code == KeyCode::Space =>
            {
                cx.action(SelectRoomAction(self.room))
            }
            _ => {}
        }
        self.view.handle_event(cx, event, scope);
    }
    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
        if let Some(state) = scope.props.get::<RowState>() {
            self.room = Some(state.key);
            self.animator_toggle(
                cx,
                state.selected,
                Animate::No,
                ids!(selected.on),
                ids!(selected.off),
            );
        }
        self.view.draw_walk(cx, scope, walk)
    }
}
#[derive(Script, ScriptHook, Widget)]
pub struct RoomsSideBar {
    #[deref]
    view: View,
    #[rust]
    rendered: Option<RoomKey>,
}
impl Widget for RoomsSideBar {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        self.view.handle_event(cx, event, scope);
        let Some(workspace) = scope.data.get_mut::<ChatWorkspace>() else {
            return;
        };
        let Some(source) = self.rendered else { return };
        if let Event::Actions(actions) = event {
            if self.view.button(cx, ids!(new_draft)).clicked(actions) {
                apply_action(
                    workspace,
                    PresentationAction {
                        source,
                        command: PresentationCommand::NewRoom,
                    },
                );
                self.view.redraw(cx);
            }
            if let Some(text) = self.view.text_input(cx, ids!(room_filter)).changed(actions) {
                apply_action(
                    workspace,
                    PresentationAction {
                        source,
                        command: PresentationCommand::SetFilter(text),
                    },
                );
                self.view.redraw(cx);
            }
            for action in actions {
                if let Some(SelectRoomAction(Some(key))) = action.downcast_ref::<SelectRoomAction>()
                {
                    apply_action(
                        workspace,
                        PresentationAction {
                            source,
                            command: PresentationCommand::SelectRoom(*key),
                        },
                    );
                    self.view.redraw(cx);
                }
            }
        }
    }
    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
            let key = RoomKey {
                epoch: workspace.presentation_epoch(),
                local_id: workspace.active_id(),
            };
            let search = self.view.text_input(cx, ids!(room_filter));
            if self.rendered.is_some_and(|old| old.epoch != key.epoch) {
                search.restore_state(cx, TextInputState::default());
            }
            if search.text() != workspace.filter && !search.is_composing() {
                search.set_text(cx, &workspace.filter);
            }
            self.view
                .button(cx, ids!(new_draft))
                .set_enabled(cx, workspace.can_create_draft());
            self.view
                .button(cx, ids!(theme_switch))
                .set_enabled(cx, !workspace.composing);
            self.rendered = Some(key);
        }
        while let Some(widget) = self.view.draw_walk(cx, scope, walk).step() {
            let portal = widget.as_portal_list();
            let Some(mut list) = portal.borrow_mut() else {
                continue;
            };
            let Some(workspace) = scope.data.get::<ChatWorkspace>() else {
                continue;
            };
            let presentation = project(
                workspace,
                (Cx::time_now() * 1000.0) as u64,
                TimelineWindow::default(),
            );
            list.set_item_range(cx, 0, presentation.rooms.len());
            while let Some(index) = list.next_visible_item(cx) {
                let Some(room) = presentation.rooms.get(index) else {
                    continue;
                };
                let item = list.item(cx, index, id!(Room));
                item.label(cx, ids!(room_name)).set_text(cx, room.title);
                item.label(cx, ids!(preview)).set_text(
                    cx,
                    if room.preview.is_empty() {
                        match room.source {
                            RoomSource::ObservedHistory => "Observed history",
                            RoomSource::LocalDraft => "Local draft",
                        }
                    } else {
                        room.preview
                    },
                );
                item.draw_all(
                    cx,
                    &mut Scope::with_props(&RowState {
                        key: room.id,
                        selected: room.selected,
                    }),
                );
            }
        }
        DrawStep::done()
    }
}
