//! Robrix button colors and typography retained for the owner renderer.
//! Unused login, editor and network presentation definitions are not registered.
use makepad_widgets::*;
script_mod! {
    use mod.prelude.widgets.*
    use mod.widgets.*
    mod.widgets.COLOR_FG_ACCEPT_GREEN = #138808
    mod.widgets.COLOR_BG_ACCEPT_GREEN = #F0FFF0
    mod.widgets.COLOR_FG_DANGER_RED = #DC0005
    mod.widgets.COLOR_BG_DANGER_RED = #FFF0F0
    mod.widgets.COLOR_FG_DISABLED = #B3B3B3
    mod.widgets.COLOR_BG_DISABLED = #E0E0E0
    mod.widgets.COLOR_PRIMARY = #ffffff
    mod.widgets.COLOR_SECONDARY = #E3E3E3
    mod.widgets.COLOR_ACTIVE_PRIMARY = #0f88fe
    mod.widgets.COLOR_ACTIVE_PRIMARY_DARKER = #106fcc
    mod.widgets.COLOR_TEXT = #1C274C
    mod.widgets.REGULAR_TEXT = theme.font_regular { font_size: 10 }
}
