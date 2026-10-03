//! Compile-time gated, account-free rendering fixtures of the real application.
//! Startup returns before keyring, filesystem state, Matrix and console owners.
use super::*;

#[path = "ui_fixture_chat.rs"]
pub(crate) mod chat;

#[path = "ui_fixture_observation.rs"]
pub(super) mod observation;

#[derive(Default)]
struct FixtureState {
    active: bool,
    console: bool,
    chat: bool,
    select_timer: Timer,
}

pub(super) fn start(app: &mut App, cx: &mut Cx) -> bool {
    let Some(mode) = selected_mode().expect("invalid explicit UI fixture selection") else {
        return false;
    };
    for path in [ids!(login_screen_view), ids!(login_console_view)] {
        let view = app.ui.view(cx, path);
        let view = view.borrow().expect("pre-login wrapper missing");
        assert!(opaque_color_shader(cx, &view), "pre-login wrapper needs an opaque color shader");
    }
    let timer = cx.start_timeout(0.5);
    let state = cx.global::<FixtureState>();
    state.active = true;
    state.console = mode == "console";
    state.chat = mode.starts_with("chat-");
    state.select_timer = timer;
    app.app_state.logged_in = mode == "console" || mode.starts_with("chat-");
    if mode.starts_with("chat-") {
        use crate::shared::hepta_theme::{select, HeptaTheme};
        select(cx, match mode.as_str() {
            "chat-titanium" => HeptaTheme::DeepSpaceTitanium,
            "chat-ceramic" => HeptaTheme::ObsidianCeramic,
            _ => HeptaTheme::PolarPrism,
        });
        chat::populate();
    }
    app.ui
        .window(cx, ids!(main_window))
        .set_title(cx, "Hepta · UI fixture · no live accounts");
    let host = cx.global::<crate::hepta_console::ConsoleHost>();
    host.set_fixture_unconfigured();
    app.ui.label(cx, ids!(hepta_brand)).set_text(cx, "H E P T A · SAMPLE");
    app.update_login_visibility(cx);
    if mode == "login-usability" || mode.starts_with("chat-") { observation::start(cx); }
    cx.redraw_all();
    true
}

fn opaque_color_shader(cx: &mut Cx, view: &View) -> bool {
    let Some(shader) = view.draw_bg.draw_vars.draw_shader_id else { return false };
    if !view.show_bg || !cx.draw_shaders[shader.index].mapping.instances.inputs
        .iter().any(|input| input.id == id!(color) && input.slots == 4)
    {
        return false;
    }
    let mut color = [0.0; 4];
    view.draw_bg.draw_vars.get_instance(cx, id!(color), &mut color);
    color.iter().all(|value| value.is_finite()) && color[3] == 1.0
}

pub(crate) fn active(cx: &mut Cx) -> bool {
    cx.global::<FixtureState>().active
}

pub(crate) fn chat_active(cx: &mut Cx) -> bool { cx.global::<FixtureState>().chat }

pub(super) fn event(cx: &mut Cx, event: &Event) {
    let state = cx.global::<FixtureState>();
    if state.active && state.select_timer.is_event(event).is_some() {
        state.select_timer = Timer::default();
        if state.console { cx.action(NavigationBarAction::OpenConsole); }
        else if state.chat { chat::select_room(cx); }
        cx.redraw_all();
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn selected_mode() -> Result<Option<String>, &'static str> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let Some(index) = args.iter().position(|arg| arg == "--hepta-ui-fixture") else {
        return Ok(None);
    };
    if args.len() != 2 || index != 0 {
        return Err("fixture cannot be combined with real owner configuration");
    }
    let mode = args.get(1).ok_or("fixture mode missing")?;
    if !matches!(mode.as_str(), "login" | "console" | "chat-titanium" | "chat-prism" | "chat-ceramic") {
        return Err("unsupported fixture mode");
    }
    Ok(Some(mode.clone()))
}

#[cfg(target_arch = "wasm32")]
fn selected_mode() -> Result<Option<String>, &'static str> {
    let query = web_sys::window()
        .ok_or("browser window unavailable")?
        .location()
        .search()
        .map_err(|_| "browser query unavailable")?;
    browser_mode(&query)
}

