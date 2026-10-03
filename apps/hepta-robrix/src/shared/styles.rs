use makepad_widgets::*;

script_mod! {

    use mod.prelude.widgets.*
    use mod.widgets.*

    mod.widgets.ICON_ADD              = crate_resource("self://resources/icons/add.svg")
    mod.widgets.ICON_ADD_REACTION     = crate_resource("self://resources/icons/add_reaction.svg")
    mod.widgets.ICON_ADD_PHOTO        = crate_resource("self://resources/icons/add_photo.svg")
    mod.widgets.ICON_ADD_USER         = crate_resource("self://resources/icons/add_user.svg")
    mod.widgets.ICON_ADD_WALLET       = crate_resource("self://resources/icons/add_wallet.svg")
    mod.widgets.ICON_FORBIDDEN        = crate_resource("self://resources/icons/forbidden.svg")
    mod.widgets.ICON_CHECKMARK        = crate_resource("self://resources/icons/checkmark.svg")
    mod.widgets.ICON_CLOSE            = crate_resource("self://resources/icons/close.svg")
    mod.widgets.ICON_CLOUD_CHECKMARK  = crate_resource("self://resources/icons/cloud_checkmark.svg")
    mod.widgets.ICON_CLOUD_OFFLINE    = crate_resource("self://resources/icons/cloud_offline.svg")
    mod.widgets.ICON_ROTATE_CW        = crate_resource("self://resources/icons/rotate_right.svg")
    mod.widgets.ICON_COPY             = crate_resource("self://resources/icons/copy.svg")
    mod.widgets.ICON_DOWNLOAD         = crate_resource("self://resources/icons/download.svg")
    mod.widgets.ICON_EDIT             = crate_resource("self://resources/icons/edit.svg")
    mod.widgets.ICON_EXTERNAL_LINK    = crate_resource("self://resources/icons/external_link.svg")
    mod.widgets.ICON_IMPORT           = crate_resource("self://resources/icons/import.svg")
    mod.widgets.ICON_HIERARCHY        = crate_resource("self://resources/icons/hierarchy.svg")
    mod.widgets.ICON_HOME             = crate_resource("self://resources/icons/home.svg")
    mod.widgets.ICON_HTML_FILE        = crate_resource("self://resources/icons/html_file.svg")
    mod.widgets.ICON_INFO             = crate_resource("self://resources/icons/info.svg")
    mod.widgets.ICON_INVITE           = crate_resource("self://resources/icons/invite.svg")
    mod.widgets.ICON_JOIN_ROOM        = crate_resource("self://resources/icons/join_room.svg")
    mod.widgets.ICON_JUMP             = crate_resource("self://resources/icons/go_back.svg")
    mod.widgets.ICON_LOCATION_PIN     = crate_resource("self://resources/icons/location-pin.svg")
    mod.widgets.ICON_LOGOUT           = crate_resource("self://resources/icons/logout.svg")
    mod.widgets.ICON_LINK             = crate_resource("self://resources/icons/link.svg")
    mod.widgets.ICON_PIN              = crate_resource("self://resources/icons/pin.svg")
    mod.widgets.ICON_REPLY            = crate_resource("self://resources/icons/reply.svg")
    mod.widgets.ICON_REPLY_IN_THREAD  = crate_resource("self://resources/icons/double_chat.svg")
    mod.widgets.ICON_SEARCH           = crate_resource("self://resources/icons/search.svg")
    mod.widgets.ICON_SEND             = crate_resource("self://resources/icons/send.svg")
    mod.widgets.ICON_SEND_ENCRYPTED   = crate_resource("self://resources/icons/send_encrypted.svg")
    mod.widgets.ICON_SEND_UNENCRYPTED = crate_resource("self://resources/icons/send_unencrypted.svg")
    mod.widgets.ICON_SETTINGS         = crate_resource("self://resources/icons/settings.svg")
    mod.widgets.ICON_SHARE            = crate_resource("self://resources/icons/share.svg")
    mod.widgets.ICON_SQUARES          = crate_resource("self://resources/icons/squares_filled.svg")
    mod.widgets.ICON_TOMBSTONE        = crate_resource("self://resources/icons/tombstone.svg")
    mod.widgets.ICON_TRASH            = crate_resource("self://resources/icons/trash.svg")
    mod.widgets.ICON_TRIANGLE_DOWN    = crate_resource("self://resources/icons/triangle_down_fill.svg")
    mod.widgets.ICON_TRIANGLE_UP      = crate_resource("self://resources/icons/triangle_up_fill.svg")
    mod.widgets.ICON_UPLOAD           = crate_resource("self://resources/icons/upload.svg")
    mod.widgets.ICON_VIEW_SOURCE      = crate_resource("self://resources/icons/view_source.svg")
    mod.widgets.ICON_WARNING          = crate_resource("self://resources/icons/warning.svg")
    mod.widgets.ICON_ZOOM_IN          = crate_resource("self://resources/icons/zoom_in.svg")
    mod.widgets.ICON_ZOOM_OUT         = crate_resource("self://resources/icons/zoom_out.svg")
    mod.widgets.ICON_ZOOM_TO_FIT      = crate_resource("self://resources/icons/zoom_to_fit.svg")
    mod.widgets.ICON_ADD_ATTACHMENT   = crate_resource("self://resources/icons/add_attachment.svg")
    mod.widgets.ICON_FILE             = crate_resource("self://resources/icons/file.svg")

    mod.widgets.TITLE_TEXT = theme.font_regular {
        font_size: (13),
    }

    mod.widgets.REGULAR_TEXT = theme.font_regular {
        font_size: (10),
    }

    mod.widgets.TEXT_SUB = theme.font_regular {
        font_size: (10),
    }

    mod.widgets.USERNAME_FONT_SIZE = 11

    mod.widgets.USERNAME_TEXT_COLOR = #xf0edff
    mod.widgets.USERNAME_TEXT_STYLE = theme.font_bold {
        font_size: (mod.widgets.USERNAME_FONT_SIZE),
    }

    mod.widgets.COLOR_ROBRIX_PURPLE = #xbba6ff; // the purple color from the Robrix logo

    mod.widgets.COLOR_ROBRIX_CYAN = #x72e5dd; // the cyan color from the Robrix logo

    mod.widgets.TYPING_NOTICE_TEXT_COLOR = #x72e5dd


    mod.widgets.MESSAGE_FONT_SIZE = 11
    mod.widgets.REDACTED_MESSAGE_FONT_SIZE = 10

    mod.widgets.MESSAGE_TEXT_COLOR = #xf0edff
    // notices (automated messages from bots) use a lighter color
    mod.widgets.COLOR_MESSAGE_NOTICE_TEXT = #xb9b0cb
    mod.widgets.MESSAGE_TEXT_LINE_SPACING = 1.3
    // This font should only be used for plaintext labels. Don't use this for Html content,
    // as the Html widget sets different fonts for different text styles (e.g., bold, italic).
    mod.widgets.MESSAGE_TEXT_STYLE = theme.font_regular {
        font_size: (mod.widgets.MESSAGE_FONT_SIZE),
        line_spacing: (mod.widgets.MESSAGE_TEXT_LINE_SPACING),
    }

    mod.widgets.MESSAGE_REPLY_PREVIEW_FONT_SIZE = 9.5



    mod.widgets.SMALL_STATE_FONT_SIZE = 9.0


    mod.widgets.SMALL_STATE_TEXT_COLOR = #xb9b0cb
    mod.widgets.SMALL_STATE_TEXT_STYLE = theme.font_regular {
        font_size: (mod.widgets.SMALL_STATE_FONT_SIZE),
    }

    mod.widgets.TIMESTAMP_FONT_SIZE = 8.5

    mod.widgets.TIMESTAMP_TEXT_COLOR = #x9589af
    mod.widgets.TIMESTAMP_TEXT_STYLE = theme.font_regular {
        font_size: (mod.widgets.TIMESTAMP_FONT_SIZE),
    }

    mod.widgets.ROOM_NAME_TEXT_COLOR = #xf0edff

    mod.widgets.COLOR_META = #xb9b0cb

    mod.widgets.COLOR_DIVIDER = #x4c4269

    mod.widgets.COLOR_DIVIDER_DARK = #x4c4269

    mod.widgets.COLOR_FG_ACCEPT_GREEN = #x72e5dd
    mod.widgets.COLOR_BG_ACCEPT_GREEN = #x173834
    mod.widgets.COLOR_FG_DANGER_RED = #xff9fae
    mod.widgets.COLOR_BG_DANGER_RED = #x40232f
    mod.widgets.COLOR_FG_DISABLED = #x9589af
    mod.widgets.COLOR_BG_DISABLED = #x2c2442
    mod.widgets.COLOR_INFO_BLUE = #x9ccaff
    mod.widgets.COLOR_WARNING_YELLOW = #xf2d397
    mod.widgets.COLOR_TEXT_WARNING_NOT_FOUND = #xf2d397

    // mod.widgets.COLOR_SELECT_TEXT = #A6CDFE
    // mod.widgets.COLOR_SELECT_TEXT = #B5D8FE
    // mod.widgets.COLOR_SELECT_TEXT = #6BB1FD88 // results in #B5D8FE when mixed halfway with white
    // mod.widgets.COLOR_SELECT_TEXT = #57A3FB44
    // 0x4C is ~30% opacity , which results in #B5D8FE when atop pure white
    // But i like the look of 0x33 20% opacity a little better.
    mod.widgets.COLOR_SELECT_TEXT = #x5c487c
    // mod.widgets.COLOR_SELECT_TEXT = #4D9BFD88 // results in #A6CDFE when mixed halfway with white

    mod.widgets.COLOR_BUTTON_INK = #x100d1d
    mod.widgets.COLOR_TEXT_SECONDARY = #xb9b0cb
    mod.widgets.COLOR_PRIMARY = #x171329

    mod.widgets.COLOR_PRIMARY_DARKER = #x0d0b19
    mod.widgets.COLOR_SECONDARY = #x231e39
    mod.widgets.COLOR_SECONDARY_DARKER = #x4c4269

    // A subtle raised material for room-list and timeline hover states.
    mod.widgets.COLOR_LIST_ITEM_BG_HOVER = #x201a33

    mod.widgets.COLOR_ACTIVE_PRIMARY = #xbba6ff

    mod.widgets.COLOR_ACTIVE_PRIMARY_DARKER = #xcebfff

    mod.widgets.COLOR_BG_PREVIEW = #x382e55

    mod.widgets.COLOR_BG_PREVIEW_HOVER = #x463666

    mod.widgets.COLOR_AVATAR_BG = #x30343c

    mod.widgets.COLOR_AVATAR_BG_IDLE = #x231e39


    mod.widgets.COLOR_UNREAD_BADGE_MENTIONS = #xff9fae;


    mod.widgets.COLOR_UNREAD_BADGE_MARKED = (mod.widgets.COLOR_ROBRIX_CYAN);
    mod.widgets.COLOR_UNREAD_BADGE_MESSAGES = #xb9b0cb


    mod.widgets.COLOR_TEXT_IDLE = #x9589af


    mod.widgets.COLOR_TEXT = #xf0edff
    mod.widgets.COLOR_TEXT_INPUT_IDLE = #x9589af

    mod.widgets.COLOR_TRANSPARENT = #00000000

    mod.widgets.COLOR_WARNING = #xf2d397

    mod.widgets.COLOR_LINK_HOVER = #x72e5dd


    // Use an even value for this, not odd, such that it can be divided in half,
    // which is needed when calculating the value of other widgets that scale with this.
    mod.widgets.NAVIGATION_TAB_BAR_SIZE = 64
    mod.widgets.NAVIGATION_TAB_BAR_AVATAR_SIZE = 40
    mod.widgets.NAVIGATION_TAB_BAR_AVATAR_FONT_SIZE = (mod.widgets.NAVIGATION_TAB_BAR_AVATAR_SIZE * 0.4)


    mod.widgets.COLOR_NAVIGATION_TAB_FG = (mod.widgets.COLOR_TEXT)
    mod.widgets.COLOR_NAVIGATION_TAB_FG_HOVER = (mod.widgets.COLOR_TEXT)
    mod.widgets.COLOR_NAVIGATION_TAB_FG_ACTIVE = (mod.widgets.COLOR_TEXT)
    mod.widgets.COLOR_NAVIGATION_TAB_BG = (mod.widgets.COLOR_SECONDARY)
    mod.widgets.COLOR_NAVIGATION_TAB_BG_HOVER = (mod.widgets.COLOR_LIST_ITEM_BG_HOVER)
    mod.widgets.COLOR_NAVIGATION_TAB_BG_ACTIVE = #x382e55

    mod.widgets.COLOR_IMAGE_VIEWER_BACKGROUND = #333333CC // 80% Opacity

    mod.widgets.COLOR_IMAGE_VIEWER_META_BACKGROUND = #x231e39

    // Ensure all settings buttons have a consistent height
    mod.widgets.SETTINGS_BUTTON_HEIGHT = 40

    // The font size used for regular (non-title, non-subsection) text
    // within any settings screen (e.g., dropdown labels, radio/toggle
    // labels, inline helper text inside a control).
    mod.widgets.SETTINGS_REGULAR_FONT_SIZE = 11
    mod.widgets.SETTINGS_REGULAR_TEXT_STYLE = theme.font_regular {
        font_size: (mod.widgets.SETTINGS_REGULAR_FONT_SIZE),
    }


    // A text input widget styled for Robrix.
    mod.widgets.RobrixTextInput = TextInput {
        width: Fill, height: Fit
        flow: Flow.Right{wrap: true},
        align: Align{y: 0.5}
        margin: 0,
        padding: 10,

        // For multiline text inputs, we want to show a light-colored scroll bar.
        scroll_bar +: {
            draw_bg +: {
            hepta_owned_material: uniform(1.0)
                color: #x9589af66
                color_hover: #xb9b0cb99
                color_drag: #xbba6ffcc
            }
        }

        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            border_radius: 8.0
            border_size: 1.0

            color: (mod.widgets.COLOR_PRIMARY)
            color_hover: (mod.widgets.COLOR_PRIMARY)
            color_focus: (mod.widgets.COLOR_PRIMARY)
            color_down: (mod.widgets.COLOR_PRIMARY)
            color_empty: (mod.widgets.COLOR_PRIMARY)
            color_disabled: (mod.widgets.COLOR_BG_DISABLED)

            border_color: (mod.widgets.COLOR_SECONDARY_DARKER)
            border_color_hover: (mod.widgets.COLOR_ACTIVE_PRIMARY)
            border_color_focus: (mod.widgets.COLOR_ACTIVE_PRIMARY_DARKER)
            border_color_down: (mod.widgets.COLOR_ACTIVE_PRIMARY_DARKER)
            border_color_empty: (mod.widgets.COLOR_SECONDARY_DARKER)
            border_color_disabled: (mod.widgets.COLOR_FG_DISABLED)

            color_2: vec4(-1.0, -1.0, -1.0, -1.0) // don't use color_2*
            border_color_2: vec4(-1.0, -1.0, -1.0, -1.0) // don't use border_color_2*
        }

        draw_selection +: {
            color: mod.widgets.COLOR_SELECT_TEXT
            // color: mix(mod.widgets.COLOR_BG_DISABLED, mod.widgets.COLOR_SELECT_TEXT, 0.5)
            color_hover:  (mod.widgets.COLOR_SELECT_TEXT)
            color_focus:  (mod.widgets.COLOR_SELECT_TEXT)
            color_down:  (mod.widgets.COLOR_SELECT_TEXT)
            color_empty:  (mod.widgets.COLOR_SELECT_TEXT)
            color_disabled: (mod.widgets.COLOR_SELECT_TEXT)
        }

        draw_cursor +: {
            color: (mod.widgets.MESSAGE_TEXT_COLOR)
        }

        draw_text +: {
            color: (mod.widgets.MESSAGE_TEXT_COLOR),
            color_hover: (mod.widgets.MESSAGE_TEXT_COLOR),
            color_focus: (mod.widgets.MESSAGE_TEXT_COLOR),
            color_down: (mod.widgets.MESSAGE_TEXT_COLOR),
            color_disabled: (mod.widgets.COLOR_FG_DISABLED),
            color_empty: (mod.widgets.COLOR_TEXT_SECONDARY),
            color_empty_hover: (mod.widgets.COLOR_TEXT_SECONDARY),
            color_empty_focus: (mod.widgets.COLOR_TEXT_SECONDARY),

            text_style: mod.widgets.MESSAGE_TEXT_STYLE {},
        }
    }

    // A read-only CodeView with our dark-material syntax highlighting colors.
    mod.widgets.LightCodeView = mod.widgets.CodeView {
        editor +: {
            word_wrap: true
            scroll_bars +: {
                show_scroll_x: false
                scroll_bar_y.drag_scrolling: true
            }
            draw_bg +: {
            hepta_owned_material: uniform(1.0) color: (mod.widgets.COLOR_TRANSPARENT) }

            // Dark-material syntax highlighting
            token_colors +: {
                whitespace: #x9589af,          // Gray for whitespace markers
                delimiter: #xf0edff,           // Dark gray for punctuation
                delimiter_highlight: #x9ccaff, // Blue for highlighted delimiters
                error_decoration: #xff9fae,    // Red for errors
                warning_decoration: #xf2d397,  // Dark yellow/amber for warnings

                unknown: #xf0edff,             // Default dark text
                branch_keyword: #xf3aed5,      // Red/pink for keywords (if, else, match)
                constant: #x9ccaff,            // Blue for constants
                identifier: #xf0edff,          // Dark gray for variables
                loop_keyword: #xf3aed5,        // Red/pink for loop keywords
                number: #x9ccaff,              // Blue for numbers
                other_keyword: #xf3aed5,       // Red/pink for other keywords
                punctuator: #xf0edff,          // Dark gray for punctuation
                string: #x72e5dd,              // Green for strings
                function: #xbba6ff,            // Purple for functions
                typename: #xf2d397,            // Orange for types
                comment: #x9589af,             // Gray for comments
            }
        }
    }

    // A read-only CodeView with dark-material color without any syntax highlighting.
    mod.widgets.PlainCodeView = mod.widgets.LightCodeView {
        editor +: {
            token_colors +: {
                whitespace: #xf0edff,
                delimiter_highlight: #xf0edff,
                error_decoration: #xf0edff,
                warning_decoration: #xf0edff,
                branch_keyword: #xf0edff,
                constant: #xf0edff,
                loop_keyword: #xf0edff,
                number: #xf0edff,
                other_keyword: #xf0edff,
                string: #xf0edff,
                function: #xf0edff,
                typename: #xf0edff,
                comment: #xf0edff,
            }
        }
    }
}


