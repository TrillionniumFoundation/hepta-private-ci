//! Synthetic data inserted into the real room-list and RoomScreen templates.
//! No SDK timeline, account, network, or delivery capability is created.
use makepad_widgets::*;
use crate::{
    app::SelectedRoom,
    home::rooms_list::{enqueue_rooms_list_update, JoinedRoomInfo, RoomsListAction, RoomsListRef, RoomsListUpdate},
    room::FetchedRoomAvatar,
    shared::html_or_plaintext::HtmlOrPlaintextWidgetRefExt,
    utils::RoomNameId,
};

const ROOMS: [(&str, &str); 6] = [
    ("Design Lab", "Concepts, critiques and craft"),
    ("Research", "Signals and exploration"),
    ("Foundation", "Principles and long-form thinking"),
    ("Prototypes", "Ideas in motion"),
    ("Field Notes", "Observations and links"),
    ("Studio", "Culture and craft"),
];

fn room(index: usize) -> RoomNameId {
    RoomNameId::new(matrix_sdk::RoomDisplayName::Named(ROOMS[index].0.into()),
        format!("!hepta-fixture-{index}:example.invalid").try_into().expect("synthetic room ID"))
}

pub(super) fn populate() {
    for (index, (_, preview)) in ROOMS.iter().enumerate() {
        enqueue_rooms_list_update(RoomsListUpdate::AddJoinedRoom(JoinedRoomInfo {
            room_name_id: room(index), num_unread_messages: 0, num_unread_mentions: 0,
            is_marked_unread: false, canonical_alias: None, alt_aliases: vec![],
            tags: Default::default(),
            latest: Some((ruma::MilliSecondsSinceUnixEpoch(ruma::UInt::try_from(1790992800000_u64 - index as u64 * 60000).unwrap()), (*preview).into())),
            room_avatar: FetchedRoomAvatar::Text(["◇", "◯", "△", "◈", "≋", "◒"][index].into()),
            // Suppress production first-visible avatar/pagination work.
            has_been_shown: true, is_selected: index == 0, is_direct: false, is_tombstoned: false,
        }));
    }
    enqueue_rooms_list_update(RoomsListUpdate::LoadedRooms { max_rooms: Some(6) });
}

pub(super) fn select_room(cx: &mut Cx) {
    let uid = cx.global::<RoomsListRef>().widget_uid();
    cx.widget_action(uid, RoomsListAction::Selected(SelectedRoom::JoinedRoom { room_name_id: room(0) }));
}

pub(crate) fn draw(view: &mut View, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
    // These are the production PortalList's Message templates, including its real
    // HTML/plaintext body, Avatar, Timestamp and RoomInputBar beneath the list.
    const MESSAGES: [(&str, &str, &str); 5] = [
        ("Arden", "10:04", "Here is the latest material study. The same Rust widgets now carry three distinct directions: Titanium, Prism and Ceramic."),
        ("Mika", "10:11", "The room list and top tabs feel especially clean. The quieter surfaces give the conversation room to breathe."),
        ("Jules", "10:16", "A shared foundation, with clear typography, restrained highlights and a composer that stays close to the conversation."),
        ("Rin", "10:24", "Try the theme buttons above. Your draft stays in the same composer while the material changes."),
        ("Design review", "10:28", "Synthetic UI fixture • no live account, connection or message delivery. All content on this screen is sample data."),
    ];
    while let Some(child) = view.draw_walk(cx, scope, walk).step() {
        let list = child.as_portal_list();
        let Some(mut list) = list.borrow_mut() else { continue; };
        list.set_item_range(cx, 0, MESSAGES.len());
        while let Some(index) = list.next_visible_item(cx) {
            let Some((name, time, body)) = MESSAGES.get(index) else { continue; };
            let item = list.item(cx, index, id!(Message));
            item.label(cx, ids!(username)).set_text(cx, name);
            item.label(cx, ids!(timestamp.ts_label)).set_text(cx, time);
            item.label(cx, ids!(avatar.text_view.text)).set_text(cx, ["◇", "◯", "△", "◈", "H"][index]);
            item.html_or_plaintext(cx, ids!(content.message)).show_plaintext(cx, body);
            item.draw_all(cx, scope);
        }
    }
    DrawStep::done()
}
