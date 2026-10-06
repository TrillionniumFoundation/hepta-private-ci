// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../licenses/ROBRIX-MIT.txt.
// Source: src/app.rs Root/Window composition and AppMain registration lifecycle.
// Hepta owns the nonvisual state; this UI does not create a runtime or credentials.
use crate::ime_router::ImeRouter;
#[cfg(feature = "native-host")]
use crate::native_host::render::RendererHost as NativeRenderer;
#[cfg(target_arch = "wasm32")]
use crate::runtime_status::RuntimeClient;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::*;
app_main!(App, font_set: International, font_assets: [MATH_VIEW_FONT_ASSET], configure: |cx| {
    #[cfg(feature = "native-host")]
    crate::native_host::render::configure(cx);
    #[cfg(not(feature = "native-host"))]
    let _ = cx;
});
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 load_all_resources() do #(App::script_component(vm)) {
  ui: Root {
   main_window := Window {
    window.inner_size: vec2(1280,800)
    window.title: "Hepta Conversations"
    body +: {
     flow: Down
     native_host_panel := View {
      visible: false width: Fill height: Fit flow: Down padding: 8 spacing: 4
      native_host_status := mod.widgets.NativeStatus {}
      native_retry_close := mod.widgets.AuroraButton {visible: false text: "Retry runtime close (no update)"}
     }
     native_content := View {width: Fill height: Fill mod.widgets.HomeScreen {}}
    }
   }
  }
 }
}
#[cfg(feature = "ui-fixtures")]
#[derive(Default)]
struct FixtureFontResources(std::collections::HashMap<String, (usize, u8)>);

