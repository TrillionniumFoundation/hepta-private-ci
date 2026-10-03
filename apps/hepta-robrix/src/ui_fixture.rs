//! Compile-time gated, account-free rendering fixtures of the real application.
//! Startup returns before keyring, filesystem state, Matrix and console owners.
use super::*;

#[derive(Default)]
struct FixtureState {
    active: bool,
    console: bool,
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
    state.select_timer = timer;
    app.app_state.logged_in = mode == "console";
    app.ui
        .window(cx, ids!(main_window))
        .set_title(cx, "Hepta · UI fixture · no live accounts");
    let host = cx.global::<crate::hepta_console::ConsoleHost>();
    host.set_fixture_unconfigured();
    app.update_login_visibility(cx);
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

pub(super) fn active(cx: &mut Cx) -> bool {
    cx.global::<FixtureState>().active
}

pub(super) fn event(cx: &mut Cx, event: &Event) {
    let state = cx.global::<FixtureState>();
    if state.active && state.console && state.select_timer.is_event(event).is_some() {
        state.select_timer = Timer::default();
        cx.action(NavigationBarAction::OpenConsole);
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
    if !matches!(mode.as_str(), "login" | "console") {
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
    if !matches!(mode, "login" | "console") {
        return Err("unsupported fixture mode");
    }
    Ok(Some(mode.to_owned()))
}

#[cfg(test)]
mod tests {
    use super::*;

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
