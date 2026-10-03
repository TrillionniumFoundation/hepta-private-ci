use super::*;
use crate::app::App;

#[test]
fn synthetic_room_order_survives_real_console_refilter() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let mut list = cx.with_vm(|vm| {
        let _ = <App as AppMain>::script_mod(vm);
        let value = script_eval!(vm, {mod.widgets.RoomsList {}});
        RoomsList::script_from_value(vm, value)
    });
    crate::app::ui_fixture::chat::populate();
    let mut state = AppState::default();
    let mut scope = Scope::with_data(&mut state);
    list.handle_rooms_list_updates(&mut cx, &Event::Actions(Vec::new()), &mut scope);
    let expected = list.displayed_regular_rooms.clone();
    assert_eq!(expected.len(), 6);
    let actions: Vec<Action> = vec![Box::new(NavigationBarAction::TabSelected(SelectedTab::Console))];
    list.handle_event(&mut cx, &Event::Actions(actions), &mut scope);
    assert_eq!(list.displayed_regular_rooms, expected);
    assert_eq!(list.all_joined_rooms.len(), 6);
}
