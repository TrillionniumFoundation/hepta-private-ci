// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Source: src/home/room_screen.rs:235–383,654–740. Adapted message profile/content
// hierarchy, virtual PortalList and room timeline/composer ownership. No Matrix behavior.
use crate::presentation::{
    PresentationAction, PresentationCommand, RoomKey, TimelineStatus, TimelineWindow,
    UserScrollTracker, apply_action, project,
};
use hepta_control_core::{
    chat::{ChatWorkspace, ComposeStatus},
    chat_timeline::Role,
};
#[cfg(feature = "ui-fixtures")]
use makepad_widgets::makepad_platform::script::res::CxScriptResourceData;
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
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
  conversation_header := View {
   width: Fill height: Fit flow: Right align: Align{y: 0.5} spacing: 14
   padding: Inset{left: 20, right: 20, top: 5, bottom: 8}
   room_actions := Label {width: Fit{max: FitBound.Abs(240)} height: Fit padding: 0 max_lines: 1 text_overflow: Ellipsis text: "New conversation" draw_text.color: COLOR_TEXT}
   presentation_note := Label {visible: false width: Fill height: Fit padding: 0 flow: Flow.Right{wrap:true} draw_text.color: TIMESTAMP_TEXT_COLOR}
  }
  room_screen_wrapper := SolidView {
   width: Fill height: Fill flow: Overlay
   draw_bg +: {color: COLOR_PRIMARY_DARKER accent: uniform(COLOR_ROBRIX_PURPLE) secondary: uniform(COLOR_AURORA_CORAL)
    pixel: fn() {
     let left_glow = max(0.0, 1.0 - length((self.pos - vec2(0.0, 0.9)) * vec2(2.0, 1.0)))
     let upper_glow = max(0.0, 1.0 - length((self.pos - vec2(0.9, 0.0)) * vec2(1.0, 2.0)))
     let base = mix(self.color, self.accent, left_glow * left_glow * 0.045)
     return mix(base, self.secondary, upper_glow * upper_glow * 0.018)
    }}
   lunar_background := Image {width: Fill height: Fill visible: false fit: ImageFit.CropToFill src: crate_resource("self:resources/lunar-titanium.png") draw_bg.image_pan: vec2(0.06, 0.0)}
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
#[derive(Default)]
struct RoomViewMemory {
    #[cfg(feature = "ui-fixtures")]
    diagnostic_frames: usize,
    #[cfg(feature = "ui-fixtures")]
    font_samples:
        std::collections::HashSet<(makepad_draw::text::font_family::FontFamilyId, usize, bool)>,
    #[cfg(feature = "ui-fixtures")]
    jump_samples: std::collections::HashMap<WidgetUid, (bool, bool, bool, [u64; 4])>,
    positions: std::collections::HashMap<RoomKey, (usize, f64, bool)>,
    message_styles:
        std::collections::HashMap<WidgetUid, (crate::visual_theme::VisualTheme, bool, u64)>,
    last_widget: Option<WidgetUid>,
    epoch: Option<u64>,
}
#[derive(Script, ScriptHook, Widget)]
pub struct RoomScreen {
    #[deref]
    view: View,
    #[rust]
    active_key: Option<RoomKey>,
    #[rust]
    scroll_tracker: UserScrollTracker,
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
                // Scroll actions also report font/layout renormalization. Only
                // the SDK's user-travel counter identifies wheel/touch/bar input.
                let travel = list.user_scroll_travel();
                if let Some(at_end) = self.scroll_tracker.observe(travel, list.is_at_end()) {
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
                // Presentation order remains the owner's order. Only the row's
                // alignment and surface vary with the observed author role.
                let own = message.role == Role::User;
                let available = cx.turtle().rect().size.x.max(160.0);
                let content_width = if own {
                    ((available - 40.0) * 0.82).clamp(100.0, 680.0)
                } else {
                    (available - 90.0).clamp(70.0, 780.0)
                };
                let theme = cx.global::<crate::visual_theme::ThemeState>().selected;
                let tokens = theme.tokens();
                let bubble = own || theme != crate::visual_theme::VisualTheme::AuroraGraphite;
                let padding = if bubble { 12.0 } else { 0.0 };
                let align = if own { 1.0 } else { 0.0 };
                let color = if own { tokens.selected } else { tokens.surface };
                let border = tokens.border;
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
                        body.layout.align.x = align;
                    }
                    item.widget(cx, ids!(profile)).set_visible(cx, !own);
                    let mut content = item.widget(cx, ids!(content));
                    script_apply_eval!(cx,content,{
                        width: #(content_width) show_bg: #(bubble) padding: #(padding)
                        draw_bg +: {color: #(color) border_color: #(border)}
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
