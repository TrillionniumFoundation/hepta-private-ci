//! Synthetic data inserted into the real room-list and RoomScreen templates.
//! No SDK timeline, account, network, or delivery capability is created.
use makepad_widgets::*;
use crate::{
    app::SelectedRoom,
    home::rooms_list::{enqueue_rooms_list_update, JoinedRoomInfo, RoomsListAction, RoomsListRef, RoomsListUpdate},
    room::FetchedRoomAvatar,
    shared::{html_or_plaintext::HtmlOrPlaintextWidgetRefExt, text_or_image::TextOrImageWidgetRefExt},
    home::event_reaction_list::ReactionListWidgetRefExt,
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

#[derive(Default)]
struct FixtureDrawState {
    initialized: std::collections::HashSet<WidgetUid>,
    lists: std::collections::HashSet<WidgetUid>,
    image: Option<Texture>,
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
        if cx.global::<FixtureDrawState>().lists.insert(list.widget_uid()) {
            list.set_tail_range(false);
            list.set_first_id_and_scroll(0, 0.0);
        }
        while let Some(index) = list.next_visible_item(cx) {
            let Some((name, time, body)) = MESSAGES.get(index) else { continue; };
            let item = list.item(cx, index, if index == 0 { id!(ImageMessage) } else { id!(Message) });
            item.label(cx, ids!(username)).set_text(cx, name);
            item.label(cx, ids!(timestamp.ts_label)).set_text(cx, time);
            item.label(cx, ids!(avatar.text_view.text)).set_text(cx, ["◇", "◯", "△", "◈", "H"][index]);
            if index == 0 {
                item.view(cx, ids!(caption_view)).set_visible(cx, true);
                item.html_or_plaintext(cx, ids!(caption)).show_plaintext(cx, body);
            } else {
                item.html_or_plaintext(cx, ids!(content.message)).show_plaintext(cx, body);
            }
            if cx.global::<FixtureDrawState>().initialized.insert(item.widget_uid()) {
                if index == 0 {
                    // A small procedural material swatch, carried by the real
                    // ImageMessage/TextOrImage path. No files or media requests.
                    let texture = if let Some(texture) = cx.global::<FixtureDrawState>().image.clone() { texture } else {
                        let mut bytes = Vec::with_capacity(320 * 96 * 4);
                        for y in 0..96 {
                            for x in 0..320 {
                                let facet = ((x + y * 2) % 160) as u8;
                                bytes.extend_from_slice(&[25 + facet / 4, 23 + facet / 5, 50 + facet / 2, 255]);
                            }
                        }
                        let texture = image_cache::ImageBuffer::new(&bytes, 320, 96).unwrap().into_new_texture(cx);
                        cx.global::<FixtureDrawState>().image = Some(texture.clone());
                        texture
                    };
                    let _ = item.text_or_image(cx, ids!(content.message.image)).show_image(cx, None,
                        |cx, image| -> Result<(usize, usize), ()> { image.set_texture(cx, Some(texture)); Ok((320, 96)) });
                }
                if index == 2 {
                    item.widget(cx, ids!(replied_to_message)).set_visible(cx, true);
                    item.label(cx, ids!(reply_preview_username)).set_text(cx, "Mika · synthetic reply");
                    item.html_or_plaintext(cx, ids!(reply_preview_body)).show_plaintext(cx, "The room list and top tabs feel especially clean.");
                    item.reaction_list(cx, ids!(reaction_list)).set_fixture(cx, room(0).room_id().clone());
                }
            }
            item.draw_all(cx, scope);
        }
    }
    DrawStep::done()
}
