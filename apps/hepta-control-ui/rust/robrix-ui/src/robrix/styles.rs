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
   cjk := FontMember {res: crate_resource("makepad_widgets:resources/LXGWWenKaiRegular.ttf") asc: 0.0 desc: 0.0}
   emoji := FontMember {res: crate_resource("makepad_widgets:resources/NotoColorEmoji.ttf") asc: 0.0 desc: 0.0}
  }
 }
 mod.widgets.HEPTA_BOLD = theme.font_bold {
  font_family: FontFamily {
   latin := FontMember {res: crate_resource("makepad_widgets:resources/IBMPlexSans-SemiBold.ttf") asc: -0.1 desc: 0.0}
   cjk := FontMember {res: crate_resource("makepad_widgets:resources/LXGWWenKaiBold.ttf") asc: 0.0 desc: 0.0}
   emoji := FontMember {res: crate_resource("makepad_widgets:resources/NotoColorEmoji.ttf") asc: 0.0 desc: 0.0}
  }
 }
 mod.widgets.USERNAME_TEXT_STYLE = mod.widgets.HEPTA_BOLD {font_size: 12}
 mod.widgets.MESSAGE_TEXT_STYLE = mod.widgets.HEPTA_REGULAR {font_size: 12 line_spacing: 1.3}
}
