//! Native presentation tokens. Color never substitutes for an observed state.
use super::chat_model::design;
use super::egui;

const fn color(rgb: [u8; 3]) -> egui::Color32 {
    egui::Color32::from_rgb(rgb[0], rgb[1], rgb[2])
}

pub(super) const BACKGROUND: egui::Color32 = color(design::BACKGROUND);
pub(super) const SURFACE: egui::Color32 = color(design::SURFACE);
pub(super) const BORDER: egui::Color32 = color(design::BORDER);
pub(super) const TEXT: egui::Color32 = color(design::TEXT);
pub(super) const MUTED: egui::Color32 = color(design::MUTED);
pub(super) const CYAN: egui::Color32 = color(design::ACCENT);
pub(super) const VIOLET: egui::Color32 = egui::Color32::from_rgb(184, 166, 255);
pub(super) const WARNING: egui::Color32 = egui::Color32::from_rgb(255, 207, 128);
pub(super) const ERROR: egui::Color32 = egui::Color32::from_rgb(255, 164, 174);

#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub(super) enum Contrast {
    #[default]
    Standard,
    High,
}

pub(super) fn current_contrast(ctx: &egui::Context) -> Contrast {
    ctx.data(|data| data.get_temp(egui::Id::new("hepta-contrast")))
        .unwrap_or_default()
}

pub(super) fn ensure_initialized(ctx: &egui::Context) {
    if !ctx.data(|data| {
        data.get_temp::<bool>(egui::Id::new("hepta-theme"))
            .unwrap_or(false)
    }) {
        install(ctx, Contrast::Standard);
    }
}

pub(super) fn install(ctx: &egui::Context, contrast: Contrast) {
    let mut style = (*ctx.style_of(egui::Theme::Dark)).clone();
    style.visuals = egui::Visuals::dark();
    style.visuals.panel_fill = BACKGROUND;
    style.visuals.window_fill = SURFACE;
    style.visuals.extreme_bg_color = BACKGROUND;
    style.visuals.faint_bg_color = SURFACE;
    style.visuals.override_text_color = Some(TEXT);
    style.visuals.hyperlink_color = CYAN;
    style.visuals.selection.bg_fill = egui::Color32::from_rgb(31, 78, 97);
    style.visuals.slider_trailing_fill = true;
    style.visuals.selection.stroke = egui::Stroke::new(1.5, CYAN);
    style.visuals.widgets.noninteractive.bg_stroke = egui::Stroke::new(1.0, BORDER);
    style.visuals.widgets.noninteractive.fg_stroke = egui::Stroke::new(1.0, MUTED);
    style.visuals.widgets.inactive.bg_fill = SURFACE;
    style.visuals.widgets.inactive.weak_bg_fill = SURFACE;
    style.visuals.widgets.inactive.bg_stroke =
        egui::Stroke::new(1.0, egui::Color32::from_rgb(78, 103, 132));
    style.visuals.widgets.hovered.bg_fill = egui::Color32::from_rgb(29, 48, 65);
    style.visuals.widgets.hovered.weak_bg_fill = egui::Color32::from_rgb(29, 48, 65);
    style.visuals.widgets.hovered.bg_stroke = egui::Stroke::new(1.5, CYAN);
    style.visuals.widgets.active.bg_stroke = egui::Stroke::new(2.0, CYAN);
    if contrast == Contrast::High {
        style.visuals.widgets.inactive.bg_stroke = egui::Stroke::new(1.5, MUTED);
        style.visuals.widgets.noninteractive.bg_stroke = egui::Stroke::new(1.5, MUTED);
    }
    style.spacing.item_spacing = egui::vec2(10.0, 8.0);
    style.spacing.button_padding = egui::vec2(12.0, 7.0);
    style.spacing.interact_size.y = design::CONTROL_HEIGHT;
    style.spacing.text_edit_width = 320.0;
    for (kind, size) in [
        (egui::TextStyle::Heading, 25.0),
        (egui::TextStyle::Body, 15.0),
        (egui::TextStyle::Button, 14.0),
        (egui::TextStyle::Small, 13.0),
        (egui::TextStyle::Monospace, 13.0),
    ] {
        let family = if kind == egui::TextStyle::Monospace {
            egui::FontFamily::Monospace
        } else {
            egui::FontFamily::Proportional
        };
        style
            .text_styles
            .insert(kind, egui::FontId::new(size, family));
    }
    ctx.set_theme(egui::Theme::Dark);
    ctx.set_style_of(egui::Theme::Dark, style);
    ctx.data_mut(|data| {
        data.insert_temp(egui::Id::new("hepta-theme"), true);
        data.insert_temp(egui::Id::new("hepta-contrast"), contrast);
    });
}

pub(super) fn card() -> egui::Frame {
    egui::Frame::new()
        .fill(SURFACE)
        .stroke(egui::Stroke::new(1.0, BORDER))
        .corner_radius(10)
        .inner_margin(16)
}

pub(super) fn section(ui: &mut egui::Ui, title: &str, description: &str) {
    ui.heading(title);
    ui.label(egui::RichText::new(description).color(MUTED));
    ui.add_space(8.0);
}

/// A static seven-sided brand mark, unrelated to connection or health state.
pub(super) fn brand_mark(ui: &mut egui::Ui) {
    let (rect, _) = ui.allocate_exact_size(egui::vec2(28.0, 28.0), egui::Sense::hover());
    let points = (0..7)
        .map(|index| {
            let angle = std::f32::consts::TAU * index as f32 / 7.0 - std::f32::consts::FRAC_PI_2;
            rect.center() + egui::vec2(angle.cos(), angle.sin()) * 12.0
        })
        .collect();
    ui.painter().add(egui::Shape::closed_line(
        points,
        egui::Stroke::new(1.5, CYAN),
    ));
    ui.painter()
        .circle_stroke(rect.center(), 5.0, egui::Stroke::new(1.0, VIOLET));
}
