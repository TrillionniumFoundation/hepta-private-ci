//! Read-only diagnostics for the dedicated compact-sidebar browser fixture.
//! This module is absent from normal builds and never dispatches an action.
use hepta_control_core::chat::{ChatWorkspace, WorkspaceTab};
use makepad_widgets::*;

#[derive(Clone)]
struct DrawnSidebar {
    // Actual sidebar, brand, group, search and New draft widget areas.
    areas: [Area; 5],
    rooms: Vec<(u64, Area)>,
}

#[derive(Default)]
struct SidebarFixture {
    drawn: Option<DrawnSidebar>,
    last: String,
    sample: u64,
    geometry_frame: u64,
    geometry: Option<String>,
}

/// Remember actual widget areas; resolve them only after the Root event ends.
pub(crate) fn remember_draw(cx: &mut Cx, areas: [Area; 5], rooms: Vec<(u64, Area)>) {
    cx.global::<SidebarFixture>().drawn = Some(DrawnSidebar { areas, rooms });
}

/// Preserve every actual finalized room draw, including equal geometry after a
/// selection/resize. The existing host geometry log remains deduplicated.
pub(crate) fn remember_room_geometry(cx: &mut Cx, geometry: String) {
    let frame = cx.redraw_id;
    let state = cx.global::<SidebarFixture>();
    state.geometry_frame = frame;
    state.geometry = Some(geometry);
}

fn rectangle(cx: &Cx, area: Area) -> String {
    if !area.is_valid(cx) {
        return "null".into();
    }
    let rect = area.rect(cx);
    let values = [rect.pos.x, rect.pos.y, rect.size.x, rect.size.y];
    if values.iter().all(|value| value.is_finite()) {
        format!("{values:?}")
    } else {
        "null".into()
    }
}

fn clipped_rectangle(cx: &Cx, area: Area) -> String {
    if !area.is_valid(cx) {
        return "null".into();
    }
    let rect = area.clipped_rect(cx);
    let values = [rect.pos.x, rect.pos.y, rect.size.x, rect.size.y];
    if values.iter().all(|value| value.is_finite()) {
        format!("{values:?}")
    } else {
        "null".into()
    }
}

// Text Areas contain one instance per glyph. Area::rect reports the first
// instance; the clipped union is the real complete visible text extent.
fn visible_glyphs(cx: &Cx, area: Area) -> String {
    if !area.is_valid(cx) {
        return "null".into();
    }
    let rect = area.clipped_rect_union(cx);
    let values = [rect.pos.x, rect.pos.y, rect.size.x, rect.size.y];
    if values.iter().all(|value| value.is_finite()) {
        format!("{values:?}")
    } else {
        "null".into()
    }
}

