// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../licenses/ROBRIX-MIT.txt.
// Source: src/app.rs Root/Window composition and AppMain registration lifecycle.
// Hepta owns the nonvisual state; this UI does not create a runtime or credentials.
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::*;
app_main!(App, font_set: International);
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
        self.ui
            .handle_event(cx, event, &mut Scope::with_data(&mut self.workspace));
    }
}
