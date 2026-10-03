use makepad_widgets::*;

script_mod! {
    use mod.prelude.widgets.*
    use mod.widgets.*

    // The base Robrix button widget.
    // Uses COLOR_ACTIVE_PRIMARY (blue) background with white text by default.
    // See also the preset variants below:
    //   RobrixPositiveIconButton, RobrixNegativeIconButton, RobrixNeutralIconButton.
    mod.widgets.RobrixIconButton = Button {
        width: Fit,
        height: Fit,
        spacing: 10,
        padding: 10,
        align: Align{x: 0, y: 0.5}

        // Keyboard focus has a visible edge; it does not alter button authority.
        animator +: {
            focus: {
                default: @off
                off: AnimatorState {
                    from: {all: Forward {duration: 0.0}}
                    apply: {
                        draw_bg: {focus: 0.0}
                        draw_text: {focus: 0.0}
                    }
                }
                on: AnimatorState {
                    from: {all: Forward {duration: 0.0}}
                    apply: {
                        draw_bg: {focus: 1.0}
                        draw_text: {focus: 0.0}
                    }
                }
            }
        }

        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            border_size: 1.0
            border_radius: 8.0

            color: (COLOR_ACTIVE_PRIMARY)
            color_hover: (COLOR_ACTIVE_PRIMARY_DARKER)
            color_down: (COLOR_ACTIVE_PRIMARY_DARKER)
            color_disabled: (COLOR_BG_DISABLED)

            border_color: #0000
            border_color_hover: #0000
            border_color_down: #0000
            border_color_focus: (COLOR_TEXT)
            border_color_disabled: #0000

            // Disable gradient (color_2) by default
            color_2: vec4(-1.0, -1.0, -1.0, -1.0)
            border_color_2: vec4(-1.0, -1.0, -1.0, -1.0)
        }

        draw_icon: mod.draw.DrawSvg {
            hepta_owned_material: uniform(1.0)
            color: (COLOR_BUTTON_INK)
            get_color: fn() {
                let base = self.eval_gradient()
                if self.hepta_owned_material > 0.5 && self.color.x >= 0.0 {
                    return vec4(self.color.rgb*self.color.a*base.a, self.color.a*base.a)
                }
                return base
            }
        }
        icon_walk: Walk{width: 16, height: 16}

        draw_text +: {
            color: (COLOR_BUTTON_INK)
            color_hover: (COLOR_BUTTON_INK)
            color_down: (COLOR_BUTTON_INK)
            color_disabled: (COLOR_FG_DISABLED)
            text_style: mod.widgets.REGULAR_TEXT {font_size: 10},
        }
        text: ""
    }

    // Green button for positive/accept actions: joining a room, confirming, accepting an invite.
    mod.widgets.RobrixPositiveIconButton = mod.widgets.RobrixIconButton {
        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            border_color: (COLOR_FG_ACCEPT_GREEN)
            border_color_hover: (COLOR_FG_ACCEPT_GREEN)
            border_color_down: (COLOR_FG_ACCEPT_GREEN)
            color: (COLOR_BG_ACCEPT_GREEN)
            color_hover: #x224a44
            color_down: #x2a5950
        }
        draw_icon.color: (COLOR_FG_ACCEPT_GREEN)
        draw_text +: {
            color: (COLOR_FG_ACCEPT_GREEN)
            color_hover: (COLOR_FG_ACCEPT_GREEN)
            color_down: (COLOR_FG_ACCEPT_GREEN)
        }
    }

    // Red button for negative/dangerous actions: rejecting, leaving, deleting, blocking.
    mod.widgets.RobrixNegativeIconButton = mod.widgets.RobrixIconButton {
        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            border_color: (COLOR_FG_DANGER_RED)
            border_color_hover: (COLOR_FG_DANGER_RED)
            border_color_down: (COLOR_FG_DANGER_RED)
            color: (COLOR_BG_DANGER_RED)
            color_hover: #x52303f
            color_down: #x61394b
        }
        draw_icon.color: (COLOR_FG_DANGER_RED)
        draw_text +: {
            color: (COLOR_FG_DANGER_RED)
            color_hover: (COLOR_FG_DANGER_RED)
            color_down: (COLOR_FG_DANGER_RED)
        }
    }

    // Gray button for cancel/dismiss actions: canceling, closing, going back.
    mod.widgets.RobrixNeutralIconButton = mod.widgets.RobrixIconButton {
        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            border_color: (COLOR_BG_DISABLED)
            border_color_hover: (COLOR_BG_DISABLED)
            border_color_down: (COLOR_BG_DISABLED)
            color: (COLOR_SECONDARY)
            color_hover: #x382e55
            color_down: #x463666
        }
        draw_icon.color: (COLOR_TEXT)
        draw_text +: {
            color: (COLOR_TEXT)
            color_hover: (COLOR_TEXT)
            color_down: (COLOR_TEXT)
        }
    }
}