/// #171329
pub const COLOR_BUTTON_INK: Vec4 = crate::shared::hepta_theme::rgba(0x100d1dff);
pub const COLOR_PRIMARY:               Vec4 = super::hepta_theme::rgba(0x171329ff);
/// #BBA6FF
pub const COLOR_ACTIVE_PRIMARY:        Vec4 = super::hepta_theme::rgba(0xbba6ffff);
/// #CEBFFF
pub const COLOR_ACTIVE_PRIMARY_DARKER: Vec4 = super::hepta_theme::rgba(0xcebfffff);
/// #72E5DD
pub const COLOR_FG_ACCEPT_GREEN:       Vec4 = super::hepta_theme::rgba(0x72e5ddff);
/// #173834
pub const COLOR_BG_ACCEPT_GREEN:       Vec4 = super::hepta_theme::rgba(0x173834ff);
/// #9589AF
pub const COLOR_FG_DISABLED:           Vec4 = super::hepta_theme::rgba(0x9589afff);
/// #2C2442
pub const COLOR_BG_DISABLED:           Vec4 = super::hepta_theme::rgba(0x2c2442ff);
/// #F0EDFF
pub const COLOR_TEXT:                  Vec4 = super::hepta_theme::rgba(0xf0edffff);
/// #FF9FAE
pub const COLOR_FG_DANGER_RED:         Vec4 = super::hepta_theme::rgba(0xff9faeff);
/// #40232F
pub const COLOR_BG_DANGER_RED:         Vec4 = super::hepta_theme::rgba(0x40232fff);
/// #BBA6FF
pub const COLOR_ROBRIX_PURPLE:         Vec4 = super::hepta_theme::rgba(0xbba6ffff);
/// #72E5DD
pub const COLOR_ROBRIX_CYAN:           Vec4 = super::hepta_theme::rgba(0x72e5ddff);
/// #FF9FAE
pub const COLOR_UNREAD_BADGE_MENTIONS: Vec4 = super::hepta_theme::rgba(0xff9faeff);
/// #572DCC
pub const COLOR_UNREAD_BADGE_MARKED:   Vec4 = COLOR_ROBRIX_CYAN;
/// #B9B0CB
pub const COLOR_UNREAD_BADGE_MESSAGES: Vec4 = super::hepta_theme::rgba(0xb9b0cbff);
/// #FF6e00
pub const COLOR_UNKNOWN_ROOM_AVATAR:   Vec4 = vec4(1.0, 0.431, 0.0, 1.0);
/// #B9B0CB
pub const COLOR_MESSAGE_NOTICE_TEXT:   Vec4 = super::hepta_theme::rgba(0xb9b0cbff);
/// #F2D397
pub const COLOR_TEXT_WARNING_NOT_FOUND: Vec4 = super::hepta_theme::rgba(0xf2d397ff);
/// #382E55
pub const COLOR_BG_PREVIEW:            Vec4 = super::hepta_theme::rgba(0x382e55ff);
/// #463666
pub const COLOR_BG_PREVIEW_HOVER:      Vec4 = super::hepta_theme::rgba(0x463666ff);

