//! Local presentation preferences. No session, transport, or runtime authority.
use makepad_widgets::*;
use std::collections::HashSet;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum VisualTheme {
    ObsidianIce,
    LunarTitanium,
    #[default]
    AuroraGraphite,
}
impl VisualTheme {
    pub fn next(self) -> Self {
        match self {
            Self::ObsidianIce => Self::LunarTitanium,
            Self::LunarTitanium => Self::AuroraGraphite,
            Self::AuroraGraphite => Self::ObsidianIce,
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Self::ObsidianIce => "Obsidian Ice",
            Self::LunarTitanium => "Lunar Titanium",
            Self::AuroraGraphite => "Aurora Graphite",
        }
    }
    pub fn sidebar_width(self) -> f64 {
        match self {
            Self::ObsidianIce => 300.0,
            Self::LunarTitanium => 280.0,
            Self::AuroraGraphite => 248.0,
        }
    }
    pub fn tokens(self) -> Tokens {
        let values = match self {
            Self::ObsidianIce => [
                0x0c131dff, 0x151f2bff, 0x202e40ff, 0xe8f2ffff, 0xa7b8ceff, 0x63bdffff, 0x31506bff,
                0x284665ff, 0x8ed9ffff,
            ],
            Self::LunarTitanium => [
                0xf3f5f7ff, 0xe9eef1ff, 0xfffffff0, 0x18232cff, 0x52616dff, 0x267d8cff, 0xc5d1d8ff,
                0xd4e7ebff, 0x267d8cff,
            ],
            Self::AuroraGraphite => [
                0x10111dff, 0x1a1a2eff, 0x222238ff, 0xeeebffff, 0xb4b0c9ff, 0x9585ffff, 0x37354fff,
                0x34305eff, 0xffb3bcff,
            ],
        };
        let [
            canvas,
            panel,
            surface,
            text,
            muted,
            accent,
            border,
            selected,
            secondary,
        ] = values.map(Vec4f::from_u32);
        Tokens {
            canvas,
            panel,
            surface,
            text,
            muted,
            accent,
            border,
            selected,
            secondary,
        }
    }
}
#[derive(Clone, Copy)]
pub struct Tokens {
    pub canvas: Vec4f,
    pub panel: Vec4f,
    pub surface: Vec4f,
    pub text: Vec4f,
    pub muted: Vec4f,
    pub accent: Vec4f,
    pub border: Vec4f,
    pub selected: Vec4f,
    pub secondary: Vec4f,
}
#[derive(Default)]
pub struct ThemeState {
    pub selected: VisualTheme,
    styled: HashSet<WidgetUid>,
}
pub fn cycle(cx: &mut Cx) {
    let state = cx.global::<ThemeState>();
    state.selected = state.selected.next();
    state.styled.clear();
    cx.redraw_all();
}