#[cfg(any(target_arch = "wasm32", test))]
fn browser_mode(query: &str) -> Result<Option<String>, &'static str> {
    let query = query.strip_prefix('?').unwrap_or(query);
    let parts: Vec<_> = query.split('&').collect();
    let selected: Vec<_> = parts
        .iter()
        .filter_map(|part| part.split_once('='))
        .filter(|(key, _)| *key == "hepta-ui-fixture")
        .collect();
    if selected.is_empty() {
        if parts.contains(&"hepta-ui-fixture") {
            return Err("fixture mode missing");
        }
        return Ok(None);
    }
    if parts.len() != 1 || selected.len() != 1 {
        return Err("fixture cannot be combined with other browser parameters");
    }
    let mode = selected[0].1;
    if !matches!(mode, "login" | "console" | "login-usability" | "chat-titanium" | "chat-prism" | "chat-ceramic") {
        return Err("unsupported fixture mode");
    }
    Ok(Some(mode.to_owned()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn real_app_logout_and_login_events_cancel_restore_intent() {
        let mut cx = Cx::new(Box::new(|_, _| {}));
        let mut app = cx.with_vm(|vm| {
            let value = <App as AppMain>::script_mod(vm);
            App::script_from_value(vm, value)
        });
        app.app_state.logged_in = true;
        app.app_state.adaptive_dock_restore = Some(crate::home::adaptive_restore::AdaptiveDockRestore::capture());
        let actions: Vec<Action> = vec![Box::new(crate::logout::logout_confirm_modal::LogoutAction::LogoutSuccess)];
        app.handle_actions(&mut cx, &actions);
        assert!(!app.app_state.logged_in);
        assert!(app.app_state.adaptive_dock_restore.is_none());
        app.app_state.adaptive_dock_restore = Some(crate::home::adaptive_restore::AdaptiveDockRestore::capture());
        let actions: Vec<Action> = vec![Box::new(crate::login::login_screen::LoginAction::LoginSuccess)];
        app.handle_actions(&mut cx, &actions);
        assert!(app.app_state.adaptive_dock_restore.is_none());
    }

    #[test]
    fn actual_chat_fixture_draw_resolves_dynamic_material_and_image_values() {
        let _ = makepad_widgets::makepad_platform::shader_error::take();
        let mut cx = Cx::new(Box::new(|_, _| {}));
        cx.global::<FixtureState>().chat = true;
        let mut room = cx.with_vm(|vm| {
            vm.bx.captured_errors = Some(Vec::new());
            let _ = <App as AppMain>::script_mod(vm);
            let value = script_eval!(vm, { mod.widgets.RoomScreen {} });
            WidgetRef::script_from_value(vm, value)
        });
        use crate::home::room_screen::RoomScreenWidgetRefExt;
        let synthetic = crate::utils::RoomNameId::new(matrix_sdk::RoomDisplayName::Named("Sample".into()),
            "!hepta-fixture-test:example.invalid".try_into().unwrap());
        room.as_room_screen().set_displayed_room(&mut cx, &synthetic, None);
        let pass = DrawPass::new(&mut cx);
        pass.set_size(&mut cx, dvec2(800.0, 600.0));
        let mut list = DrawList::new(&mut cx);
        let event = DrawEvent::default();
        let mut draw = CxDraw::new(&mut cx, &event);
        draw.begin_pass(&pass, None);
        list.begin_always(&mut draw);
        {
            let mut cx = Cx2d::new(&mut draw);
            cx.begin_root_turtle(dvec2(800.0, 600.0), Layout::flow_down());
            room.draw_all(&mut cx, &mut Scope::with_data(&mut AppState::default()));
            cx.end_pass_sized_turtle();
        }
        list.end(&mut draw);
        draw.end_pass(&pass);
        drop(draw);
        let list = room.portal_list(&mut cx, ids!(list));
        let (_, image_message) = list.get_item(0).expect("first real image message");
        let image = image_message.image(&mut cx, ids!(content.message.image.image_view.image));
        let area = image.area();
        assert!(area.is_valid(&cx), "fixture image must have a real drawn area");
        let size = area.rect(&cx).size;
        assert!(size.x > 0.0 && size.x <= 320.0 && size.y > 0.0 && size.y <= 96.0,
            "fixture image must fit320x96, got {size:?}");
        let (_, reply_message) = list.get_item(2).expect("real reply fixture message");
        let card = reply_message.widget(&mut cx, ids!(reply_card)).area();
        let body = reply_message.widget(&mut cx, ids!(reply_preview_body)).area();
        assert!(card.is_valid(&cx) && body.is_valid(&cx));
        let card = card.rect(&cx);
        let body = body.rect(&cx);
        assert!(card.size.x > 0.0 && card.size.y > 0.0 && body.size.y > 0.0);
        assert!(body.pos.y >= card.pos.y && body.pos.y + body.size.y <= card.pos.y + card.size.y + 1.0,
            "reply body must remain inside its real recessed card");
        cx.with_vm(|vm| { let errors = vm.take_errors(); assert!(errors.is_empty(), "fixture dynamic script errors: {errors:#?}"); });
        assert_eq!(makepad_widgets::makepad_platform::shader_error::take(), None);
    }

    #[test]
    fn actual_app_templates_compile_without_script_errors() {
        let _ = makepad_widgets::makepad_platform::shader_error::take();
        let mut cx = Cx::new(Box::new(|_, _| {}));
        cx.with_vm(|vm| {
            vm.bx.captured_errors = Some(Vec::new());
            let value = <App as AppMain>::script_mod(vm);
            let _app = App::script_from_value(vm, value);
            // Dock templates are lazy: instantiate the real splitter too, so a
            // shader scope error cannot hide behind an otherwise valid App.
            let splitter = script_eval!(vm, { mod.widgets.RobrixSplitter {} });
            let _splitter = Splitter::script_from_value(vm, splitter);
            let tab = script_eval!(vm, {mod.widgets.RobrixTab {}});
            let _tab = Tab::script_from_value(vm, tab);
            for value in [
                script_eval!(vm, { mod.widgets.RoomScreen {} }),
                script_eval!(vm, { mod.widgets.ImageMessage {} }),
                script_eval!(vm, { mod.widgets.Avatar {} }),
                script_eval!(vm, { mod.widgets.ReactionList {} }),
                script_eval!(vm, { mod.widgets.ReplyPreviewContent {} }),
                script_eval!(vm, { mod.widgets.RoomsListEntryContent {} }),
            ] {
                let _widget = WidgetRef::script_from_value(vm, value);
            }
            let errors = vm.take_errors();
            assert!(errors.is_empty(), "actual app template errors: {errors:#?}");
        });
        assert_eq!(makepad_widgets::makepad_platform::shader_error::take(), None, "native shader diagnostics are independent of script errors");
    }

    #[test]
    fn theme_preferences_migrate_and_round_trip_in_existing_app_state() {
        use crate::shared::hepta_theme::HeptaTheme;
        for input in ["{}", r#"{"hepta_theme":"unknown-future-theme"}"#] {
            let prefs: AppPreferences = serde_json::from_str(input).unwrap();
            assert_eq!(prefs.hepta_theme, HeptaTheme::PolarPrism);
        }
        for choice in [HeptaTheme::DeepSpaceTitanium, HeptaTheme::PolarPrism, HeptaTheme::ObsidianCeramic] {
            let mut state = AppState::default();
            state.app_prefs.hepta_theme = choice;
            let saved = persistence::serialize_app_state(&state).unwrap();
            let restored: AppState = serde_json::from_slice(&saved).unwrap();
            assert_eq!(restored.app_prefs, state.app_prefs);
            let mut cx = Cx::new(Box::new(|_, _| {}));
            restored.app_prefs.on_hepta_theme_changed(&mut cx);
            assert_eq!(*cx.global::<HeptaTheme>(), choice);
            assert!(!restored.logged_in);
        }
    }

    #[test]
    fn prelogin_background_requires_real_color_shader() {
        let mut cx = Cx::new(Box::new(|_, _| {}));
        let (plain, solid) = cx.with_vm(|vm| {
            makepad_widgets::script_mod(vm);
            let plain = script_eval!(vm, {
                mod.widgets.View { show_bg: true draw_bg.color: #fff }
            });
            let plain = View::script_from_value(vm, plain);
            let solid = script_eval!(vm, {
                mod.widgets.SolidView { show_bg: true draw_bg.color: #fff }
            });
            (plain, View::script_from_value(vm, solid))
        });
        assert!(!opaque_color_shader(&mut cx, &plain));
        assert!(opaque_color_shader(&mut cx, &solid));
    }
    #[test]
    fn browser_fixture_is_explicit_and_cannot_mix_owner_parameters() {
        assert_eq!(browser_mode("").unwrap(), None);
        assert_eq!(
            browser_mode("?hepta-ui-fixture=login").unwrap(),
            Some("login".into())
        );
        assert_eq!(
            browser_mode("?hepta-ui-fixture=console").unwrap(),
            Some("console".into())
        );
        assert_eq!(
            browser_mode("?hepta-ui-fixture=login-usability").unwrap(),
            Some("login-usability".into())
        );
        for query in [
            "?hepta-ui-fixture",
            "?hepta-ui-fixture=",
            "?hepta-ui-fixture=other",
            "?hepta-ui-fixture=login&token=x",
            "?hepta-ui-fixture=login&hepta-ui-fixture=console",
        ] {
            assert!(browser_mode(query).is_err());
        }
    }
}