/// Applies positive (green) button styling to the given button.
pub fn apply_positive_button_style(cx: &mut Cx, button: &mut ButtonRef) {
    script_apply_eval!(cx, button, {
        draw_bg +: {
            border_color: mod.widgets.COLOR_FG_ACCEPT_GREEN,
            color: mod.widgets.COLOR_BG_ACCEPT_GREEN,
            color_hover: #x224a44,
            color_down: #x2a5950,
        }
        draw_text +: {
            color: mod.widgets.COLOR_FG_ACCEPT_GREEN,
            color_hover: mod.widgets.COLOR_FG_ACCEPT_GREEN,
            color_down: mod.widgets.COLOR_FG_ACCEPT_GREEN,
        }
        draw_icon +: {
            color: mod.widgets.COLOR_FG_ACCEPT_GREEN,
        }
    });
}

/// Applies negative (red) button styling to the given button.
pub fn apply_negative_button_style(cx: &mut Cx, button: &mut ButtonRef) {
    script_apply_eval!(cx, button, {
        draw_bg +: {
            border_color: mod.widgets.COLOR_FG_DANGER_RED,
            color: mod.widgets.COLOR_BG_DANGER_RED,
            color_hover: #x52303f,
            color_down: #x61394b,
        }
        draw_text +: {
            color: mod.widgets.COLOR_FG_DANGER_RED,
            color_hover: mod.widgets.COLOR_FG_DANGER_RED,
            color_down: mod.widgets.COLOR_FG_DANGER_RED,
        }
        draw_icon +: {
            color: mod.widgets.COLOR_FG_DANGER_RED,
        }
    });
}

