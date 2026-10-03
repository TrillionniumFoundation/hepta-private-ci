//! Read-only observation of the explicit, account-free browser usability fixture.
//! No field contents, account data, focus changes or dispatched widget actions.
use super::*;
use crate::room::room_input_bar::RoomInputBarWidgetRefExt;
use crate::home::room_screen::RoomScreenWidgetRefExt;

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
        // Observe the actual visible navigation owner, never the first cached
        // RoomScreen found elsewhere in an inactive tab or adaptive variant.
        let desktop = app.ui.adaptive_view(cx, ids!(main_adaptive_view))
            .borrow().and_then(|view| view.active_variant()) == Some(live_id!(Desktop));
        let stack = app.ui.stack_navigation(cx, ids!(view_stack));
        let stack_view = stack.current_view().map(|id| stack.view_by_id(cx, id)).unwrap_or_default();
        let dock = app.ui.dock(cx, ids!(dock));
        let dock_selection: Vec<_> = dock.clone_state().unwrap_or_default().values().filter_map(|item| {
            if let DockItem::Tabs {tabs, selected, ..} = item { tabs.get(*selected).copied() } else { None }
        }).collect();
        let selected_id = app.app_state.selected_room.as_ref().map(|room| room.tab_id());
        let room_root = if desktop {
            selected_id.filter(|id| dock_selection.contains(id)).map(|id| dock.item(id)).unwrap_or_default()
        } else { stack_view.widget(cx, ids!(room_screen)) };
        let editor = room_root.text_input(cx, ids!(room_input_bar.mentionable_text_input.text_input));
        let displayed_room = room_root.as_room_screen().synthetic_displayed_room();
        let mut controls = serde_json::Map::new();
        let paths: &[(&str, &[LiveId])] = &[
            ("theme_a", ids!(theme_a)), ("theme_b", ids!(theme_b)), ("theme_c", ids!(theme_c)),
            ("header", ids!(room_header)), ("timeline", ids!(timeline.list)),
            ("composer", ids!(room_input_bar.mentionable_text_input.text_input)),
            ("back", ids!(header.content.button_container.left_button)),
            ("rooms_list", ids!(rooms_list)),
        ];
        for &(name, path) in paths {
            let widget = match name {
                "header" | "timeline" | "composer" => room_root.widget(cx, path),
                "back" => stack_view.widget(cx, path),
                _ => app.ui.widget(cx, path),
            };
            let area = widget.area();
            let valid = !area.is_empty() && area.is_valid(cx);
            let rect = if valid { area.clipped_rect(cx) } else { Rect::default() };
            controls.insert(name.into(), serde_json::json!({
                "valid": valid,
                "uid": format!("{:?}", widget.widget_uid()), "focused": valid && cx.has_key_focus(area),
                "clipped": [rect.pos.x, rect.pos.y, rect.size.x, rect.size.y],
            }));
        }
        let mut preview_geometry = Vec::new();
        if desktop {
            let rooms = app.ui.widget(cx, ids!(rooms_list));
            let list = rooms.portal_list(cx, ids!(list));
            for index in 0..16 {
                let Some((_, row)) = list.get_item(index) else { continue };
                let preview = row.widget(cx, ids!(latest_message.html_view.html));
                let area = preview.area();
                if area.is_empty() || !area.is_valid(cx) { continue; }
                let full = area.rect(cx); let clipped = area.clipped_rect(cx);
                preview_geometry.push(serde_json::json!({
                    "height": full.size.y, "clipped_height": clipped.size.y,
                    "visible": clipped.size.x > 1.0 && clipped.size.y > 1.0,
                }));
            }
        }
        log!("[hepta-chat-observation] {}", serde_json::json!({
            "sequence": sequence, "controls": controls,
            "room_preview_geometry": preview_geometry,
            "theme": cx.global::<crate::shared::hepta_theme::HeptaTheme>(),
            "draft_matches_fixture": editor.text() == "theme-draft-fixture",
            "draft_matches_research": editor.text() == "research-draft",
            "draft_empty": editor.text().is_empty(),
            "displayed_room": displayed_room,
            "desktop": desktop,
            "stack_transitioning": stack.is_transitioning(),
            "dock_selection_matches_room": selected_id.is_some_and(|id| dock_selection.contains(&id)),
            "selected_room": app.app_state.selected_room.as_ref().map(|r| r.room_id().as_str()),
            "selected_tab": format!("{:?}", app.app_state.selected_tab),
            "fixture_logged_in": app.app_state.logged_in,
            "send_context_unset": room_root.room_input_bar(cx, ids!(room_input_bar)).synthetic_send_context_unset(),
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
