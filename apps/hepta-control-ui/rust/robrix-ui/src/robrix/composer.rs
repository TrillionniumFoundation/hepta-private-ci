// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Source: src/room/room_input_bar.rs:35–179. Preserve capped rounded composer,
// overlay and bottom-aligned input/send layout; Matrix previews and send code removed.
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 mod.widgets.RoomInputBar = RoundedView {
  width: Fill
  height: Fit{max: FitBound.Rel{base: Base.Full, factor: 0.75}}
  flow: Down
  new_batch: true
  margin: Inset{left: -4, right: -4, bottom: -4}
  show_bg: true
  draw_bg +: {color: COLOR_PRIMARY border_radius: 5.0 border_color: COLOR_SECONDARY border_size: 2.0}
  overlay_wrapper := View {
   width: Fill
   height: Fit{max: FitBound.Rel{base: Base.Full, factor: 0.75}}
   flow: Overlay
   input_bar := View {
    width: Fill
    height: Fit{max: FitBound.Rel{base: Base.Full, factor: 0.75}}
    flow: Right
    align: Align{y: 1.0}
    padding: 6
    message_input := TextInput {
     width: Fill height: 92 is_multiline: true
     margin: Inset{top: 3, bottom: 5.75, left: 3, right: 3}
     empty_text: "Write a local draft…"
    }
    send_message_button := Button {
     enabled: false text: "Send"
     padding: 8 margin: Inset{top: 4, left: 4, right: 4, bottom: 5}
    }
   }
  }
  cannot_send_notice := Label {
   width: Fill height: Fit flow: Flow.Right{wrap: true}
   padding: 12 draw_text.color: COLOR_TEXT
   text: "Sending unavailable: no authenticated chat owner is configured. Draft stays local."
  }
 }
}
