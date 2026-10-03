use super::*;
use crate::app::App;

fn restored_destination(selection: SelectedTab) -> (SelectedTab, LiveId) {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let mut desktop = cx.with_vm(|vm| {
        let _ = <App as AppMain>::script_mod(vm);
        let value = script_eval!(vm, { mod.widgets.MainDesktopUI {} });
        MainDesktopUI::script_from_value(vm, value)
    });
    let mut state = AppState::default();
    state.selected_tab = selection;
    // A new adaptive desktop initially contains its Home default. Restoration
    // must apply the app's current Console destination after loading that tree.
    desktop.load_dock_state_from(&mut cx, &mut state, RestoreSelection::Saved);
    let snapshot = desktop.save_dock_state(&mut cx);
    let DockItem::Tabs { tabs, selected, .. } = &snapshot.dock_items[&id!(main_tabs)] else {
        panic!("missing real main tab container");
    };
    assert!(state.selected_room.is_none());
    assert!(snapshot.open_rooms.is_empty());
    (state.selected_tab, tabs[*selected])
}

#[test]
fn adaptive_console_restore_selects_real_console_after_dock_load() {
    assert_eq!(restored_destination(SelectedTab::Console), (SelectedTab::Console, id!(hepta_console_tab)));
}

#[test]
fn home_restore_keeps_the_existing_home_destination() {
    assert_eq!(restored_destination(SelectedTab::Home), (SelectedTab::Home, id!(home_tab)));
}

fn sample_room(name: &str, local: &str) -> SelectedRoom {
    SelectedRoom::JoinedRoom {room_name_id: RoomNameId::new(
        matrix_sdk::RoomDisplayName::Named(name.into()),
        format!("!{local}:example.invalid").try_into().unwrap(),
    )}
}

#[test]
fn adaptive_restore_uses_current_room_instead_of_older_saved_room() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let mut desktop = cx.with_vm(|vm| {
        let _ = <App as AppMain>::script_mod(vm);
        let value = script_eval!(vm, { mod.widgets.MainDesktopUI {} });
        MainDesktopUI::script_from_value(vm, value)
    });
    let mut state = AppState::default();
    let old = sample_room("Design Lab", "design");
    let current = sample_room("Research", "research");
    desktop.focus_or_create_tab(&mut cx, old);
    desktop.save_dock_state_to(&mut cx, &mut state);
    state.selected_room = Some(current.clone());
    desktop.load_dock_state_from(&mut cx, &mut state, RestoreSelection::Current(Some(current.clone())));
    assert_eq!(state.selected_room, Some(current.clone()));
    let saved = desktop.save_dock_state(&mut cx);
    let DockItem::Tabs {tabs, selected, ..} = &saved.dock_items[&id!(main_tabs)] else {panic!("tabs missing")};
    assert_eq!(tabs[*selected], current.tab_id());
}

fn initialized_desktop(cx: &mut Cx) -> MainDesktopUI {
    cx.with_vm(|vm| {
        let _ = <App as AppMain>::script_mod(vm);
        let value = script_eval!(vm, { mod.widgets.MainDesktopUI {} });
        MainDesktopUI::script_from_value(vm, value)
    })
}

#[test]
fn targeted_handoff_defers_under_modal_and_reads_newest_room_once() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let mut desktop = initialized_desktop(&mut cx);
    let mut state = AppState::default();
    state.logged_in = true;
    state.selected_room = Some(sample_room("Older mobile room", "older"));
    state.adaptive_dock_restore = Some(crate::home::adaptive_restore::AdaptiveDockRestore::capture());
    let actions: Vec<Action> = vec![Box::new(MainDesktopUiAction::LoadNewDock {target: desktop.widget_uid()})];
    cx.block_scrolling_except_within(Area::Empty);
    desktop.handle_actions(&mut cx, &actions, &mut Scope::with_data(&mut state));
    assert!(!desktop.has_loaded_dock);
    assert!(state.adaptive_dock_restore.is_some());
    let latest = sample_room("Newest room", "newest");
    state.selected_room = Some(latest.clone());
    cx.unblock_scrolling();
    desktop.handle_actions(&mut cx, &actions, &mut Scope::with_data(&mut state));
    assert!(state.adaptive_dock_restore.is_none());
    assert_eq!(desktop.most_recently_selected_room, Some(latest.clone()));
    // A duplicate initial-load message cannot restore the previous saved room.
    desktop.handle_actions(&mut cx, &actions, &mut Scope::with_data(&mut state));
    assert_eq!(state.selected_room, Some(latest));
}

#[test]
fn retired_widget_load_cannot_consume_new_owner_intent() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let old = initialized_desktop(&mut cx);
    let mut current = initialized_desktop(&mut cx);
    let mut state = AppState::default();
    state.logged_in = true;
    state.adaptive_dock_restore = Some(crate::home::adaptive_restore::AdaptiveDockRestore::capture());
    let actions: Vec<Action> = vec![Box::new(MainDesktopUiAction::LoadNewDock {target: old.widget_uid()})];
    current.handle_actions(&mut cx, &actions, &mut Scope::with_data(&mut state));
    assert!(!current.has_loaded_dock);
    assert!(state.adaptive_dock_restore.is_some());
}

#[test]
fn compact_back_to_list_restores_home_instead_of_saved_room() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let mut desktop = initialized_desktop(&mut cx);
    let mut state = AppState::default();
    desktop.focus_or_create_tab(&mut cx, sample_room("Saved", "saved"));
    desktop.save_dock_state_to(&mut cx, &mut state);
    state.selected_room = None;
    desktop.load_dock_state_from(&mut cx, &mut state, RestoreSelection::Current(None));
    let saved = desktop.save_dock_state(&mut cx);
    let DockItem::Tabs {tabs, selected, ..} = &saved.dock_items[&id!(main_tabs)] else {panic!("tabs missing")};
    assert_eq!(tabs[*selected], id!(home_tab));
    assert!(state.selected_room.is_none());
}
