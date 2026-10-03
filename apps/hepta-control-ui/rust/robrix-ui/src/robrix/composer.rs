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
  height: Fit
  flow: Down
  new_batch: true
  margin: Inset{left: 16, right: 16, top: 8, bottom: 12}
  show_bg: true
  draw_bg +: {color: COLOR_PRIMARY border_radius: 18.0 border_color: COLOR_ROBRIX_PURPLE border_size: 1.0
   accent: uniform(COLOR_ROBRIX_PURPLE) secondary: uniform(COLOR_AURORA_CORAL)
   pixel: fn() {
    let sdf = Sdf2d.viewport(self.pos * self.rect_size)
    sdf.box(0.5, 0.5, self.rect_size.x - 1.0, self.rect_size.y - 1.0, 18.0)
    sdf.fill_keep(self.color)
    return sdf.stroke(mix(self.secondary, self.accent, self.pos.x), 1.0)
   }}
  overlay_wrapper := View {
   width: Fill
   height: Fit
   flow: Overlay
   input_bar := View {
    width: Fill
    height: Fit
    flow: Right
    align: Align{y: 1.0}
    padding: 6
    message_input := TextInput {
     width: Fill height: 64 padding: 10 is_multiline: true
     margin: Inset{top: 3, bottom: 5.75, left: 3, right: 3}
     empty_text: "Write a local draft…"
    }
    send_message_button := mod.widgets.AuroraButton {
     enabled: false text: "Send"
     padding: 8 margin: Inset{top: 4, left: 4, right: 4, bottom: 5}
    }
   }
  }
  cannot_send_notice := Label {
   width: Fill height: Fit flow: Flow.Right{wrap: true}
   padding: 8 draw_text.color: TIMESTAMP_TEXT_COLOR
   text: "Sending unavailable: no authenticated chat owner is configured. Draft stays local."
  }
 }
}