#[derive(Script)]
pub struct App {
    #[live]
    ui: WidgetRef,
    #[rust]
    workspace: ChatWorkspace,
    #[rust]
    ime_router: ImeRouter,
    #[cfg(target_arch = "wasm32")]
    #[rust]
    runtime_status: RuntimeClient,
    #[cfg(feature = "native-host")]
    #[rust]
    native_host: NativeRenderer,
}
impl ScriptHook for App {
    fn on_after_new(&mut self, _vm: &mut ScriptVm) {
        #[cfg(feature = "ui-fixtures")]
        {
            self.workspace = hepta_control_core::chat::fixtures::owner_conversation_fixture();
            hepta_control_core::chat::fixtures::extend_scroll_fixture(&mut self.workspace);
        }
    }
}
// Temporary read-only diagnostic on the isolated keyboard-audit branch.
// It records neither editor/search text nor owner credentials, and never sets focus.
#[cfg(feature = "keyboard-focus-trace")]
impl App {
    fn observe_keyboard_focus(&self, cx: &mut Cx, event: &Event, phase: &str) {
        let (kind, key) = match event {
            Event::KeyDown(key) => ("down", key),
            Event::KeyUp(key) => ("up", key),
            _ => return,
        };
        if !matches!(
            key.key_code,
            KeyCode::Tab | KeyCode::Space | KeyCode::ReturnKey | KeyCode::Escape
        ) {
            return;
        }
        let focus = cx.key_focus();
        let mut candidates = Vec::new();
        for (name, id) in [
            ("conversations", id!(conversations)),
            ("chat_tab", id!(chat_tab)),
            ("console_tab", id!(console_tab_button)),
            ("mobile_theme", id!(mobile_theme_switch)),
            ("desktop_theme", id!(theme_switch)),
            ("editor", id!(message_input)),
            ("search", id!(room_filter)),
            ("back", id!(back_to_chat)),
            ("new_draft", id!(new_draft)),
            ("rail_chat", id!(rail_chat)),
            ("rail_console", id!(rail_console)),
            ("send", id!(send_message_button)),
        ] {
            let widget = self.ui.widget(cx, &[id]);
            let area = widget.area();
            if !widget.is_empty() {
                candidates.push((
                    name,
                    area,
                    area.is_valid(cx),
                    area == focus,
                    widget.visible(),
                ));
            }
        }
        let mut stops = Vec::new();
        let mut public_nav_root = None;
        let mut stops_truncated = false;
        if cx.has_global::<makepad_widgets::makepad_draw::nav::CxNavTreeRc>()
            && let Some(root) = self.ui.widget(cx, ids!(main_window)).area().draw_list_id()
        {
            public_nav_root = Some(root);
            let _ = CxDraw::iterate_nav_stops(cx, root, |cx, stop| {
                if stops.len() < 32 {
                    stops.push((stop.area, stop.area.is_valid(cx), stop.area == focus));
                } else {
                    stops_truncated = true;
                }
                None
            });
        }
        log!(
            "HEPTA_KEYBOARD_FOCUS phase={} kind={} key={:?} shift={} focus={:?} valid={} candidates={:?} public_nav_root={:?} stops_truncated={} stops={:?}",
            phase,
            kind,
            key.key_code,
            key.modifiers.shift,
            focus,
            focus.is_valid(cx),
            candidates,
            public_nav_root,
            stops_truncated,
            stops,
        );
    }
}
impl AppMain for App {
    fn after_new_from_script(vm: &mut ScriptVm, app: &mut Self) {
        #[cfg(feature = "native-host")]
        vm.with_cx_mut(|cx| app.native_host.adopt(cx));
        #[cfg(not(feature = "native-host"))]
        let _ = (vm, app);
    }
    fn script_mod(vm: &mut ScriptVm) -> ScriptValue {
        makepad_widgets::theme_mod(vm);
        script_eval!(vm, {mod.theme = mod.themes.dark});
        makepad_widgets::widgets_mod(vm);
        crate::robrix::styles::script_mod(vm);
        crate::native_status::script_mod(vm);
        crate::robrix::dock::script_mod(vm);
        crate::robrix::composer::script_mod(vm);
        crate::robrix::rooms::script_mod(vm);
        crate::robrix::room::script_mod(vm);
        crate::robrix::home::script_mod(vm);
        self::script_mod(vm)
    }
    fn handle_event(&mut self, cx: &mut Cx, event: &Event) {
        #[cfg(feature = "ui-fixtures")]
        if matches!(event, Event::NetworkResponses(_) | Event::Draw(_)) {
            use makepad_widgets::makepad_platform::script::res::CxScriptResourceData;
            let resources = cx.script_data.resources.resources.clone();
            for resource in resources.borrow().iter() {
                if !resource.abs_path.ends_with(".ttf") && !resource.abs_path.ends_with(".otf") {
                    continue;
                }
                let state = match &resource.data {
                    CxScriptResourceData::NotLoaded => 0,
                    CxScriptResourceData::Loading => 1,
                    CxScriptResourceData::Loaded(_) => 2,
                    CxScriptResourceData::Error(_) => 3,
                };
                let current = (resource.loaded_len(), state);
                if cx
                    .global::<FixtureFontResources>()
                    .0
                    .insert(resource.abs_path.clone(), current)
                    != Some(current)
                {
                    log!(
                        "HEPTA_FIXTURE_RESOURCE_EVENT dependency={:?} state={} loaded_len={}",
                        resource.dependency_path,
                        state,
                        resource.loaded_len()
                    );
                }
            }
        }
        #[cfg(feature = "native-host")]
        if self.native_host.before_event(cx, &self.ui, event) {
            return;
        }
        crate::visual_theme::apply_tree(cx, &self.ui);
        #[cfg(feature = "keyboard-focus-trace")]
        self.observe_keyboard_focus(cx, event, "before-dispatch");
        self.ime_router
            .dispatch(cx, &self.ui, event, &mut self.workspace);
        #[cfg(feature = "keyboard-focus-trace")]
        self.observe_keyboard_focus(cx, event, "after-dispatch");
        #[cfg(target_arch = "wasm32")]
        self.runtime_status.handle_event(
            cx,
            &self.ui,
            event,
            self.workspace.tab == hepta_control_core::chat::WorkspaceTab::Console
                && !self.workspace.navigation_open,
            self.workspace.presentation_epoch(),
        );
        #[cfg(feature = "native-host")]
        if matches!(event, Event::Draw(_)) {
            self.native_host.after_draw(cx, &self.ui);
        }
        crate::visual_theme::apply_tree(cx, &self.ui);
        #[cfg(feature = "ui-fixtures")]
        if matches!(event, Event::Draw(_)) {
            crate::robrix::room::finish_fixture_geometry(cx);
        }
        #[cfg(feature = "ui-fixtures")]
        crate::robrix::sidebar_fixture::after_event(cx, &self.workspace, &self.ui, event);
    }
}
