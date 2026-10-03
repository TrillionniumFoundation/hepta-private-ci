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
    desktop.load_dock_state_from(&mut cx, &mut state);
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