/// Publish bounded numeric state, never draft text, account or owner data.
/// Repeated stable draws are quiet; key-up/mouse-up receipts allow the test to
/// distinguish an observed unchanged result from a stale pre-input sample.
pub(crate) fn after_event(cx: &mut Cx, workspace: &ChatWorkspace, ui: &WidgetRef, event: &Event) {
    let drawn = cx.global::<SidebarFixture>().drawn.clone();
    let ids: Vec<_> = workspace.drafts().map(|(id, _)| id).collect();
    let new_draft = drawn.as_ref().map_or(Area::Empty, |drawn| drawn.areas[4]);
    let new_draft_valid = new_draft.is_valid(cx);
    let new_draft_focused = new_draft_valid && cx.key_focus() == new_draft;
    let targets = if workspace.navigation_open {
        drawn.map(|drawn| {
            let rooms = drawn
                .rooms
                .into_iter()
                .map(|(room, area)| format!("{{\"room\":{room},\"area\":{}}}", rectangle(cx, area)))
                .collect::<Vec<_>>()
                .join(",");
            format!(
                "{{\"sidebar\":{},\"brand\":{},\"group\":{},\"search\":{},\"newDraft\":{},\"newDraftClipped\":{},\"rooms\":[{}]}}",
                rectangle(cx, drawn.areas[0]),
                visible_glyphs(cx, drawn.areas[1]),
                visible_glyphs(cx, drawn.areas[2]),
                rectangle(cx, drawn.areas[3]),
                rectangle(cx, drawn.areas[4]),
                clipped_rectangle(cx, drawn.areas[4]),
                rooms
            )
        })
    } else {
        // The compact navigation page is closed. Preserve raw validity/focus
        // observations below, but never advertise hidden targets for clicking.
        None
    };
    let controls = [
        ("conversations", ids!(conversations)),
        ("backToChat", ids!(back_to_chat)),
        ("chat", ids!(chat_tab)),
        ("console", ids!(console_tab_button)),
        ("theme", ids!(mobile_theme_switch)),
        ("editor", ids!(message_input)),
        ("send", ids!(send_message_button)),
    ]
    .into_iter()
    .map(|(name, id)| {
        let area = ui.widget(cx, id).area();
        format!("\"{name}\":{}", rectangle(cx, area))
    })
    .collect::<Vec<_>>()
    .join(",");
    let theme = cx
        .global::<crate::visual_theme::ThemeState>()
        .selected
        .label();
    // Use the existing interior mark, drawn in the shared header on both
    // adaptive variants. The full-width bar can legitimately cover the SDK's
    // ceil-aligned pass overscan; retain it separately without using it as a
    // supposedly wholly visible probe or inferring scale from screenshot DPR.
    let dpi_bar = ui.widget(cx, ids!(brand_bar)).area();
    let dpi_probe = ui.widget(cx, ids!(brand_mark)).area();
    let draw_dpi_factor = if dpi_probe.is_valid(cx) {
        let dpi = cx.get_dpi_factor_of(&dpi_probe);
        if dpi.is_finite() && dpi > 0.0 {
            dpi.to_string()
        } else {
            "null".into()
        }
    } else {
        "null".into()
    };
    let geometry_frame = cx.global::<SidebarFixture>().geometry_frame;
    let geometry = cx.global::<SidebarFixture>().geometry.clone();
    let serialized = format!(
        "{{\"active\":{},\"draftIds\":{:?},\"count\":{},\"draftBytes\":{},\"navigationOpen\":{},\"consoleOpen\":{},\"theme\":{:?},\"newDraftAreaValid\":{},\"newDraftFocused\":{},\"keyFocusValid\":{},\"controls\":{{{}}},\"targets\":{},\"geometryFrame\":{},\"geometry\":{},\"drawDpiFactor\":{},\"dpiProbe\":{},\"dpiProbeRaw\":{},\"dpiBarRaw\":{},\"dpiBarClipped\":{}}}",
        workspace.active_id(),
        ids,
        ids.len(),
        workspace.draft().text.len(),
        workspace.navigation_open,
        workspace.tab == WorkspaceTab::Console,
        theme,
        new_draft_valid,
        new_draft_focused,
        cx.key_focus().is_valid(cx),
        controls,
        targets.unwrap_or_else(|| "null".into()),
        geometry_frame,
        geometry.unwrap_or_else(|| "null".into()),
        draw_dpi_factor,
        clipped_rectangle(cx, dpi_probe),
        rectangle(cx, dpi_probe),
        rectangle(cx, dpi_bar),
        clipped_rectangle(cx, dpi_bar)
    );
    let receipt = match event {
        Event::KeyUp(_) => "key-up",
        Event::MouseUp(_) => "mouse-up",
        Event::Draw(_) => "draw",
        _ => "state",
    };
    let input_finished = matches!(event, Event::KeyUp(_) | Event::MouseUp(_));
    let state = cx.global::<SidebarFixture>();
    if state.last == serialized && !input_finished {
        return;
    }
    state.last = serialized.clone();
    state.sample = state.sample.saturating_add(1);
    let sample = state.sample;
    log!(
        "HEPTA_FIXTURE_SIDEBAR sample={} frame={} receipt={} {}",
        sample,
        cx.redraw_id,
        receipt,
        serialized
    );
}
