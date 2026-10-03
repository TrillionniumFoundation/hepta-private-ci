// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../licenses/ROBRIX-MIT.txt.
// Source: src/app.rs Root/Window composition and AppMain registration lifecycle.
// Hepta owns the nonvisual state; this UI does not create a runtime or credentials.
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::*;
app_main!(App, font_set: International, font_assets: [MATH_VIEW_FONT_ASSET]);
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 load_all_resources() do #(App::script_component(vm)) {
  ui: Root {
   main_window := Window {
    window.inner_size: vec2(1280,800)
    window.title: "Hepta Conversations"
    body +: {mod.widgets.HomeScreen {}}
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
impl AppMain for App {
    fn script_mod(vm: &mut ScriptVm) -> ScriptValue {
        makepad_widgets::theme_mod(vm);
        script_eval!(vm, {mod.theme = mod.themes.dark});
        makepad_widgets::widgets_mod(vm);
        crate::robrix::styles::script_mod(vm);
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
                if !resource.abs_path.ends_with(".ttf") {
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
        crate::visual_theme::apply_tree(cx, &self.ui);
        self.ui
            .handle_event(cx, event, &mut Scope::with_data(&mut self.workspace));
        crate::visual_theme::apply_tree(cx, &self.ui);
    }
}
