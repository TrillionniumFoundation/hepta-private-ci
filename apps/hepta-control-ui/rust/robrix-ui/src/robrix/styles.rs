// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Source: src/shared/styles.rs. Resource-free semantic palette extraction, adapted for Hepta.
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 // Upstream shared/styles.rs:246, required by the adapted PortalList.
 mod.widgets.ListScrollBar = ScrollBar { bar_size: 9 }
 mod.widgets.COLOR_PRIMARY = #x151522
 mod.widgets.COLOR_PRIMARY_DARKER = #x10111d
 mod.widgets.COLOR_SECONDARY = #x1a1a2e
 mod.widgets.COLOR_ROBRIX_PURPLE = #x9585ff
 mod.widgets.COLOR_ACTIVE_PRIMARY = #x34305e
 mod.widgets.COLOR_ACTIVE_PRIMARY_DARKER = #x45406f
 mod.widgets.COLOR_LIST_ITEM_BG_HOVER = #x25253e
 mod.widgets.COLOR_TEXT = #xeeebff
 mod.widgets.TIMESTAMP_TEXT_COLOR = #xb4b0c9
 mod.widgets.COLOR_AURORA_CORAL = #xffb3bc
 mod.widgets.COLOR_BORDER = #x37354f
 mod.widgets.AuroraButton = ButtonFlat {
  height: 40 padding: Inset{left: 14, right: 14, top: 8, bottom: 8} margin: 0
  draw_text +: {color: mod.widgets.COLOR_TEXT color_hover: mod.widgets.COLOR_TEXT color_focus: mod.widgets.COLOR_TEXT text_style: theme.font_regular{font_size: 11}}
  draw_bg +: {
   color: mod.widgets.COLOR_PRIMARY color_hover: mod.widgets.COLOR_LIST_ITEM_BG_HOVER color_focus: mod.widgets.COLOR_ACTIVE_PRIMARY
   color_down: mod.widgets.COLOR_ACTIVE_PRIMARY_DARKER color_disabled: mod.widgets.COLOR_PRIMARY
   border_radius: 10 border_size: 1 border_color: mod.widgets.COLOR_BORDER
   border_color_hover: mod.widgets.COLOR_ROBRIX_PURPLE border_color_focus: mod.widgets.COLOR_ROBRIX_PURPLE
  }
 }
 // Current page is independent of keyboard focus: theme controls must not look
 // like selected navigation merely because they retain focus after a click.
 mod.widgets.NavigationButton = mod.widgets.AuroraButton {
  draw_bg +: {
   current_page: uniform(0.0)
   pixel: fn() {
    let sdf = Sdf2d.viewport(self.pos * self.rect_size)
    sdf.box(0.5, 0.5, self.rect_size.x - 1.0, self.rect_size.y - 1.0, 10.0)
    let face = mix(self.color, self.color_hover, self.hover)
    sdf.fill_keep(mix(face, self.color_focus, self.current_page * 0.7))
    sdf.stroke(mix(self.border_color, self.border_color_focus, self.focus), 1.0)
    if self.current_page > 0.5 {
     sdf.move_to(14.0, self.rect_size.y - 5.0)
     sdf.line_to(self.rect_size.x - 14.0, self.rect_size.y - 5.0)
     sdf.stroke(self.border_color_focus, 2.0)
    }
    return sdf.result
   }
  }
 }
 mod.widgets.RailButton = mod.widgets.AuroraButton {
  width: Fill height: 44 padding: 0
  // Retain the action label in Button state; draw its visible icon in Rust.
  draw_text +: {get_color: fn() {return #0000}}
  draw_bg +: {
   icon_kind: uniform(0.0) ink: uniform(mod.widgets.COLOR_TEXT)
   pixel: fn() {
    let sdf = Sdf2d.viewport(self.pos * self.rect_size)
    sdf.box(1.0, 1.0, self.rect_size.x - 2.0, self.rect_size.y - 2.0, 12.0)
    sdf.fill_keep(mix(self.color, self.color_hover, self.hover))
    sdf.stroke(mix(self.border_color, self.border_color_focus, self.focus), 1.0)
    let center = self.rect_size * 0.5
    if self.icon_kind < 0.5 {
     sdf.box(center.x - 10.0, center.y - 8.0, 20.0, 14.0, 4.0)
     sdf.stroke(self.ink, 1.5)
     sdf.move_to(center.x - 6.0, center.y + 6.0)
     sdf.line_to(center.x - 6.0, center.y + 10.0)
     sdf.line_to(center.x - 1.0, center.y + 6.0)
     sdf.stroke(self.ink, 1.5)
    } else {
     sdf.move_to(center.x - 9.0, center.y - 6.0)
     sdf.line_to(center.x - 3.0, center.y)
     sdf.line_to(center.x - 9.0, center.y + 6.0)
     sdf.stroke(self.ink, 1.5)
     sdf.move_to(center.x + 1.0, center.y + 6.0)
     sdf.line_to(center.x + 9.0, center.y + 6.0)
     sdf.stroke(self.ink, 1.5)
    }
    return sdf.result
   }
  }
 }
 mod.widgets.SendButton = mod.widgets.AuroraButton {
  width: 40 height: 40 padding: 0
  // The real Button remains disabled until an authorized host is composed.
  // Keep its action name in state; platform accessibility remains unqualified.
  draw_text +: {get_color: fn() {return #0000}}
  draw_bg +: {
   accent: uniform(mod.widgets.COLOR_ROBRIX_PURPLE)
   ink: uniform(mod.widgets.COLOR_TEXT)
   pixel: fn() {
    let sdf = Sdf2d.viewport(self.pos * self.rect_size)
    let center = self.rect_size * 0.5
    let face = mix(self.accent, self.color_disabled, self.disabled)
    let ink = mix(self.ink, self.border_color, self.disabled)
    sdf.circle(center.x, center.y, min(self.rect_size.x, self.rect_size.y) * 0.5 - 1.0)
    sdf.fill_keep(face)
    let rim = mix(mix(self.accent, self.border_color_focus, self.focus), self.border_color, self.disabled)
    sdf.stroke(rim, 1.0)
    // A locked outline, not an active-looking send arrow, communicates that
    // the real owner is unavailable. Button.enabled remains authoritative.
    if self.disabled > 0.5 {
     sdf.box(center.x - 6.0, center.y - 1.0, 12.0, 10.0, 2.0)
     sdf.stroke(ink, 1.5)
     sdf.move_to(center.x - 4.0, center.y - 1.0)
     sdf.line_to(center.x - 4.0, center.y - 6.0)
     sdf.line_to(center.x + 4.0, center.y - 6.0)
     sdf.line_to(center.x + 4.0, center.y - 1.0)
     sdf.stroke(ink, 1.5)
     return sdf.result
    }
    sdf.move_to(center.x, center.y + 8.0)
    sdf.line_to(center.x, center.y - 8.0)
    sdf.move_to(center.x - 6.0, center.y - 2.0)
    sdf.line_to(center.x, center.y - 8.0)
    sdf.line_to(center.x + 6.0, center.y - 2.0)
    sdf.stroke(ink, 1.8)
    return sdf.result
   }
  }
 }
 mod.widgets.HeptaMark = View {
  width: Fill height: 56 show_bg: true
  draw_bg +: {accent: uniform(mod.widgets.COLOR_ROBRIX_PURPLE) pixel: fn() {
   let sdf = Sdf2d.viewport(self.pos * self.rect_size)
   let c = self.rect_size * 0.5
   sdf.move_to(c.x, c.y - 13.0)
   sdf.line_to(c.x + 11.0, c.y - 6.0)
   sdf.line_to(c.x + 11.0, c.y + 6.0)
   sdf.line_to(c.x, c.y + 13.0)
   sdf.line_to(c.x - 11.0, c.y + 6.0)
   sdf.line_to(c.x - 11.0, c.y - 6.0)
   sdf.close_path()
   sdf.stroke(self.accent, 1.5)
   sdf.move_to(c.x - 5.0, c.y - 5.0)
   sdf.line_to(c.x + 5.0, c.y + 5.0)
   sdf.stroke(self.accent, 1.5)
   return sdf.result
  }}
 }
 mod.widgets.AuroraNewConversation = mod.widgets.AuroraButton {
  height: 44
  draw_bg +: {color: mod.widgets.COLOR_SECONDARY color_2: mod.widgets.COLOR_ACTIVE_PRIMARY
   border_color: mod.widgets.COLOR_AURORA_CORAL border_color_2: mod.widgets.COLOR_ROBRIX_PURPLE
   gradient_border_horizontal: 1.0 border_size: 1.0}
 }
 mod.widgets.AuroraAvatar = RoundedView {
  width: 36 height: 36 align: Center
  draw_bg +: {color: mod.widgets.COLOR_ACTIVE_PRIMARY border_radius: 18 border_size: 1 border_color: mod.widgets.COLOR_ROBRIX_PURPLE}
  avatar := Label {height: Fit width: Fit text: "H" draw_text +: {color: mod.widgets.COLOR_TEXT text_style: theme.font_bold{font_size: 11}}}
 }
 mod.widgets.HEPTA_REGULAR = theme.font_regular {
  font_family: FontFamily {
   latin := FontMember {res: crate_resource("makepad_widgets:resources/IBMPlexSans-Text.ttf") asc: -0.1 desc: 0.0}
   cjk := FontMember {res: crate_resource("hepta_robrix_ui:resources/fonts/NotoSansSC-Regular.otf") asc: 0.0 desc: 0.0}
   rare := FontMember {res: crate_resource("makepad_widgets:resources/LXGWWenKaiRegular.ttf") asc: 0.0 desc: 0.0}
   emoji := FontMember {res: crate_resource("makepad_widgets:resources/NotoColorEmoji.ttf") asc: 0.0 desc: 0.0}
  }
 }
 mod.widgets.HEPTA_BOLD = theme.font_bold {
  font_family: FontFamily {
   latin := FontMember {res: crate_resource("makepad_widgets:resources/IBMPlexSans-SemiBold.ttf") asc: -0.1 desc: 0.0}
   cjk := FontMember {res: crate_resource("hepta_robrix_ui:resources/fonts/NotoSansSC-Bold.otf") asc: 0.0 desc: 0.0}
   rare := FontMember {res: crate_resource("makepad_widgets:resources/LXGWWenKaiBold.ttf") asc: 0.0 desc: 0.0}
   emoji := FontMember {res: crate_resource("makepad_widgets:resources/NotoColorEmoji.ttf") asc: 0.0 desc: 0.0}
  }
 }
 mod.widgets.USERNAME_TEXT_STYLE = mod.widgets.HEPTA_BOLD {font_size: 12}
 mod.widgets.MESSAGE_TEXT_STYLE = mod.widgets.HEPTA_REGULAR {font_size: 12 line_spacing: 1.3}
}
