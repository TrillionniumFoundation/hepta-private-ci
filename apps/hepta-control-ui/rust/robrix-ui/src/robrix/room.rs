// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Source: src/home/room_screen.rs:235–383,654–740. Adapted message profile/content
// hierarchy, virtual PortalList and room timeline/composer ownership. No Matrix behavior.
use crate::presentation::PresentationAction;
use crate::presentation::PresentationCommand;
use crate::presentation::RoomKey;
use crate::presentation::TimelineStatus;
use crate::presentation::TimelineWindow;
use crate::presentation::UserScrollTracker;
use crate::presentation::apply_action;
use crate::presentation::project;
use hepta_control_core::chat::ChatWorkspace;
use hepta_control_core::chat::ComposeStatus;
use hepta_control_core::chat_timeline::Role;
#[cfg(feature = "ui-fixtures")]
use makepad_widgets::makepad_platform::script::res::CxScriptResourceData;
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 mod.widgets.ConversationHeading = #(ConversationHeading::register_widget(vm)) {
  width: Fill height: 84 flow: Down
  heading_surface := View {
   width: Fill height: Fill flow: Right align: Align{y: 0.5}
   padding: Inset{left: 30, right: 24}
   show_bg: true
   draw_bg +: {
    color: COLOR_PRIMARY material: uniform(1.0)
    accent: uniform(COLOR_ROBRIX_PURPLE) secondary: uniform(COLOR_AURORA_CORAL)
    pixel: fn() {
     if self.material < 0.5 { return self.color }
     let top_edge = max(0.0, 1.0 - self.pos.y * self.rect_size.y)
     let bottom_edge = max(0.0, 1.0 - (1.0 - self.pos.y) * self.rect_size.y)
     if self.material < 1.5 {
      let mint = max(0.0, 1.0 - length((self.pos - vec2(0.15, 0.0)) * vec2(1.7, 1.5)))
      let violet = max(0.0, 1.0 - length((self.pos - vec2(0.85, 0.0)) * vec2(1.7, 1.5)))
      let face = mix(mix(self.color, self.accent, mint * mint * 0.04), self.secondary, violet * violet * 0.07)
      let edge = mix(self.accent, self.secondary, self.pos.x)
      return mix(mix(face, edge, top_edge * 0.28), #x383e49, bottom_edge * 0.6)
     }
     let warm = max(0.0, 1.0 - self.pos.y)
     let face = mix(self.color, #xffffff, warm * 0.45)
     return mix(mix(face, #xffffff, top_edge * 0.72), #x88999f, bottom_edge * 0.55)
    }
   }
   room_actions := Label {
    width: Fill height: Fit padding: 0 max_lines: 1 text_overflow: Ellipsis
    text: "New conversation"
    draw_text +: {color: COLOR_TEXT text_style: USERNAME_TEXT_STYLE{font_size: 26}}
   }
  }
 }
 mod.widgets.Message = View {
  width: Fill height: Fit margin: 0 flow: Down spacing: 0
  body := View {
   width: Fill height: Fit flow: Right
   padding: Inset{top: 10, bottom: 10, left: 20, right: 20}
   profile := View {
    align: Align{x: 0.5, y: 0.0} width: 36 height: Fit
    margin: Inset{top: 0, right: 14} flow: Down
    avatar_frame := mod.widgets.AuroraAvatar {}
   }
   content := RoundedView {
    width: Fill height: Fit flow: Down padding: 0
    show_bg: false draw_bg +: {color: COLOR_SECONDARY border_radius: 12 border_size: 1 border_color: COLOR_BORDER}
    username := Label {
     width: Fill padding: 0 max_lines: 1 text_overflow: Ellipsis
     margin: Inset{bottom: 5, top: 0, right: 10}
     draw_text +: {text_style: USERNAME_TEXT_STYLE {} color: COLOR_TEXT}
    }
    message := Label {
     width: Fill height: Fit padding: 0 flow: Flow.Right{wrap: true}
     draw_text +: {text_style: MESSAGE_TEXT_STYLE {} color: COLOR_TEXT}
    }
    send_status_indicator := Label {width: Fill padding: Inset{top: 4} draw_text.color: TIMESTAMP_TEXT_COLOR}
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
  presentation_note := Label {visible: false width: Fill height: Fit padding: Inset{left: 20, right: 20, top: 5, bottom: 8} flow: Flow.Right{wrap:true} draw_text.color: TIMESTAMP_TEXT_COLOR}
  room_screen_wrapper := SolidView {
   width: Fill height: Fill flow: Overlay
   draw_bg +: {color: COLOR_PRIMARY_DARKER material: uniform(1.0) accent: uniform(COLOR_ROBRIX_PURPLE) secondary: uniform(COLOR_AURORA_CORAL)
    pixel: fn() {
     if self.material > 1.5 {
      let upper_light = max(0.0, 1.0 - self.pos.y * 3.0)
      let bottom_shade = max(0.0, 1.0 - (1.0 - self.pos.y) * self.rect_size.y / 10.0)
      let face = mix(self.color, #xffffff, upper_light * upper_light * 0.18)
      return mix(face, #xb6afa5, bottom_shade * bottom_shade * 0.045)
     }
     if self.material > 0.5 {
      let mint = max(0.0, 1.0 - length((self.pos - vec2(0.1, 0.0)) * vec2(1.8, 5.0)))
      let violet = max(0.0, 1.0 - length((self.pos - vec2(0.9, 0.0)) * vec2(1.8, 5.0)))
      let lower_mint = max(0.0, 1.0 - length((self.pos - vec2(0.15, 1.0)) * vec2(1.8, 4.0)))
      let lower_violet = max(0.0, 1.0 - length((self.pos - vec2(0.85, 1.0)) * vec2(1.8, 4.0)))
      let face = mix(self.color, self.accent, mint * mint * 0.035 + lower_mint * lower_mint * 0.025)
      return mix(face, self.secondary, violet * violet * 0.055 + lower_violet * lower_violet * 0.035)
     }
     let left_glow = max(0.0, 1.0 - length((self.pos - vec2(0.0, 0.9)) * vec2(2.0, 1.0)))
     let upper_glow = max(0.0, 1.0 - length((self.pos - vec2(0.9, 0.0)) * vec2(1.0, 2.0)))
     let base = mix(self.color, self.accent, left_glow * left_glow * 0.045)
     return mix(base, self.secondary, upper_glow * upper_glow * 0.018)
    }}
   timeline_and_input_bar := View {
    width: Fill height: Fill flow: Down
    empty_state := Label {width: Fill height: Fit padding: 24 flow: Flow.Right{wrap: true} draw_text.color: COLOR_TEXT text: "Your conversation starts here. Write a local draft below."}
    timeline := mod.widgets.Timeline {}
    jump_to_latest := mod.widgets.AuroraButton {visible: false text: "Jump to latest"}
    room_input_bar := mod.widgets.RoomInputBar {}
   }
  }
 }
}
/// Displays the existing conversation title without changing workspace state.
#[derive(Script, ScriptHook, Widget)]
pub struct ConversationHeading {
    #[deref]
    view: View,
    #[live]
    compact: bool,
}
impl Widget for ConversationHeading {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        self.view.handle_event(cx, event, scope);
    }
    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, mut walk: Walk) -> DrawStep {
        let theme = cx.global::<crate::visual_theme::ThemeState>().selected;
        walk.height = Size::Fixed(if self.compact {
            48.0
        } else {
            theme.channel_heading_height()
        });
        if let Some(mut title) = self.view.label(cx, ids!(room_actions)).borrow_mut() {
            title.draw_text.text_style.font_size = if self.compact { 16.0 } else { 26.0 };
        }
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
            self.view.label(cx, ids!(room_actions)).set_text(
                cx,
                workspace
                    .title_for(workspace.active_id())
                    .unwrap_or("New conversation"),
            );
        }
        self.view.draw_walk(cx, scope, walk)
    }
}
#[derive(Default)]
struct RoomViewMemory {
    #[cfg(feature = "ui-fixtures")]
    diagnostic_frames: usize,
    #[cfg(feature = "ui-fixtures")]
    font_samples:
        std::collections::HashSet<(makepad_draw::text::font_family::FontFamilyId, usize, bool)>,
    #[cfg(feature = "ui-fixtures")]
    jump_samples: std::collections::HashMap<WidgetUid, (bool, bool, bool, [u64; 4])>,
    #[cfg(feature = "ui-fixtures")]
    geometry_samples: std::collections::HashMap<WidgetUid, String>,
    #[cfg(feature = "ui-fixtures")]
    geometry_last_items: std::collections::HashMap<WidgetUid, (FixtureLastIdentity, WidgetUid)>,
    #[cfg(feature = "ui-fixtures")]
    pending_geometry: Vec<FixtureGeometry>,
    positions: std::collections::HashMap<RoomKey, (usize, f64, bool)>,
    message_styles:
        std::collections::HashMap<WidgetUid, (crate::visual_theme::VisualTheme, bool, u64)>,
    last_widget: Option<WidgetUid>,
    epoch: Option<u64>,
}
#[cfg(feature = "ui-fixtures")]
#[derive(PartialEq, Eq)]
struct FixtureLastIdentity {
    room: RoomKey,
    total: usize,
    thread: String,
    turn: String,
    item: String,
    text: String,
    status: String,
}
// Capture areas in the actual room draw, then resolve their final coordinates
// only after Root has completed its parent layout/clipping. This is fixture-only
// observation; it never requests drawing or changes scroll state.
#[cfg(feature = "ui-fixtures")]
struct FixtureGeometry {
    widget: WidgetUid,
    key: RoomKey,
    total: usize,
    first: usize,
    offset: f64,
    at_end: bool,
    follow_latest: bool,
    travel: f64,
    areas: [Area; 6],
}
#[cfg(feature = "ui-fixtures")]
pub(crate) fn finish_fixture_geometry(cx: &mut Cx) {
    let pending = std::mem::take(&mut cx.global::<RoomViewMemory>().pending_geometry);
    for sample in pending {
        let rect = |area: Area, clipped: bool| -> String {
            if !area.is_valid(cx) {
                return "null".into();
            }
            let r = if clipped {
                area.clipped_rect_union(cx)
            } else {
                area.rect(cx)
            };
            let values = [r.pos.x, r.pos.y, r.size.x, r.size.y];
            if values.iter().all(|value| value.is_finite()) {
                format!("{:?}", values)
            } else {
                "null".into()
            }
        };
        let serialized = format!(
            "{{\"room\":{},\"epoch\":{},\"total\":{},\"first\":{},\"offset\":{},\"atEnd\":{},\"followLatest\":{},\"travel\":{},\"viewport\":{},\"lastRow\":{},\"lastContent\":{},\"lastBodyVisibleGlyphs\":{},\"lastStatusFirstGlyph\":{},\"lastStatusVisibleGlyphs\":{},\"composer\":{},\"layoutFinalized\":true}}",
            sample.key.local_id,
            sample.key.epoch,
            sample.total,
            sample.first,
            sample.offset,
            sample.at_end,
            sample.follow_latest,
            sample.travel,
            rect(sample.areas[0], false),
            rect(sample.areas[1], false),
            rect(sample.areas[2], false),
            rect(sample.areas[3], true),
            rect(sample.areas[4], false),
            rect(sample.areas[4], true),
            rect(sample.areas[5], false)
        );
        super::sidebar_fixture::remember_room_geometry(cx, serialized.clone());
        if cx
            .global::<RoomViewMemory>()
            .geometry_samples
            .insert(sample.widget, serialized.clone())
            .as_ref()
            != Some(&serialized)
        {
            log!(
                "HEPTA_FIXTURE_GEOMETRY frame={} {}",
                cx.redraw_id,
                serialized
            );
        }
    }
}
#[derive(Script, ScriptHook, Widget)]
pub struct RoomScreen {
    #[deref]
    view: View,
    #[rust]
    active_key: Option<RoomKey>,
    #[rust]
    scroll_tracker: UserScrollTracker,
    #[rust]
    pending_tail_redraw: Option<(NextFrame, RoomKey, f64)>,
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
        let follow_latest = workspace
            .timeline()
            .is_none_or(|timeline| timeline.scroll.at_end);
        if let Some((frame, expected_room, expected_travel)) = self.pending_tail_redraw
            && frame.is_event(event).is_some()
        {
            self.pending_tail_redraw = None;
            let list = self.view.portal_list(cx, ids!(list));
            let current_room = RoomKey {
                epoch: workspace.presentation_epoch(),
                local_id: workspace.active_id(),
            };
            let valid = source == expected_room
                && current_room == expected_room
                && follow_latest
                && list.user_scroll_travel() == expected_travel;
            #[cfg(feature = "ui-fixtures")]
            log!(
                "HEPTA_FIXTURE_TAIL_CALLBACK room={} epoch={} valid={} travel={} expected_travel={}",
                source.local_id,
                source.epoch,
                valid,
                list.user_scroll_travel(),
                expected_travel
            );
            if valid {
                // Draw-generated Actions still execute inside the SDK draw
                // dispatch, where ordinary redraw requests are ignored. Its
                // NextFrame event is outside that dispatch and can repaint the
                // cached parent without changing the user's scroll position.
                self.view.redraw(cx);
            }
        }
        let mut apply = |command| apply_action(workspace, PresentationAction { source, command });
        if let Event::Actions(actions) = event {
            let list = self.view.portal_list(cx, ids!(list));
            if list.scrolled(actions) {
                // Scroll actions also report font/layout renormalization. Only
                // the SDK's user-travel counter identifies wheel/touch/bar input.
                let travel = list.user_scroll_travel();
                if let Some(at_end) = self.scroll_tracker.observe(travel, list.is_at_end()) {
                    self.pending_tail_redraw = None;
                    let _result = apply(PresentationCommand::UserScrolled { at_end });
                    #[cfg(feature = "ui-fixtures")]
                    log!(
                        "HEPTA_FIXTURE_SCROLL_ACTION room={} epoch={} at_end={} result={:?}",
                        source.local_id,
                        source.epoch,
                        at_end,
                        _result
                    );
                    // The list action arrives after its own redraw. Repaint the
                    // parent too so the sibling Jump control reflects the new intent.
                    self.view.redraw(cx);
                } else {
                    let redraw_parent = list.borrow().is_some_and(|inner| {
                        if !inner.area().is_valid(cx) {
                            return false;
                        }
                        let size = inner.area().rect(cx).size;
                        self.scroll_tracker.request_tail_redraw(
                            follow_latest,
                            travel,
                            inner.is_at_end(),
                            inner.first_id(),
                            inner.first_scroll(),
                            [size.x, size.y],
                        )
                    });
                    // Drop the PortalList read guard before the parent redraw
                    // traverses its children and takes their mutable guards.
                    if redraw_parent && self.pending_tail_redraw.is_none() {
                        self.pending_tail_redraw = Some((cx.new_next_frame(), source, travel));
                        #[cfg(feature = "ui-fixtures")]
                        log!(
                            "HEPTA_FIXTURE_TAIL_SCHEDULE room={} epoch={} travel={}",
                            source.local_id,
                            source.epoch,
                            travel
                        );
                    }
                }
                #[cfg(feature = "ui-fixtures")]
                log!(
                    "HEPTA_FIXTURE_SCROLL travel={} at_end={} first={}",
                    travel,
                    list.is_at_end(),
                    list.first_id()
                );
            }
            if self.view.button(cx, ids!(jump_to_latest)).clicked(actions) {
                apply(PresentationCommand::JumpToLatest);
                list.set_tail_range(true);
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
                self.pending_tail_redraw = None;
                self.scroll_tracker.reset(list.user_scroll_travel());
                let memory = cx.global::<RoomViewMemory>();
                if memory.epoch != Some(key.epoch) {
                    memory.positions.clear();
                    memory.message_styles.clear();
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
            let show_notice = presentation.timeline.empty_state.is_some()
                || presentation.timeline.status == TimelineStatus::ResyncRequired;
            self.view
                .widget(cx, ids!(empty_state))
                .set_visible(cx, show_notice);
            self.view.label(cx, ids!(empty_state)).set_text(cx, if presentation.timeline.status == TimelineStatus::ResyncRequired {"History is incomplete. Waiting for an authoritative refresh; partial output is unconfirmed."} else {"Your conversation starts here. Write a local draft below."});
        }
        #[cfg(feature = "ui-fixtures")]
        let mut diagnostic_items = Vec::new();
        while let Some(widget) = self.view.draw_walk(cx, scope, walk).step() {
            let portal = widget.as_portal_list();
            let user_travel = portal.user_scroll_travel();
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
            let follow_latest = workspace
                .timeline()
                .is_none_or(|timeline| timeline.scroll.at_end);
            if count > 0
                && self
                    .scroll_tracker
                    .restore_tail(follow_latest, user_travel, list.is_at_end())
            {
                // Font/layout reflow changes row heights without changing the
                // item range. Honor the existing follow intent immediately;
                // an unprocessed user gesture must never be overwritten.
                list.set_tail_range(true);
                if let Some(last) = UserScrollTracker::tail_anchor(list.first_id(), count) {
                    list.set_first_id_and_scroll(last, 0.0);
                }
            }
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
                // Every actual role shares the same avatar/text column. Keep
                // the owner's order and role/status labels; add no identity data.
                let own = message.role == Role::User;
                let available = cx.turtle().rect().size.x.max(160.0);
                // 40 px outer padding + 36 px avatar + 14 px profile gap.
                let content_width = (available - 90.0).clamp(70.0, 720.0);
                let theme = cx.global::<crate::visual_theme::ThemeState>().selected;
                let style = (theme, own, content_width.to_bits());
                if cx
                    .global::<RoomViewMemory>()
                    .message_styles
                    .get(&item.widget_uid())
                    != Some(&style)
                {
                    // Eval intentionally does not recurse into child widgets in
                    // this SDK. Address each actual child; keep geometry typed.
                    if let Some(mut body) = item.view(cx, ids!(body)).borrow_mut() {
                        body.layout.align.x = 0.0;
                    }
                    item.widget(cx, ids!(profile))
                        .set_visible(cx, /*visible*/ true);
                    let mut content = item.widget(cx, ids!(content));
                    script_apply_eval!(cx,content,{
                        width: #(content_width) show_bg: false padding: 0
                    });
                    cx.global::<RoomViewMemory>()
                        .message_styles
                        .insert(item.widget_uid(), style);
                }
                item.label(cx, ids!(username)).set_text(cx, name);
                item.label(cx, ids!(avatar)).set_text(cx, initial);
                item.label(cx, ids!(message)).set_text(cx, message.text);
                item.label(cx, ids!(send_status_indicator))
                    .set_text(cx, message.status);
                item.draw_all(cx, &mut Scope::empty());
                #[cfg(feature = "ui-fixtures")]
                diagnostic_items.push((index, item));
            }
        }
        #[cfg(feature = "ui-fixtures")]
        for (index, item) in &diagnostic_items {
            let label = item.label(cx, ids!(message));
            if let Some(label) = label.borrow() {
                let members: Vec<_> = label
                    .draw_text
                    .text_style
                    .font_family
                    .member_ids()
                    .collect();
                type FontStore = std::rc::Rc<std::cell::RefCell<makepad_draw::text::fonts::Fonts>>;
                if cx.has_global::<FontStore>() {
                    let font_id = label.draw_text.text_style.font_family_id();
                    let store = cx.get_global::<FontStore>().clone();
                    let (family, complete) = {
                        let mut fonts = store.borrow_mut();
                        let complete = fonts.is_font_family_complete(font_id, members.len());
                        (
                            fonts
                                .is_font_family_known(font_id)
                                .then(|| fonts.get_or_load_font_family(font_id)),
                            complete,
                        )
                    };
                    if let Some(family) = family {
                        let loaded = family.fonts().len();
                        if cx
                            .global::<RoomViewMemory>()
                            .font_samples
                            .insert((font_id, loaded, complete))
                        {
                            cx.global::<RoomViewMemory>().diagnostic_frames = 0;
                            log!(
                                "HEPTA_FIXTURE_FONT_STATE index={} loaded_fonts={} complete={} members={:?}",
                                index,
                                loaded,
                                complete,
                                members
                            );
                            for resource in cx.script_data.resources.resources.borrow().iter() {
                                if !resource.abs_path.ends_with(".ttf") {
                                    continue;
                                }
                                let state = match &resource.data {
                                    CxScriptResourceData::NotLoaded => "not_loaded",
                                    CxScriptResourceData::Loading => "loading",
                                    CxScriptResourceData::Loaded(_) => "loaded",
                                    CxScriptResourceData::Error(_) => "error",
                                };
                                log!(
                                    "HEPTA_FIXTURE_FONT_RESOURCE path={} dependency={:?} state={} loaded_len={}",
                                    resource.abs_path,
                                    resource.dependency_path,
                                    state,
                                    resource.loaded_len()
                                );
                            }
                            if loaded == 0 {
                                continue;
                            }
                            for (probe, sample) in
                                [("plain", "中文输入😀"), ("mixed", "Fixture 59 中文输入😀")]
                            {
                                let shaped = family.get_or_shape(sample.into());
                                let glyphs: Vec<_> = shaped
                                    .glyphs
                                    .iter()
                                    .map(|glyph| (glyph.id, glyph.font.id()))
                                    .collect();
                                log!(
                                    "HEPTA_FIXTURE_SHAPING probe={} loaded_fonts={} glyphs={:?}",
                                    probe,
                                    loaded,
                                    glyphs
                                );
                            }
                        }
                    }
                }
            }
        }
        #[cfg(feature = "ui-fixtures")]
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
            // Observe only. No additional layout, scrolling, or redraw is requested.
            let list = self.view.portal_list(cx, ids!(list));
            let travel = list.user_scroll_travel();
            if let Some(inner) = list.borrow() {
                let total = project(workspace, 0, TimelineWindow::default())
                    .timeline
                    .total;
                let key = RoomKey {
                    epoch: workspace.presentation_epoch(),
                    local_id: workspace.active_id(),
                };
                let widget = self.widget_uid();
                let current = project(
                    workspace,
                    0,
                    TimelineWindow::Range {
                        start: total.saturating_sub(1),
                        limit: 1,
                    },
                );
                let identity =
                    current
                        .timeline
                        .messages
                        .first()
                        .map(|message| FixtureLastIdentity {
                            room: key,
                            total,
                            thread: message.id.thread_id.into(),
                            turn: message.id.turn_id.into(),
                            item: message.id.item_id.into(),
                            text: message.text.into(),
                            status: message.status.into(),
                        });
                if let Some((_, item)) = diagnostic_items
                    .iter()
                    .find(|(index, _)| *index + 1 == total)
                    && let Some(identity) = identity
                {
                    cx.global::<RoomViewMemory>()
                        .geometry_last_items
                        .insert(widget, (identity, item.widget_uid()));
                }
                let last = total
                    .checked_sub(1)
                    .and_then(|index| inner.get_item(index))
                    .map(|(_, item)| item);
                let last = last.filter(|item| {
                    let current = project(
                        workspace,
                        0,
                        TimelineWindow::Range {
                            start: total.saturating_sub(1),
                            limit: 1,
                        },
                    );
                    current.timeline.messages.first().is_some_and(|message| {
                        cx.global::<RoomViewMemory>()
                            .geometry_last_items
                            .get(&widget)
                            .is_some_and(|(identity, uid)| {
                                *uid == item.widget_uid()
                                    && identity.room == key
                                    && identity.total == total
                                    && identity.thread == message.id.thread_id
                                    && identity.turn == message.id.turn_id
                                    && identity.item == message.id.item_id
                                    && identity.text == message.text
                                    && identity.status == message.status
                            })
                    })
                });
                let area = |ids: &[LiveId]| {
                    last.as_ref()
                        .map_or(Area::Empty, |item| item.widget(cx, ids).area())
                };
                let status = area(ids!(send_status_indicator));
                let sample = FixtureGeometry {
                    widget,
                    key,
                    total,
                    first: inner.first_id(),
                    offset: inner.first_scroll(),
                    at_end: inner.is_at_end(),
                    follow_latest: workspace
                        .timeline()
                        .is_none_or(|timeline| timeline.scroll.at_end),
                    travel,
                    areas: [
                        inner.area(),
                        last.as_ref().map_or(Area::Empty, WidgetRef::area),
                        area(ids!(content)),
                        area(ids!(message)),
                        status,
                        self.view.widget(cx, ids!(room_input_bar)).area(),
                    ],
                };
                cx.global::<RoomViewMemory>().pending_geometry.push(sample);
            }
        }
        #[cfg(feature = "ui-fixtures")]
        if cx.global::<RoomViewMemory>().diagnostic_frames < 12 {
            cx.global::<RoomViewMemory>().diagnostic_frames += 1;
            for (index, item) in diagnostic_items {
                let label = item.label(cx, ids!(message));
                let area = label.area();
                // PortalList probes include culled rows with no glyph instances.
                // Do not ask the renderer for geometry that was not drawn.
                if !area.is_valid(cx) {
                    log!("HEPTA_FIXTURE_LAYOUT index={} drawn=false", index);
                    continue;
                }
                let rect = area.clipped_rect_union(cx);
                let row = item.area();
                if row.is_valid(cx) {
                    let rect = row.rect(cx);
                    log!(
                        "HEPTA_FIXTURE_ROW index={} x={} y={} width={} height={}",
                        index,
                        rect.pos.x,
                        rect.pos.y,
                        rect.size.x,
                        rect.size.y
                    );
                }
                let content = item.view(cx, ids!(content)).area();
                if content.is_valid(cx) {
                    let rect = content.rect(cx);
                    log!(
                        "HEPTA_FIXTURE_CONTENT index={} x={} y={} width={} height={}",
                        index,
                        rect.pos.x,
                        rect.pos.y,
                        rect.size.x,
                        rect.size.y
                    );
                }
                log!(
                    "HEPTA_FIXTURE_VISIBLE_GLYPHS index={} x={} y={} width={} height={}",
                    index,
                    rect.pos.x,
                    rect.pos.y,
                    rect.size.x,
                    rect.size.y
                );
            }
        }
        #[cfg(feature = "ui-fixtures")]
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
            let jump = self.view.widget(cx, ids!(jump_to_latest));
            let area = jump.area();
            let valid = area.is_valid(cx);
            let rect = if valid {
                area.rect(cx)
            } else {
                Rect::default()
            };
            let tail = workspace
                .timeline()
                .is_none_or(|timeline| timeline.scroll.at_end);
            let sample = (
                tail,
                jump.visible(),
                valid,
                [
                    rect.pos.x.to_bits(),
                    rect.pos.y.to_bits(),
                    rect.size.x.to_bits(),
                    rect.size.y.to_bits(),
                ],
            );
            if cx
                .global::<RoomViewMemory>()
                .jump_samples
                .insert(self.widget_uid(), sample)
                != Some(sample)
            {
                log!(
                    "HEPTA_FIXTURE_JUMP tail={} visible={} area_valid={} x={} y={} width={} height={}",
                    tail,
                    jump.visible(),
                    valid,
                    rect.pos.x,
                    rect.pos.y,
                    rect.size.x,
                    rect.size.y
                );
            }
        }
        if let Some(key) = self.active_key {
            let list = self.view.portal_list(cx, ids!(list));
            if let Some(inner) = list.borrow() {
                #[cfg(feature = "ui-fixtures")]
                if cx.global::<RoomViewMemory>().diagnostic_frames < 12 && inner.area().is_valid(cx)
                {
                    let viewport = inner.area().rect(cx);
                    log!(
                        "HEPTA_FIXTURE_VIEWPORT first={} offset={} at_end={} x={} y={} width={} height={}",
                        inner.first_id(),
                        inner.first_scroll(),
                        inner.is_at_end(),
                        viewport.pos.x,
                        viewport.pos.y,
                        viewport.size.x,
                        viewport.size.y
                    );
                }
                cx.global::<RoomViewMemory>().positions.insert(
                    key,
                    (
                        inner.first_id(),
                        inner.first_scroll(),
                        scope
                            .data
                            .get::<ChatWorkspace>()
                            .and_then(ChatWorkspace::timeline)
                            .is_none_or(|timeline| timeline.scroll.at_end),
                    ),
                );
            }
        }
        DrawStep::done()
    }
}