/// Recolour existing widget instances. Never rebuild the tree or touch editor
/// text, undo, selection, focus, owner identity or PortalList scroll position.
pub fn apply_tree(cx: &mut Cx, root: &WidgetRef) {
    let theme = cx.global::<ThemeState>().selected;
    let tokens = theme.tokens();
    let mut stack = vec![(LiveId(0), root.clone())];
    let mut count = 0;
    while let Some((name, mut widget)) = stack.pop() {
        count += 1;
        if count > 4096 {
            break;
        }
        widget.children(&mut |id, child| stack.push((id, child)));
        if widget.is_empty() || !cx.global::<ThemeState>().styled.insert(widget.widget_uid()) {
            continue;
        }
        let Tokens {
            canvas,
            panel,
            surface,
            text,
            muted,
            accent,
            border,
            selected,
            secondary,
        } = tokens;
        if widget.borrow::<Label>().is_some() {
            if name == id!(username) || name == id!(room_name) {
                script_apply_eval!(cx,widget,{draw_text +: {text_style +: {font_family: mod.widgets.HEPTA_BOLD.font_family}}});
            } else {
                script_apply_eval!(cx,widget,{draw_text +: {text_style +: {font_family: mod.widgets.HEPTA_REGULAR.font_family}}});
            }
            widget.as_label().set_text_color(
                cx,
                if name == id!(send_status_indicator)
                    || name == id!(cannot_send_notice)
                    || name == id!(preview)
                    || name == id!(presentation_note)
                {
                    muted
                } else {
                    text
                },
            );
        } else if widget.borrow::<TextInput>().is_some() {
            script_apply_eval!(cx,widget,{
                draw_cursor +: {color: #(accent) color_focus: #(accent)}
                draw_selection +: {color: #(selected) color_focus: #(selected)}
                draw_bg +: {color: #(surface) color_empty: #(surface) color_focus: #(surface) border_color: #(border) border_color_focus: #(accent)}
                draw_text +: {text_style +: {font_family: mod.widgets.HEPTA_REGULAR.font_family} color: #(text) color_hover: #(text) color_focus: #(text) color_empty: #(muted) color_empty_hover: #(muted) color_empty_focus: #(muted)}
            });
        } else if widget.borrow::<Button>().is_some() {
            script_apply_eval!(cx,widget,{
                draw_bg +: {color: #(surface) color_2: #(surface) color_hover: #(selected) color_2_hover: #(selected) color_focus: #(selected) color_disabled: #(panel) border_color: #(border) border_color_focus: #(accent) border_color_hover: #(accent)}
                draw_text +: {text_style +: {font_family: mod.widgets.HEPTA_REGULAR.font_family} color: #(text) color_hover: #(text) color_focus: #(text) color_disabled: #(muted)}
            });
            if name == id!(rail_chat) || name == id!(rail_console) {
                script_apply_eval!(cx,widget,{draw_bg +: {ink: #(text)}});
            }
            if name == id!(send_message_button) {
                script_apply_eval!(cx,widget,{draw_bg +: {accent: #(accent) ink: #(text)}});
            }
            if name == id!(theme_switch) || name == id!(mobile_theme_switch) {
                widget.as_button().set_text(cx, theme.label());
            }
        } else if widget.borrow::<Tab>().is_some() {
            script_apply_eval!(cx,widget,{
                draw_bg +: {accent: #(accent) secondary: #(secondary) color: #(panel) color_2: #(panel) color_active: #(selected) color_2_active: #(selected) color_hover: #(surface) color_2_hover: #(surface)}
                draw_text +: {color: #(muted) color_active: #(text)}
            });
        } else if widget
            .borrow::<crate::robrix::home::MainDesktopUI>()
            .is_some()
        {
            script_apply_eval!(cx,widget,{draw_bg +: {color: #(panel)}});
        } else if widget
            .borrow::<crate::robrix::rooms::RoomsSideBar>()
            .is_some()
        {
            script_apply_eval!(cx,widget,{draw_bg +: {color: #(panel) accent: #(accent)}});
        } else if widget
            .borrow::<crate::robrix::rooms::RoomsListEntry>()
            .is_some()
        {
            script_apply_eval!(cx,widget,{draw_bg +: {color_hover: #(surface) color_selected: #(selected) color_selected_hover: #(selected)}});
        } else if widget.borrow::<Dock>().is_some() {
            let width = theme.sidebar_width();
            widget.as_dock().set_splitter_align(
                cx,
                id!(root),
                SplitterAlign::FromA(width),
                /*mark_dirty*/ false,
            );
        } else if widget.borrow::<Image>().is_some() && name == id!(lunar_background) {
            widget
                .as_image()
                .set_visible(cx, theme == VisualTheme::LunarTitanium);
        } else if widget.borrow::<View>().is_some() {
            // RoomScreen owns role-aware message surfaces. A generic pass must
            // not erase the user's bubble after its direct child style applies.
            if name == id!(content) {
                continue;
            }
            let color = if name == id!(room_screen_wrapper) {
                canvas
            } else {
                panel
            };
            script_apply_eval!(cx,widget,{draw_bg +: {color: #(color)}});
            if name == id!(room_screen_wrapper) {
                script_apply_eval!(cx,widget,{draw_bg +: {accent: #(accent) secondary: #(secondary)}});
            }
            if name == id!(brand_mark) {
                script_apply_eval!(cx,widget,{draw_bg +: {accent: #(accent)}});
            }
            if name == id!(avatar_frame) {
                script_apply_eval!(cx,widget,{draw_bg +: {color: #(selected) border_color: #(accent)}});
            }
            if name == id!(room_input_bar) {
                script_apply_eval!(cx,widget,{draw_bg +: {color: #(surface) accent: #(accent) secondary: #(secondary)}});
            }
        }
    }
}
