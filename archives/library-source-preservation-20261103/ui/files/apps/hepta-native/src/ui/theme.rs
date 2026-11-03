//! Native cockpit tokens. Appearance conveys observed state, never authority.
use eframe::egui::{self, Color32, FontFamily, FontId, Stroke, TextStyle};

pub(super) const BACKGROUND: Color32 = Color32::from_rgb(10, 16, 25);
pub(super) const SURFACE: Color32 = Color32::from_rgb(17, 27, 40);
pub(super) const BORDER: Color32 = Color32::from_rgb(49, 70, 89);
pub(super) const TEXT: Color32 = Color32::from_rgb(226, 235, 244);
pub(super) const MUTED: Color32 = Color32::from_rgb(158, 180, 200);
pub(super) const CYAN: Color32 = Color32::from_rgb(111, 223, 229);
pub(super) const AMBER: Color32 = Color32::from_rgb(249, 198, 113);
pub(super) const ERROR: Color32 = Color32::from_rgb(255, 161, 164);

pub(super) fn install(ctx: &egui::Context) {
    let mut style = (*ctx.style_of(egui::Theme::Dark)).clone();
    style.visuals = egui::Visuals::dark();
    style.visuals.panel_fill = BACKGROUND;
    style.visuals.window_fill = SURFACE;
    style.visuals.extreme_bg_color = BACKGROUND;
    style.visuals.faint_bg_color = SURFACE;
    style.visuals.override_text_color = Some(TEXT);
    style.visuals.weak_text_color = Some(MUTED);
    style.visuals.selection.bg_fill = Color32::from_rgb(31, 80, 94);
    style.visuals.selection.stroke = Stroke::new(1.5, CYAN);
    style.visuals.hyperlink_color = CYAN;
    style.visuals.error_fg_color = ERROR;
    style.visuals.text_cursor.blink = false;
    style.visuals.warn_fg_color = AMBER;
    style.visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, BORDER);
    style.visuals.widgets.inactive.bg_fill = SURFACE;
    style.visuals.widgets.inactive.weak_bg_fill = SURFACE;
    style.visuals.widgets.inactive.bg_stroke = Stroke::new(1.0, BORDER);
    style.visuals.widgets.hovered.bg_fill = Color32::from_rgb(31, 53, 70);
    style.visuals.widgets.hovered.weak_bg_fill = Color32::from_rgb(31, 53, 70);
    style.visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, CYAN);
    style.visuals.widgets.active.bg_fill = Color32::from_rgb(32, 72, 87);
    style.visuals.widgets.active.bg_stroke = Stroke::new(2.0, CYAN);
    style.spacing.item_spacing = egui::vec2(12.0, 10.0);
    style.spacing.button_padding = egui::vec2(12.0, 8.0);
    style.spacing.interact_size.y = 34.0;
    style.spacing.text_edit_width = 360.0;
    style.spacing.scroll.floating = false;
    style.spacing.scroll.bar_width = 10.0;
    style.spacing.scroll.handle_min_length = 32.0;
    style.text_styles.insert(
        TextStyle::Heading,
        FontId::new(26.0, FontFamily::Proportional),
    );
    style
        .text_styles
        .insert(TextStyle::Body, FontId::new(15.0, FontFamily::Proportional));
    style.text_styles.insert(
        TextStyle::Button,
        FontId::new(14.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        TextStyle::Small,
        FontId::new(12.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        TextStyle::Monospace,
        FontId::new(13.0, FontFamily::Monospace),
    );
    // No decorative motion: state changes remain immediate and readable.
    style.animation_time = 0.0;
    ctx.set_theme(egui::Theme::Dark);
    ctx.set_style_of(egui::Theme::Dark, style);
}

pub(super) fn card() -> egui::Frame {
    egui::Frame::new()
        .fill(SURFACE)
        .stroke(Stroke::new(1.0, BORDER))
        .corner_radius(3)
        .inner_margin(18)
}

pub(super) fn eyebrow(ui: &mut egui::Ui, text: &str) {
    ui.label(egui::RichText::new(text).monospace().size(11.0).color(CYAN));
}