/// Applies neutral (gray) button styling to the given button.
pub fn apply_neutral_button_style(cx: &mut Cx, button: &mut ButtonRef) {
    script_apply_eval!(cx, button, {
        draw_bg +: {
            border_color: mod.widgets.COLOR_BG_DISABLED,
            color: mod.widgets.COLOR_SECONDARY,
            color_hover: #x382e55,
            color_down: #x463666,
        }
        draw_text +: {
            color: mod.widgets.COLOR_TEXT,
            color_hover: mod.widgets.COLOR_TEXT,
            color_down: mod.widgets.COLOR_TEXT,
        }
        draw_icon +: {
            color: mod.widgets.COLOR_TEXT,
        }
    });
}

/// Applies the primary (blue) button styling to the given button.
pub fn apply_primary_button_style(cx: &mut Cx, button: &mut ButtonRef) {
    script_apply_eval!(cx, button, {
        draw_bg +: {
            color: mod.widgets.COLOR_ACTIVE_PRIMARY,
            color_hover: mod.widgets.COLOR_ACTIVE_PRIMARY_DARKER,
            color_down: #xcebfff,
            border_color: #0000,
            border_color_hover: #0000,
            border_color_down: #0000,
        }
        draw_text +: {
            color: mod.widgets.COLOR_BUTTON_INK,
            color_hover: mod.widgets.COLOR_BUTTON_INK,
            color_down: mod.widgets.COLOR_BUTTON_INK,
        }
        draw_icon +: {
            color: mod.widgets.COLOR_BUTTON_INK,
        }
    });
}
