//! Narrow compact-chat keyboard routing around the pinned SDK's known gaps.
//! No owner transport, text capture, SDK fork, or post-dispatch focus override.
use crate::ime_router::CompositionLayout;
use crate::keyboard_focus_policy::{ChatStops, ReturnIdentity, ReturnPolicy, Stop, tab_target};
use hepta_control_core::chat::{ChatWorkspace, WorkspaceTab};
use makepad_widgets::makepad_draw::nav::CxNavTreeRc;
use makepad_widgets::makepad_platform::event::finger::TouchState;
use makepad_widgets::*;

type Identity = ReturnIdentity<Area, WidgetUid>;
#[derive(Default)]
pub(crate) struct KeyboardFocus {
    returning: ReturnPolicy<Area, WidgetUid, NextFrame>,
}
#[derive(Default)]
pub(crate) struct DispatchPlan {
    pub consume_tab: bool,
    escape: Option<Identity>,
}
fn compact_chat(cx: &mut Cx, workspace: &ChatWorkspace) -> bool {
    workspace.tab == WorkspaceTab::Conversations
        && cx.global::<CompositionLayout>().variant == Some(live_id!(Mobile))
}
fn plain_key(key: &KeyEvent) -> bool {
    !key.modifiers.control && !key.modifiers.alt && !key.modifiers.logo
}
fn newer_input(event: &Event) -> bool {
    match event {
        Event::MouseDown(_)
        | Event::KeyDown(_)
        | Event::TextInput(_)
        | Event::TextCut(_)
        | Event::ImeAction(_)
        | Event::WindowLostFocus(_) => true,
        Event::TouchUpdate(touch) => touch.touches.iter().any(|p| p.state == TouchState::Start),
        _ => false,
    }
}
fn identity(cx: &mut Cx, root: &WidgetRef, workspace: &ChatWorkspace) -> Identity {
    ReturnIdentity {
        epoch: workspace.presentation_epoch(),
        room: workspace.active_id(),
        focus: cx.key_focus(),
        opener: root.widget(cx, ids!(conversations)).widget_uid(),
        search: root.widget(cx, ids!(room_filter)).widget_uid(),
    }
}
fn nav_snapshot(cx: &mut Cx, root: &WidgetRef) -> Option<(DrawListId, Vec<Stop<Area>>)> {
    if !cx.has_global::<CxNavTreeRc>() {
        return None;
    }
    let root_area = root.widget(cx, ids!(main_window)).area();
    if !root_area.is_valid(cx) {
        return None;
    }
    let draw_list = root_area.draw_list_id()?;
    let mut stops = Vec::new();
    let mut overflow = false;
    let _ = CxDraw::iterate_nav_stops(cx, draw_list, |cx, stop| {
        if stops.len() == 32 {
            overflow = true;
            return Some(Area::Empty); // Real callback short-circuit on the33rd stop.
        }
        stops.push(Stop {
            area: stop.area,
            valid: stop.area.is_valid(cx),
        });
        None
    });
    (!overflow).then_some((draw_list, stops))
}
impl KeyboardFocus {
    pub(crate) fn before_dispatch(
        &mut self,
        cx: &mut Cx,
        root: &WidgetRef,
        event: &Event,
        workspace: &ChatWorkspace,
        ime_quiet: bool,
    ) -> DispatchPlan {
        let compact = compact_chat(cx, workspace);
        let closed = compact && !workspace.navigation_open && ime_quiet;
        let current = identity(cx, root, workspace);
        self.returning.observe(current, closed, newer_input(event));
        if let Some(frame) = self.returning.frame()
            && frame.is_event(event).is_some()
            && self.returning.take_frame(frame)
        {
            let opener = root.widget(cx, ids!(conversations));
            let area = opener.area();
            if !opener.is_empty() && opener.widget_uid() == current.opener && area.is_valid(cx) {
                // Prior Draw's focus requests have settled. This request precedes
                // ordinary dispatch, so a newer legitimate handler always wins.
                cx.set_key_focus(area);
            }
        }
        let mut plan = DispatchPlan::default();
        if let Event::KeyDown(key) = event {
            if key.key_code == KeyCode::Escape
                && plain_key(key)
                && compact
                && workspace.navigation_open
                && ime_quiet
            {
                let search = root.widget(cx, ids!(room_filter));
                let opener = root.widget(cx, ids!(conversations));
                if !search.is_empty()
                    && !opener.is_empty()
                    && search.area().is_valid(cx)
                    && search.area() == current.focus
                {
                    plan.escape = Some(current);
                }
            }
            if key.key_code == KeyCode::Tab && plain_key(key) && closed {
                plan.consume_tab = self.route_tab(cx, root, key.modifiers.shift);
            }
        }
        plan
    }
    fn route_tab(&self, cx: &mut Cx, root: &WidgetRef, shift: bool) -> bool {
        let Some((draw_list, stops)) = nav_snapshot(cx, root) else {
            return false;
        };
        let conversations = root.widget(cx, ids!(conversations));
        let theme = root.widget(cx, ids!(mobile_theme_switch));
        let send = root.widget(cx, ids!(send_message_button));
        let editor = root.widget(cx, ids!(message_input));
        if conversations.is_empty() || theme.is_empty() || send.is_empty() || editor.is_empty() {
            return false;
        }
        let Some(send_enabled) = send.borrow::<Button>().map(|b| b.enabled()) else {
            return false;
        };
        let focus = cx.key_focus();
        let target = tab_target(
            &stops,
            true,
            ChatStops {
                conversations: conversations.area(),
                theme: theme.area(),
                send: send.area(),
                editor: editor.area(),
            },
            (!focus.is_empty()).then_some(focus),
            shift,
            send_enabled,
        );
        let Some(target) = target else { return false };
        // Resolve the target's own scroll stack, including reverse navigation.
        let selected = CxDraw::iterate_nav_stops(cx, draw_list, |_, stop| {
            (stop.area == target).then_some(target)
        });
        let Some((area, stack)) = selected else {
            return false;
        };
        if !area.is_valid(cx) {
            return false;
        }
        NavControl::send_trigger_to_scroll_stack(cx, stack);
        cx.set_key_focus(area);
        true
    }
    pub(crate) fn after_dispatch(
        &mut self,
        cx: &mut Cx,
        root: &WidgetRef,
        event: &Event,
        workspace: &ChatWorkspace,
        ime_quiet: bool,
        plan: DispatchPlan,
    ) {
        let eligible = compact_chat(cx, workspace) && !workspace.navigation_open && ime_quiet;
        let current = identity(cx, root, workspace);
        if let Some(source) = plan.escape
            && eligible
            && source == current
        {
            self.returning.begin(source);
        }
        self.returning.observe(current, eligible, false);
        if matches!(event, Event::Draw(_)) {
            let opener = root.widget(cx, ids!(conversations));
            let valid = !opener.is_empty()
                && opener.widget_uid() == current.opener
                && opener.area().is_valid(cx);
            if self.returning.needs_frame_after_draw(valid) {
                // Scheduling only. Never write focus after another Draw handler.
                self.returning.arm(cx.new_next_frame());
            }
        }
    }
}
