// Derived from Project Robius / Robrix f2208f16184e1b2d8307dc9f98375e47b1fcd677.
// Copyright 2023–2026 Project Robius Developers. MIT; see ../../licenses/ROBRIX-MIT.txt.
// Source: src/shared/styles.rs. Resource-free semantic palette extraction, adapted for Hepta.
use makepad_widgets::*;
script_mod! {
 use mod.prelude.widgets.*
 use mod.widgets.*
 // Upstream shared/styles.rs:246, required by the adapted PortalList.
 mod.widgets.ListScrollBar = ScrollBar { bar_size: 9 }
 mod.widgets.COLOR_PRIMARY = #151e2b
 mod.widgets.COLOR_PRIMARY_DARKER = #101722
 mod.widgets.COLOR_SECONDARY = #202d3b
 mod.widgets.COLOR_ROBRIX_PURPLE = #53d4c3
 mod.widgets.COLOR_ACTIVE_PRIMARY = #204f59
 mod.widgets.COLOR_ACTIVE_PRIMARY_DARKER = #29626b
 mod.widgets.COLOR_LIST_ITEM_BG_HOVER = #263849
 mod.widgets.COLOR_TEXT = #e4edf5
 mod.widgets.TIMESTAMP_TEXT_COLOR = #aabcca
 mod.widgets.USERNAME_TEXT_STYLE = theme.font_bold {font_size: 12}
 mod.widgets.MESSAGE_TEXT_STYLE = theme.font_regular {font_size: 12 line_spacing: 1.3}
}
