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
     width: Fill height: 52 padding: 8 is_multiline: true
     margin: 0
     draw_bg +: {border_size: 0.0 border_radius: 12.0}
     empty_text: "Write a local draft…"
    }
    send_message_button := mod.widgets.SendButton {
     enabled: false text: "Send"
     animator.disabled.default: @on
     margin: Inset{top: 4, left: 8, right: 6, bottom: 6}
    }
   }
  }
  cannot_send_notice := Label {
   width: Fill height: Fit flow: Flow.Right{wrap: true}
   padding: Inset{left: 14, right: 14, top: 0, bottom: 8} draw_text +: {color: TIMESTAMP_TEXT_COLOR text_style: theme.font_regular{font_size: 9}}
   text: "Local draft · chat owner unavailable"
  }
 }
}
