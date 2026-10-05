// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Sources: home/main_desktop_ui.rs:15–81; home/home_screen.rs:145–210.
// Retains Robrix sidebar/main Dock split, fixed sidebar tab, persistent chat/Console
// tabs and AdaptiveView/CachedWidget ownership. Matrix room factories removed.
use crate::presentation::PresentationAction;
use crate::presentation::PresentationCommand;
use crate::presentation::RoomKey;
use crate::presentation::apply_action;
use hepta_control_core::chat::ChatWorkspace;
use hepta_control_core::chat::WorkspaceTab;
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 mod.widgets.HeptaBrandBar = View {
  width: Fill height: 68 flow: Right align: Align{y: 0.5}
  padding: Inset{left: 33, right: 24} spacing: 20
  show_bg: true draw_bg.color: COLOR_PRIMARY
  brand_mark := mod.widgets.HeptaMark {width: 44 height: 44}
  brand_title := Label {text: "H E P T A" padding: 0 draw_text +: {color: COLOR_TEXT text_style: theme.font_regular{font_size: 20}}}
 }
 mod.widgets.MainConversationUI = #(MainConversationUI::register_widget(vm)) {
  width: Fill height: Fill flow: Down
  channel_heading := mod.widgets.ConversationHeading {}
  dock := mod.widgets.RobrixDock {
   width: Fill height: Fill padding: 0 spacing: 0 margin: 0
   tab_bar +: {
    height: 44
    CloseableTab := mod.widgets.RobrixTab {closeable: true}
    PermanentTab := mod.widgets.RobrixTab {closeable: false width: Fit padding: Inset{left: 24, right: 24}}
   }
   root := DockTabs {tabs: [@home_tab, @console_tab] selected: 0}
   home_tab := DockTab {name: "Chat" kind: @room_screen template: @PermanentTab}
   console_tab := DockTab {name: "Console" kind: @console_screen template: @PermanentTab}
   room_screen := CachedWidget {room_screen := mod.widgets.RoomScreen {}}
   console_screen := View {
    flow: Down padding: 24 spacing: 12
    Label {text: "Console" draw_text.color: COLOR_TEXT}
    console_status := Label {width: Fill flow: Flow.Right{wrap: true} text: "Runtime controls are not yet composed into this Robrix host. No operation is dispatched from this view." draw_text.color: COLOR_TEXT}
   }
  }
 }
 mod.widgets.MainDesktopUI = #(MainDesktopUI::register_widget(vm)) {
  flow: Right show_bg: true draw_bg.color: COLOR_PRIMARY
  rail := SolidView {
   width: 64 height: Fill flow: Down spacing: 16 padding: 8 draw_bg.color: COLOR_PRIMARY
   rail_chat := mod.widgets.RailButton {text: "Chat"}
   rail_console := mod.widgets.RailButton {text: "Console" draw_bg.icon_kind: 1.0}
  }
  layout_dock := mod.widgets.RobrixDock {
   width: Fill height: Fill padding: 0 spacing: 0 margin: 0
   tab_bar +: {
    CloseableTab := mod.widgets.RobrixTab {closeable: true}
    PermanentTab := mod.widgets.RobrixTab {closeable: false width: Fit padding: 9}
   }
   root := DockSplitter {
    axis: SplitterAxis.Horizontal align: SplitterAlign.FromA(248.0)
    a: @rooms_sidebar_tabs b: @main_workspace_tabs
   }
   rooms_sidebar_tabs := DockTabs {tabs: [@rooms_sidebar_tab] selected: 0 hide_tab_bar: true}
   main_workspace_tabs := DockTabs {tabs: [@main_workspace_tab] selected: 0 hide_tab_bar: true}
   rooms_sidebar_tab := DockTab {kind: @rooms_sidebar template: @PermanentTab}
   main_workspace_tab := DockTab {kind: @main_workspace template: @PermanentTab}
   rooms_sidebar := CachedWidget {rooms_sidebar := mod.widgets.RoomsSideBar {}}
   main_workspace := mod.widgets.MainConversationUI {}
  }
 }
 mod.widgets.HomeScreen = #(HomeScreen::register_widget(vm)) {
  main_adaptive_view := AdaptiveView {
   Desktop := SolidView {
    width: Fill height: Fill flow: Down padding: 0 margin: 0
    draw_bg.color: COLOR_SECONDARY
    brand_bar := mod.widgets.HeptaBrandBar {}
    CachedWidget {desktop_ui := mod.widgets.MainDesktopUI {}}
   }
   Mobile := SolidView {
    width: Fill height: Fill flow: Down draw_bg.color: COLOR_SECONDARY
    brand_bar := mod.widgets.HeptaBrandBar {
     height: 44 padding: Inset{left: 12, right: 12} spacing: 10
     brand_mark +: {width: 28 height: 28}
     brand_title +: {draw_text.text_style.font_size: 14}
    }
    channel_heading := mod.widgets.ConversationHeading {compact: true}
    View {width: Fill height: Fit flow: Flow.Right{wrap: true} spacing: 6 padding: 6
     conversations := mod.widgets.NavigationButton {text: "Conversations"}
     chat_tab := mod.widgets.NavigationButton {text: "Chat"}
     console_tab_button := mod.widgets.NavigationButton {text: "Console"}
     mobile_theme_switch := mod.widgets.AuroraButton {grab_key_focus: false text: "Aurora Graphite"}
    }
    mobile_pages := PageFlip {
     width: Fill height: Fill active_page: @chat_page
     chat_page := CachedWidget {room_screen := mod.widgets.RoomScreen {}}
     navigation_page := View {
      flow: Down
      back_to_chat := mod.widgets.AuroraButton {text: "Back to conversation"}
      CachedWidget {rooms_sidebar := mod.widgets.RoomsSideBar {}}
     }
     console_page := View {flow: Down padding: 16
      mobile_console_status := Label {width: Fill flow: Flow.Right{wrap: true} draw_text.color: COLOR_TEXT text: "Console controls are awaiting composition. No runtime operation is dispatched here."}
     }
    }
   }
  }
 }
}
/// The existing Chat/Console Dock, under a shared display-only room heading.
/// It receives the original workspace and forwards every event unchanged.
#[derive(Script, ScriptHook, Widget)]
pub struct MainConversationUI {
    #[deref]
    view: View,
}
impl Widget for MainConversationUI {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        self.view.handle_event(cx, event, scope);
    }
    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
        // This child is created lazily by the outer layout Dock. Select here,
        // before its first draw, so a cached Console stays Console on resize.
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
            self.view.dock(cx, ids!(dock)).select_tab(
                cx,
                if workspace.tab == WorkspaceTab::Console {
                    id!(console_tab)
                } else {
                    id!(home_tab)
                },
            );
        }
        self.view.draw_walk(cx, scope, walk)
    }
}
/// Only ordinary visible selection, used to invalidate retained draw lists.
struct VisualSelection {
    room: RoomKey,
    title: String,
    tab: WorkspaceTab,
    navigation_open: bool,
}
#[derive(Script, Widget)]
pub struct HomeScreen {
    #[deref]
    view: View,
    #[rust]
    mobile_page: Option<(LiveId, [WidgetUid; 3])>,
    #[rust]
    rendered: Option<RoomKey>,
    #[rust]
    theme_return_focus: Option<(RoomKey, TextInputRef)>,
    #[rust]
    visual_selection: Option<VisualSelection>,
    #[rust]
    pending_visual_redraw: Option<NextFrame>,
    #[rust]
    last_composing: Option<bool>,
}
impl ScriptHook for HomeScreen {
    fn on_after_new(&mut self, vm: &mut ScriptVm) {
        vm.with_cx_mut(|cx| {
            self.view
                .adaptive_view(cx, ids!(main_adaptive_view))
                .set_variant_selector(crate::ime_router::adaptive_variant)
        });
    }
}
impl Widget for HomeScreen {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        if let Event::MouseDown(mouse) = event {
            self.theme_return_focus = None;
            let focus = cx.key_focus();
            let editor = self.view.text_input(cx, ids!(message_input));
            let search = self.view.text_input(cx, ids!(room_filter));
            let target = if focus == editor.area() {
                Some(editor)
            } else if focus == search.area() {
                Some(search)
            } else {
                None
            };
            let on_theme = [ids!(theme_switch), ids!(mobile_theme_switch)]
                .into_iter()
                .any(|id| {
                    let area = self.view.button(cx, id).area();
                    area.is_valid(cx) && area.rect(cx).contains(mouse.abs)
                });
            if on_theme
                && focus.is_valid(cx)
                && let Some(target) = target
                && let Some(key) = self.rendered
            {
                self.theme_return_focus = Some((key, target));
            }
        } else if matches!(event, Event::KeyDown(_)) {
            // A keyboard-activated theme control keeps its own navigation focus.
            self.theme_return_focus = None;
        }
        self.view.handle_event(cx, event, scope);
        let Some(workspace) = scope.data.get_mut::<ChatWorkspace>() else {
            return;
        };
        let Some(source) = self.rendered else { return };
        if let Event::Actions(actions) = event {
            if (self
                .view
                .button(cx, ids!(mobile_theme_switch))
                .clicked(actions)
                || self.view.button(cx, ids!(theme_switch)).clicked(actions))
                && !workspace.composing
            {
                crate::visual_theme::cycle(cx);
                if let Some((key, input)) = self.theme_return_focus.take()
                    && key == source
                    && key.epoch == workspace.presentation_epoch()
                    && key.local_id == workspace.active_id()
                    && input.area().is_valid(cx)
                {
                    // A press may span redraws; resolve the live field's current
                    // area instead of restoring a stale draw-instance address.
                    input.take_key_focus(cx);
                }
            }
            let command = if self.view.button(cx, ids!(conversations)).clicked(actions) {
                Some(PresentationCommand::SetNavigationOpen(true))
            } else if self.view.button(cx, ids!(back_to_chat)).clicked(actions) {
                Some(PresentationCommand::SetNavigationOpen(false))
            } else if self.view.button(cx, ids!(chat_tab)).clicked(actions) {
                Some(PresentationCommand::SelectTab(WorkspaceTab::Conversations))
            } else if self
                .view
                .button(cx, ids!(console_tab_button))
                .clicked(actions)
            {
                Some(PresentationCommand::SelectTab(WorkspaceTab::Console))
            } else {
                None
            };
            if let Some(command) = command {
                apply_action(workspace, PresentationAction { source, command });
                self.view.redraw(cx);
            }
        }
        if let Event::KeyDown(key) = event
            && key.key_code == KeyCode::Escape
            && !workspace.composing
        {
            apply_action(
                workspace,
                PresentationAction {
                    source,
                    command: PresentationCommand::SetNavigationOpen(false),
                },
            );
            self.view.redraw(cx);
        }
        // A sidebar action can update selection while only invalidating the
        // sidebar. Invalidate the common view after the action, before Draw:
        // the nested Dock may otherwise reuse a clean main contents list and
        // skip both its title and selected-tab synchronization. Never record
        // an invalidation suppressed by the framework's in-draw guard. A
        // display change during drawing requests one deferred frame instead
        // of waiting for another user event or recursively dispatching one.
        if self
            .pending_visual_redraw
            .is_some_and(|frame| frame.is_event(event).is_some())
        {
            self.pending_visual_redraw = None;
        }
        let room = RoomKey {
            epoch: workspace.presentation_epoch(),
            local_id: workspace.active_id(),
        };
        let title = workspace
            .title_for(workspace.active_id())
            .unwrap_or("New conversation");
        if self.visual_selection.as_ref().is_none_or(|previous| {
            previous.room != room
                || previous.title != title
                || previous.tab != workspace.tab
                || previous.navigation_open != workspace.navigation_open
        }) {
            if cx.in_draw_event() {
                if self.pending_visual_redraw.is_none() {
                    self.pending_visual_redraw = Some(cx.new_next_frame());
                }
            } else {
                self.view.redraw(cx);
                self.visual_selection = Some(VisualSelection {
                    room,
                    title: title.to_owned(),
                    tab: workspace.tab,
                    navigation_open: workspace.navigation_open,
                });
                self.pending_visual_redraw = None;
            }
        }
    }
    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
            if self.last_composing != Some(workspace.composing) {
                self.view
                    .adaptive_view(cx, ids!(main_adaptive_view))
                    .set_variant_selector(crate::ime_router::adaptive_variant);
                self.last_composing = Some(workspace.composing);
            }
            self.rendered = Some(RoomKey {
                epoch: workspace.presentation_epoch(),
                local_id: workspace.active_id(),
            });
            let page = if workspace.navigation_open {
                id!(navigation_page)
            } else if workspace.tab == WorkspaceTab::Console {
                id!(console_page)
            } else {
                id!(chat_page)
            };
            self.view
                .page_flip(cx, ids!(mobile_pages))
                .set_active_page(cx, page);
            let mut buttons = [
                self.view.widget(cx, ids!(conversations)),
                self.view.widget(cx, ids!(chat_tab)),
                self.view.widget(cx, ids!(console_tab_button)),
            ];
            let identities = buttons.each_ref().map(|button| button.widget_uid());
            if !buttons.iter().any(WidgetRef::is_empty)
                && self.mobile_page != Some((page, identities))
            {
                for (button, target) in buttons.iter_mut().zip([
                    id!(navigation_page),
                    id!(chat_page),
                    id!(console_page),
                ]) {
                    let selected = if page == target { 1.0 } else { 0.0 };
                    script_apply_eval!(cx, button, {draw_bg +: {current_page: #(selected)}});
                }
                self.mobile_page = Some((page, identities));
            }
            self.view
                .button(cx, ids!(conversations))
                .set_enabled(cx, !workspace.composing);
            self.view
                .button(cx, ids!(mobile_theme_switch))
                .set_enabled(cx, !workspace.composing);
        }
        self.view.draw_walk(cx, scope, walk)
    }
}
#[derive(Script, ScriptHook, Widget)]
pub struct MainDesktopUI {
    #[deref]
    view: View,
    #[rust]
    rendered: Option<RoomKey>,
    #[rust]
    layout_theme: Option<crate::visual_theme::VisualTheme>,
}
impl Widget for MainDesktopUI {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        self.view.handle_event(cx, event, scope);
        let Some(workspace) = scope.data.get_mut::<ChatWorkspace>() else {
            return;
        };
        let Some(source) = self.rendered else { return };
        if let Event::Actions(actions) = event {
            let rail_tab = if self.view.button(cx, ids!(rail_chat)).clicked(actions) {
                Some(WorkspaceTab::Conversations)
            } else if self.view.button(cx, ids!(rail_console)).clicked(actions) {
                Some(WorkspaceTab::Console)
            } else {
                None
            };
            if let Some(tab) = rail_tab {
                apply_action(
                    workspace,
                    PresentationAction {
                        source,
                        command: PresentationCommand::SelectTab(tab),
                    },
                );
                self.view.redraw(cx);
            }
            let dock = self.view.dock(cx, ids!(dock));
            for action in actions.filter_widget_actions_cast::<DockAction>(dock.widget_uid()) {
                if let DockAction::TabWasPressed(tab) = action {
                    let tab = if tab == id!(console_tab) {
                        WorkspaceTab::Console
                    } else {
                        WorkspaceTab::Conversations
                    };
                    apply_action(
                        workspace,
                        PresentationAction {
                            source,
                            command: PresentationCommand::SelectTab(tab),
                        },
                    );
                }
            }
        }
    }
    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
        // A cached desktop can become visible after a theme changed in the
        // compact host. Apply layout before its first paint, not in App's
        // post-event recolour traversal after the old splitter was drawn.
        let theme = cx.global::<crate::visual_theme::ThemeState>().selected;
        if self.layout_theme != Some(theme)
            && self.view.dock(cx, ids!(layout_dock)).set_splitter_align(
                cx,
                id!(root),
                SplitterAlign::FromA(theme.sidebar_width()),
                false,
            )
        {
            // The SDK setter always requests redraw, including equal values.
            // Run once per theme/instance, preserving manual splitter changes.
            self.layout_theme = Some(theme);
        }
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
            self.rendered = Some(RoomKey {
                epoch: workspace.presentation_epoch(),
                local_id: workspace.active_id(),
            });
        }
        self.view.draw_walk(cx, scope, walk)
    }
}
