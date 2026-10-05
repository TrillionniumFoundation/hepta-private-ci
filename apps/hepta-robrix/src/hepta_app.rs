//! Native owner presentation using Robrix Root/Window, navigation and PortalList.
//! Matrix IDs and Agent conversation IDs remain distinct; this renderer creates neither.
#[cfg(not(target_arch = "wasm32"))]
use crate::hepta_owner_worker::OwnerCommand;
#[cfg(not(target_arch = "wasm32"))]
use crate::hepta_owner_worker::OwnerWorker;
#[cfg(not(target_arch = "wasm32"))]
use hepta_native::fleet_lifecycle::FleetLifecycleOperation;
use makepad_widgets::*;
#[cfg(not(target_arch = "wasm32"))]
#[path = "hepta_app_owner.rs"]
mod owner;
app_main!(App);
script_mod! {
    use mod.prelude.widgets.*
    use mod.widgets.*
    load_all_resources() do #(App::script_component(vm)) {
        ui: Root {
            main_window := Window {
                window.inner_size: vec2(1280, 800)
                window.title: "Hepta"
                pass.clear_color: #xffffff
                body +: {
                    flow: Right
                    navigation := SolidView {
                        width: 96 height: Fill flow: Down padding: 12 spacing: 16
                        draw_bg.color: #xf3f3f3
                        Label {text: "Hepta" draw_text.text_style.font_size: 18}
                        chat := RobrixNeutralIconButton {text: "Chat" width: Fill}
                        console := RobrixNeutralIconButton {text: "Console" width: Fill}
                    }
                    workspace := View {
                        width: Fill height: Fill flow: Down
                        title := Label {text: "Conversations" width: Fill height: Fit padding: 24 draw_text.text_style.font_size: 20}
                        chat_tools := View {
                            width: Fill height: Fit padding: 12 spacing: 8 flow: Right
                            new_conversation := RobrixNeutralIconButton {text: "New conversation" enabled: false}
                            refresh_conversation := RobrixNeutralIconButton {text: "Refresh messages" enabled: false}
                            inspect_chat := RobrixNeutralIconButton {text: "Inspect previous action" enabled: false}
                            abandon_creation := RobrixNegativeIconButton {text: "Abandon pending creation" enabled: false}
                            cancel_reply := RobrixNegativeIconButton {text: "Stop reply" enabled: false}
                        }
                        composer := View {
                                    width: Fill height: 72 padding: 16 spacing: 12 flow: Right
                                    send := RobrixIconButton {text: "Send" enabled: false}
                                    message_input := TextInput {width: Fill height: Fit empty_text: "Message"}
                                }
                        chat_agents := PortalList {
                            width: Fill height: 68 flow: Down
                            ChatAgent := RobrixNeutralIconButton {text: "" width: Fill height: Fit}
                        }
                        content := View {
                            width: Fill height: Fill flow: Right
                            rooms := PortalList {
                                width: 280 height: Fill flow: Down
                                Room := View {
                                    width: Fill height: Fit padding: 12
                                    open := RobrixNeutralIconButton {width: Fill height: Fit text: ""}
                                }
                            }
                            room_screen := View {
                                width: Fill height: Fill flow: Down
                                owner_status := Label {
                                    width: Fill height: Fit padding: 16
                                    draw_text.text_style.font_size: 13
                                    flow: Flow.Right{wrap: true}
                                    text: "Connect the installed owner to open a conversation."
                                }
                                timeline := PortalList {
                                    width: Fill height: Fill flow: Down
                                    auto_tail: true
                                    Message := View {
                                        width: Fill height: Fit padding: 16 flow: Down
                                        author := Label {width: Fill height: Fit}
                                        content := Label {width: Fill height: Fit flow: Flow.Right{wrap: true}}
                                    }
                                }

                            }
                        }
                        console_panel := View {
                            visible: false width: Fill height: Fill flow: Down padding: 16 spacing: 12
                            console_status := Label {
                                width: Fill height: Fit flow: Flow.Right{wrap: true}
                                text: "Waiting for the explicitly configured runtime."
                            }
                            refresh := RobrixNeutralIconButton {text: "Refresh"}
                            inspect := RobrixNeutralIconButton {text: "Inspect previous action"}
                            agents := PortalList {
                                width: Fill height: Fill flow: Down
                                Agent := RoundedView {
                                    width: Fill height: Fit padding: 16 margin: 4 flow: Down spacing: 8
                                    name := Label {width: Fill height: Fit}
                                    state := Label {width: Fill height: Fit}
                                    release := Label {width: Fill height: Fit flow: Flow.Right{wrap: true}}
                                    View {
                                        width: Fill height: Fit flow: Right spacing: 12
                                        start := RobrixPositiveIconButton {text: "Start"}
                                        stop := RobrixNegativeIconButton {text: "Stop"}
                                        restart := RobrixNeutralIconButton {text: "Restart"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
#[derive(Script, ScriptHook)]
pub struct App {
    #[live]
    ui: WidgetRef,
    #[cfg(not(target_arch = "wasm32"))]
    #[rust]
    owner: Option<OwnerWorker>,
    #[cfg(not(target_arch = "wasm32"))]
    #[rust]
    observation: Option<hepta_native::native_host::NativeHostObservation>,
    #[cfg(not(target_arch = "wasm32"))]
    #[rust]
    chat_view: Option<hepta_native::chat_presentation::ChatPresentation>,
    #[rust]
    chat_timer: Timer,
    #[rust]
    console_visible: bool,
    #[rust]
    busy: bool,
    #[rust]
    displayed_revision: u64,
    #[rust]
    displayed_threads: Vec<String>,
}

impl App {
    fn draw(&mut self, cx: &mut Cx2d) {
        #[cfg(not(target_arch = "wasm32"))]
        let agent_list_uid = self.ui.portal_list(cx, ids!(agents)).widget_uid();
        #[cfg(not(target_arch = "wasm32"))]
        let chat_agents_uid = self.ui.portal_list(cx, ids!(chat_agents)).widget_uid();
        #[cfg(not(target_arch = "wasm32"))]
        let rooms_uid = self.ui.portal_list(cx, ids!(rooms)).widget_uid();
        #[cfg(not(target_arch = "wasm32"))]
        let timeline_uid = self.ui.portal_list(cx, ids!(timeline)).widget_uid();
        while let Some(step) = self.ui.draw(cx, &mut Scope::empty()).step() {
            if let Some(mut list) = step.as_portal_list().borrow_mut() {
                #[cfg(not(target_arch = "wasm32"))]
                if list.widget_uid() == agent_list_uid {
                    self.displayed_revision = self
                        .observation
                        .as_ref()
                        .map(|view| view.revision)
                        .unwrap_or_default();
                    let agents = self
                        .observation
                        .as_ref()
                        .map(|view| view.agents.as_slice())
                        .unwrap_or_default();
                    let available = self.observation.as_ref().is_some_and(|view| {
                        view.lifecycle_available && !view.previous_action_pending && !self.busy
                    });
                    list.set_item_range(cx, 0, agents.len());
                    while let Some(index) = list.next_visible_item(cx) {
                        let Some(agent) = agents.get(index) else {
                            continue;
                        };
                        let item = list.item(cx, index, id!(Agent));
                        item.label(cx, ids!(name))
                            .set_text(cx, &format!("Agent {} · {}", index + 1, agent.id));
                        item.label(cx, ids!(state)).set_text(cx, &agent.state);
                        item.label(cx, ids!(release)).set_text(
                            cx,
                            agent.release.as_deref().unwrap_or("No release selected"),
                        );
                        item.button(cx, ids!(start))
                            .set_enabled(cx, available && !agent.active);
                        item.button(cx, ids!(stop))
                            .set_enabled(cx, available && agent.active);
                        item.button(cx, ids!(restart))
                            .set_enabled(cx, available && agent.running && agent.healthy);
                        item.draw_all_unscoped(cx);
                    }
                    continue;
                }
                #[cfg(not(target_arch = "wasm32"))]
                if list.widget_uid() == chat_agents_uid {
                    self.displayed_revision = self
                        .observation
                        .as_ref()
                        .map(|view| view.revision)
                        .unwrap_or_default();
                    let agents = self
                        .observation
                        .as_ref()
                        .map(|view| view.agents.as_slice())
                        .unwrap_or_default();
                    let enabled = self
                        .observation
                        .as_ref()
                        .is_some_and(|view| view.chat_available)
                        && !self.busy;
                    list.set_item_range(cx, 0, agents.len());
                    while let Some(index) = list.next_visible_item(cx) {
                        let Some(agent) = agents.get(index) else {
                            continue;
                        };
                        let item = list.item(cx, index, id!(ChatAgent));
                        item.as_button()
                            .set_text(cx, &format!("Open Agent {} · {}", index + 1, agent.state));
                        item.as_button()
                            .set_enabled(cx, enabled && agent.running && agent.healthy);
                        item.draw_all_unscoped(cx);
                    }
                    continue;
                }
                #[cfg(not(target_arch = "wasm32"))]
                if list.widget_uid() == rooms_uid {
                    let rows = self
                        .chat_view
                        .as_ref()
                        .map(|view| view.conversations.as_slice())
                        .unwrap_or_default();
                    self.displayed_threads = rows.iter().map(|row| row.id.clone()).collect();
                    list.set_item_range(cx, 0, rows.len());
                    while let Some(index) = list.next_visible_item(cx) {
                        let Some(row) = rows.get(index) else {
                            continue;
                        };
                        let item = list.item(cx, index, id!(Room));
                        item.button(cx, ids!(open)).set_text(
                            cx,
                            if row.title.trim().is_empty() {
                                "Conversation"
                            } else {
                                &row.title
                            },
                        );
                        item.button(cx, ids!(open)).set_enabled(
                            cx,
                            !self.busy
                                && self
                                    .chat_view
                                    .as_ref()
                                    .is_some_and(|view| !view.previous_action_pending),
                        );
                        item.draw_all_unscoped(cx);
                    }
                    continue;
                }
                #[cfg(not(target_arch = "wasm32"))]
                if list.widget_uid() == timeline_uid {
                    let rows = self
                        .chat_view
                        .as_ref()
                        .map(|view| view.messages.as_slice())
                        .unwrap_or_default();
                    list.set_item_range(cx, 0, rows.len());
                    while let Some(index) = list.next_visible_item(cx) {
                        let Some(row) = rows.get(index) else {
                            continue;
                        };
                        let item = list.item(cx, index, id!(Message));
                        item.label(cx, ids!(author))
                            .set_text(cx, if row.sender == "user" { "You" } else { "Agent" });
                        item.label(cx, ids!(content)).set_text(cx, &row.body);
                        item.draw_all_unscoped(cx);
                    }
                    continue;
                }
                // Conversations are populated only by the original chat owner.
                // An unconfigured transport never manufactures local rooms.
                list.set_item_range(cx, 0, 0);
            }
        }
    }
}

impl AppMain for App {
    fn script_mod(vm: &mut ScriptVm) -> ScriptValue {
        makepad_widgets::theme_mod(vm);
        script_eval!(vm, {mod.theme = mod.themes.light});
        makepad_widgets::widgets_mod(vm);
        crate::owner_styles::script_mod(vm);
        crate::owner_icon_button::script_mod(vm);
        self::script_mod(vm)
    }
    fn handle_event(&mut self, cx: &mut Cx, event: &Event) {
        // Framework clipboard writes have no original final-use receipt.
        // Explicit platform effects remain with NativeShellRuntime.
        if matches!(event, Event::TextCopy(_) | Event::TextCut(_)) {
            return;
        }
        if let Event::Draw(draw) = event {
            self.draw(&mut Cx2d::new(&mut CxDraw::new(cx, draw)));
            return;
        }
        #[cfg(not(target_arch = "wasm32"))]
        self.handle_owner_event(cx, event);
        self.ui.handle_event(cx, event, &mut Scope::empty());
        if let Event::Actions(actions) = event {
            if self.ui.button(cx, ids!(chat)).clicked(actions) {
                self.console_visible = false;
                self.ui.label(cx, ids!(title)).set_text(cx, "Conversations");
                self.ui.widget(cx, ids!(chat_tools)).set_visible(cx, true);
                self.ui.widget(cx, ids!(composer)).set_visible(cx, true);
                self.ui.widget(cx, ids!(chat_agents)).set_visible(cx, true);
                self.ui.widget(cx, ids!(content)).set_visible(cx, true);
                self.ui
                    .widget(cx, ids!(console_panel))
                    .set_visible(cx, false);
            }
            if self.ui.button(cx, ids!(console)).clicked(actions) {
                self.console_visible = true;
                self.ui.label(cx, ids!(title)).set_text(cx, "Runtime");
                self.ui.widget(cx, ids!(chat_tools)).set_visible(cx, false);
                self.ui.widget(cx, ids!(composer)).set_visible(cx, false);
                self.ui.widget(cx, ids!(chat_agents)).set_visible(cx, false);
                self.ui.widget(cx, ids!(content)).set_visible(cx, false);
                self.ui
                    .widget(cx, ids!(console_panel))
                    .set_visible(cx, true);
            }
            #[cfg(not(target_arch = "wasm32"))]
            self.handle_owner_actions(cx, actions);
        }
    }
}
