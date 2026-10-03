use makepad_widgets::*;

script_mod! {
    use mod.prelude.widgets.*
    use mod.widgets.*

    mod.widgets.RobrixSplitter = Splitter {
        // size: theme.splitter_size
        // min_horizontal: theme.splitter_min_horizontal
        // max_horizontal: theme.splitter_max_horizontal
        // min_vertical: theme.splitter_min_vertical
        // max_vertical: theme.splitter_max_vertical

        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            color: COLOR_PRIMARY_DARKER
            color_hover: COLOR_ROBRIX_PURPLE
            color_drag: COLOR_ROBRIX_PURPLE
            color_grab: uniform(COLOR_TEXT)

            pixel: fn() {
                let sdf = Sdf2d.viewport(self.pos * self.rect_size)

                // Body: dark gray by default (matches the default dark theme's
                // `color_bg_app`), transitions to purple on hover/drag.
                // Mildly rounded corners soften the edges where panels meet.
                let body_color = mix(
                    self.color
                    mix(self.color_hover, self.color_drag, self.drag)
                    self.hover
                )
                sdf.box(
                    0.0,
                    0.0,
                    self.rect_size.x,
                    self.rect_size.y,
                    1.5
                )
                sdf.fill(body_color)

                // Draw the grab bar shape
                if self.is_vertical > 0.5 {
                    sdf.box(
                        self.splitter_pad
                        self.rect_size.y * 0.5 - self.bar_size * 0.5
                        self.rect_size.x - 2.0 * self.splitter_pad
                        self.bar_size
                        self.border_radius
                    )
                }
                else {
                    sdf.box(
                        self.rect_size.x * 0.5 - self.bar_size * 0.5
                        self.splitter_pad
                        self.bar_size
                        self.rect_size.y - 2.0 * self.splitter_pad
                        self.border_radius
                    )
                }

                // Grab bar: white when hovered/dragged, otherwise matches body
                let grab_color = mix(self.color, self.color_grab, self.hover)
                return sdf.fill_keep(grab_color)
            }
        }

        animator: Animator{
            hover: {
                default: @off
                off: AnimatorState{
                    from: {all: Forward {duration: 0.1}}
                    apply: {
                        draw_bg: {drag: 0.0, hover: 0.0}
                    }
                }

                on: AnimatorState{
                    from: {
                        all: Forward {duration: 0.1}
                        drag: Forward {duration: 0.01}
                    }
                    apply: {
                        draw_bg: {
                            drag: 0.0,
                            hover: snap(1.0)
                        }
                    }
                }

                drag: AnimatorState{
                    from: { all: Forward { duration: 0.1 }}
                    apply: {
                        draw_bg: {
                            drag: snap(1.0),
                            hover: 1.0
                        }
                    }
                }
            }
        }
    }

    mod.widgets.RobrixTabCloseButton = TabCloseButton {
        height: 10.0
        width: 10.0
        margin: Inset{ right: theme.space_2, left: -1 }
        draw_button +: {
            hepta_owned_material: uniform(1.0)
            hepta_material: uniform(1.0)
            color: COLOR_TEXT
            color_hover: COLOR_FG_DANGER_RED
            color_active: COLOR_BUTTON_INK
            pixel: fn() {
                let sdf = Sdf2d.viewport(self.pos * self.rect_size)
                let c = self.rect_size * 0.5
                let r = 2.5 + self.hover * 0.5
                sdf.move_to(c.x-r, c.y-r)
                sdf.line_to(c.x+r, c.y+r)
                sdf.move_to(c.x-r, c.y+r)
                sdf.line_to(c.x+r, c.y-r)
                let prism = max(0.0, 1.0-abs(self.hepta_material-1.0))
                return sdf.stroke(mix(mix(self.color, self.color_active, self.active*prism), self.color_hover, self.hover), 1.0)
            }
        }

        animator: Animator{
            hover: {
                default: @off
                off: AnimatorState{
                    from: {all: Forward {duration: 0.1}}
                    apply: {
                        draw_button: {hover: 0.0}
                    }
                }

                on: AnimatorState{
                    cursor: MouseCursor.Hand
                    from: {all: Snap}
                    apply: {
                        draw_button: {hover: 1.0}
                    }
                }
            }
        }
    }

    mod.widgets.RobrixTab = Tab {
        width: Fit
        height: Fill

        align: Align{x: 0.0, y: 0.5}
        padding: Inset{left: 18, right: 18, top: 10, bottom: 10}
        margin: 0

        close_button: mod.widgets.RobrixTabCloseButton {}
        draw_text +: {
            hepta_owned_material: uniform(1.0)
            hepta_material: uniform(1.0)
            text_style: theme.font_regular {}
            color: COLOR_TEXT
            color_hover: COLOR_ACTIVE_PRIMARY
            color_active: COLOR_BUTTON_INK
            get_color: fn() {
                let prism = max(0.0, 1.0-abs(self.hepta_material-1.0))
                let ceramic = max(0.0, self.hepta_material-1.0)
                let selected = mix(mix(self.color, self.color_hover, ceramic), self.color_active, prism)
                return mix(mix(self.color, self.color_hover, self.hover*0.6), selected, self.active)
            }
        }

        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            // Light blue-ish color, de-saturated from COLOR_ACTIVE_PRIMARY
            color: COLOR_PRIMARY
            color_2: COLOR_PRIMARY
            // A slightly darker shade of the tab color for hover visibility
            color_hover: COLOR_SECONDARY
            color_2_hover: COLOR_SECONDARY
            // Active (selected) tabs are a deeper blue, with a vertical gradient
            // to a slightly lighter blue.
            color_active: COLOR_ACTIVE_PRIMARY
            color_2_active: COLOR_ACTIVE_PRIMARY_DARKER
            // Remove the border and rounded corners from the default Tab style
            border_size: 1.0
            border_radius: 8.0
            hepta_material: uniform(1.0)
            color_edge: uniform(#x4c4269)
            color_selected_surface: uniform(#x382e55)
            pixel: fn() {
                let p = self.pos * self.rect_size
                let sdf = Sdf2d.viewport(p)
                let prism = max(0.0, 1.0-abs(self.hepta_material-1.0))
                let ceramic = max(0.0, self.hepta_material-1.0)
                let selected = mix(self.color_selected_surface, mix(self.color_active, self.color_2_active, self.pos.y), prism)
                sdf.box_y(1.0, 1.0, self.rect_size.x-2.0, self.rect_size.y, (5.0+prism*3.0)*0.5, 0.5)
                sdf.fill_keep(mix(mix(self.color, self.color_hover, self.hover), selected, self.active))
                sdf.stroke(mix(self.color_edge, self.color_active, self.active*(1.0-prism)*0.45), 0.7)
                if self.hepta_material < 0.5 {
                    sdf.box(2.0, self.rect_size.y-3.0, max(0.0, self.rect_size.x-4.0)*self.active, 2.5, 1.0)
                    sdf.fill(self.color_active)
                }
                if ceramic > 0.5 {
                    sdf.box(5.0, 1.0, max(0.0, self.rect_size.x-10.0)*self.active, 1.0, 0.5)
                    sdf.fill(self.color_active)
                }
                return sdf.result
            }
        }

        animator: Animator{
            hover: {
                default: @off
                off: AnimatorState{
                    from: {all: Forward {duration: 0.2}}
                    apply: {
                        draw_bg: {hover: 0.0}
                        draw_text: {hover: 0.0}
                    }
                }

                on: AnimatorState{
                    cursor: MouseCursor.Hand
                    from: {all: Forward {duration: 0.1}}
                    apply: {
                        draw_bg: {hover: snap(1.0)}
                        draw_text: {hover: snap(1.0)}
                    }
                }
            }

            active: {
                default: @off
                off: AnimatorState{
                    from: {all: Forward {duration: 0.3}}
                    apply: {
                        close_button: {draw_button: {active: 0.0}}
                        draw_bg: {active: 0.0}
                        draw_text: {active: 0.0}
                    }
                }

                on: AnimatorState{
                    from: {all: Snap}
                    apply: {
                        close_button: {draw_button: {active: 1.0}}
                        draw_bg: {active: 1.0}
                        draw_text: {active: 1.0}
                    }
                }
            }
        }
    }

    mod.widgets.RobrixTabBar = TabBar {
        CloseableTab := mod.widgets.RobrixTab {closeable: true}
        PermanentTab := mod.widgets.RobrixTab {closeable: false}

        draw_drag +: {
            draw_depth: 10
            color: (mod.widgets.COLOR_TEXT)
        }
        draw_fill +: {
            hepta_owned_material: uniform(1.0)
            color: COLOR_PRIMARY_DARKER
            pixel: fn() { return self.color * self.hepta_owned_material }
        }
        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            color: COLOR_PRIMARY_DARKER
        }

        width: Fill
        height: 42.0

        scroll_bars: ScrollBarsTabs {
            show_scroll_x: true
            show_scroll_y: false
            scroll_bar_x +: {
                bar_size: 4
                use_vertical_finger_scroll: true
            }
        }
    }

    mod.widgets.RobrixDock = Dock {
        flow: Down

        round_corner +: {
            color: COLOR_SECONDARY
        }

        padding: Inset{left: theme.dock_border_size, top: 0, right: theme.dock_border_size, bottom: theme.dock_border_size}
        drag_target_preview +: {
            draw_depth: 10.0
            color: mix(COLOR_ACTIVE_PRIMARY, #FFFFFF00, 0.5)
        }
        tab_bar: mod.widgets.RobrixTabBar {}
        splitter: mod.widgets.RobrixSplitter {}
    }
}
