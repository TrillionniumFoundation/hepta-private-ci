//! Read-only observation of the explicit, account-free browser usability fixture.
//! No field contents, account data, focus changes or dispatched widget actions.
use super::*;

#[derive(Default)]
struct ObservationState {
    timer: Timer,
    sequence: u64,
}

pub(super) fn start(cx: &mut Cx) {
    let timer = cx.start_interval(0.1);
    cx.global::<ObservationState>().timer = timer;
}

pub(crate) fn observe(app: &App, cx: &mut Cx, event: &Event) {
    let state = cx.global::<ObservationState>();
    if state.timer.is_event(event).is_none() { return; }
    state.sequence += 1;
    let sequence = state.sequence;
    if super::chat_active(cx) {
        let mut controls = serde_json::Map::new();
        let paths: &[(&str, &[LiveId])] = &[
            ("theme_a", ids!(theme_a)), ("theme_b", ids!(theme_b)), ("theme_c", ids!(theme_c)),
            ("header", ids!(room_header)), ("timeline", ids!(timeline.list)),
            ("composer", ids!(room_input_bar.mentionable_text_input.text_input)),
        ];
        for &(name, path) in paths {
            let widget = app.ui.widget(cx, path);
            let area = widget.area();
            let rect = area.clipped_rect(cx);
            controls.insert(name.into(), serde_json::json!({
                "uid": format!("{:?}", widget.widget_uid()), "focused": cx.has_key_focus(area),
                "clipped": [rect.pos.x, rect.pos.y, rect.size.x, rect.size.y],
            }));
        }
        log!("[hepta-chat-observation] {}", serde_json::json!({
            "sequence": sequence, "controls": controls,
            "theme": cx.global::<crate::shared::hepta_theme::HeptaTheme>(),
            "draft_matches_fixture": app.ui.text_input(cx, ids!(room_input_bar.mentionable_text_input.text_input)).text() == "theme-draft-fixture",
            "selected_room": app.app_state.selected_room.as_ref().map(|r| r.room_id().as_str()),
            "selected_tab": format!("{:?}", app.app_state.selected_tab),
            "fixture_logged_in": app.app_state.logged_in,
            "console_authority": cx.global::<crate::hepta_console::ConsoleHost>().fixture_authority(),
        }));
        return;
    }
    let mut controls = serde_json::Map::new();
    let paths: &[(&str, &[LiveId])] = &[
        ("user_id_input", ids!(login_screen_view.login_screen.user_id_input)),
        ("password_input", ids!(login_screen_view.login_screen.password_input)),
        ("show_password_button", ids!(login_screen_view.login_screen.show_password_button)),
        ("hide_password_button", ids!(login_screen_view.login_screen.hide_password_button)),
        ("homeserver_input", ids!(login_screen_view.login_screen.homeserver_input)),
        ("login_button", ids!(login_screen_view.login_screen.login_button)),
        ("apple_button", ids!(login_screen_view.login_screen.apple_button)),
        ("facebook_button", ids!(login_screen_view.login_screen.facebook_button)),
        ("github_button", ids!(login_screen_view.login_screen.github_button)),
        ("gitlab_button", ids!(login_screen_view.login_screen.gitlab_button)),
        ("google_button", ids!(login_screen_view.login_screen.google_button)),
        ("twitter_button", ids!(login_screen_view.login_screen.twitter_button)),
        ("signup_button", ids!(login_screen_view.login_screen.signup_button)),
        ("open_hepta_console", ids!(login_screen_view.open_hepta_console)),
    ];
    for &(name, path) in paths {
        let widget = app.ui.widget(cx, path);
        let area = widget.area();
        let valid = !area.is_empty() && area.is_valid(cx);
        let rect = if valid { area.rect(cx) } else { Rect::default() };
        let clipped = if valid { area.clipped_rect(cx) } else { Rect::default() };
        controls.insert(name.into(), serde_json::json!({
            "valid": valid,
            "focused": valid && cx.has_key_focus(area),
            "size": [rect.size.x, rect.size.y],
            "clipped": [clipped.pos.x, clipped.pos.y, clipped.size.x, clipped.size.y],
        }));
    }
    // Compare only with this fixed synthetic draft; never export text or hashes.
    let draft_matches_fixture = app.ui
        .text_input(cx, ids!(login_screen_view.login_screen.user_id_input))
        .text() == "reachability-fixture";
    log!("[hepta-ui-observation] {}", serde_json::json!({
        "sequence": sequence,
        "focus_empty": cx.key_focus().is_empty(),
        "draft_matches_fixture": draft_matches_fixture,
        "controls": controls,
    }));
}
