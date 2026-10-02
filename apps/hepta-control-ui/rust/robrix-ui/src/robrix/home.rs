// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Sources: home/main_desktop_ui.rs:15–81; home/home_screen.rs:145–210.
// Retains Robrix sidebar/main Dock split, fixed sidebar tab, persistent chat/Console
// tabs and AdaptiveView/CachedWidget ownership. Matrix room factories removed.
use crate::presentation::{PresentationAction, PresentationCommand, RoomKey, apply_action};
use hepta_control_core::chat::{ChatWorkspace, WorkspaceTab};
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 mod.widgets.MainDesktopUI = #(MainDesktopUI::register_widget(vm)) {
  flow: Overlay
  dock := mod.widgets.RobrixDock {
   width: Fill height: Fill padding: 0 spacing: 0 margin: 0
   tab_bar +: {
    CloseableTab := mod.widgets.RobrixTab {closeable: true}
    PermanentTab := mod.widgets.RobrixTab {closeable: false width: Fit padding: 9}
   }
   root := DockSplitter {
    axis: SplitterAxis.Horizontal align: SplitterAlign.FromA(300.0)
    a: @rooms_sidebar_tabs b: @main_tabs
   }
   rooms_sidebar_tabs := DockTabs {tabs: [@rooms_sidebar_tab] selected: 0 hide_tab_bar: true}
   main_tabs := DockTabs {tabs: [@home_tab, @console_tab] selected: 0}
   rooms_sidebar_tab := DockTab {kind: @rooms_sidebar template: @PermanentTab}
   home_tab := DockTab {name: "Conversation" kind: @room_screen template: @PermanentTab}
   console_tab := DockTab {name: "Console" kind: @console_screen template: @PermanentTab}
   rooms_sidebar := mod.widgets.RoomsSideBar {}
   room_screen := mod.widgets.RoomScreen {}
   console_screen := View {
    flow: Down padding: 24 spacing: 12
    Label {text: "Console" draw_text.color: COLOR_TEXT}
    Label {width: Fill flow: Flow.Right{wrap: true} text: "Runtime controls are not yet composed into this Robrix host. No operation is dispatched from this view." draw_text.color: COLOR_TEXT}
   }
  }
 }
 mod.widgets.HomeScreen = #(HomeScreen::register_widget(vm)) {
  main_adaptive_view := AdaptiveView {
   Desktop := SolidView {
    width: Fill height: Fill flow: Right padding: 0 margin: 0
    draw_bg.color: COLOR_SECONDARY
    CachedWidget {desktop_ui := mod.widgets.MainDesktopUI {}}
   }
   Mobile := SolidView {
    width: Fill height: Fill flow: Down draw_bg.color: COLOR_SECONDARY
    View {width: Fill height: Fit flow: Right spacing: 8
     conversations := Button {text: "Conversations"}
     chat_tab := Button {text: "Chat"}
     console_tab_button := Button {text: "Console"}
    }
    mobile_pages := PageFlip {
     width: Fill height: Fill active_page: @chat_page
     chat_page := CachedWidget {room_screen := mod.widgets.RoomScreen {}}
     navigation_page := View {
      flow: Down
      back_to_chat := Button {text: "Back to conversation"}
      CachedWidget {rooms_sidebar := mod.widgets.RoomsSideBar {}}
     }
     console_page := View {flow: Down padding: 16
      Label {width: Fill flow: Flow.Right{wrap: true} draw_text.color: COLOR_TEXT text: "Console controls are awaiting composition. No runtime operation is dispatched here."}
     }
    }
   }
  }
 }
}
#[derive(Script, Widget)]
pub struct HomeScreen {
    #[deref]
    view: View,
    #[rust]
    rendered: Option<RoomKey>,
}
impl ScriptHook for HomeScreen {
    fn on_after_new(&mut self, vm: &mut ScriptVm) {
        vm.with_cx_mut(|cx| {
            self.view
                .adaptive_view(cx, ids!(main_adaptive_view))
                .set_variant_selector(|_, size| {
                    if size.x >= 760.0 {
                        live_id!(Desktop)
                    } else {
                        live_id!(Mobile)
                    }
                })
        });
    }
}
impl Widget for HomeScreen {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        self.view.handle_event(cx, event, scope);
        let Some(workspace) = scope.data.get_mut::<ChatWorkspace>() else {
            return;
        };
        let Some(source) = self.rendered else { return };
        if let Event::Actions(actions) = event {
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
    }
    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
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
            self.view
                .button(cx, ids!(conversations))
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
}
impl Widget for MainDesktopUI {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        self.view.handle_event(cx, event, scope);
        let Some(workspace) = scope.data.get_mut::<ChatWorkspace>() else {
            return;
        };
        let Some(source) = self.rendered else { return };
        if let Event::Actions(actions) = event {
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
        if let Some(workspace) = scope.data.get::<ChatWorkspace>() {
            self.rendered = Some(RoomKey {
                epoch: workspace.presentation_epoch(),
                local_id: workspace.active_id(),
            });
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
