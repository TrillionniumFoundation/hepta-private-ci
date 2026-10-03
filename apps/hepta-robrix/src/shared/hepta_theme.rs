//! Three materials for the same Robrix widget tree. Only paint data changes.
//! Like Makepad's live theme editor, semantic colors are retargeted in draw slots
//! after drawing. No ScriptReapply, widget replacement, texture recoloring, or
//! account/room/composer mutation is involved.
use makepad_widgets::*;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub enum HeptaTheme {
    DeepSpaceTitanium,
    #[default]
    PolarPrism,
    ObsidianCeramic,
}

impl HeptaTheme {
    fn index(self) -> usize {
        match self { Self::DeepSpaceTitanium => 0, Self::PolarPrism => 1, Self::ObsidianCeramic => 2 }
    }
}

// Columns: Titanium, Prism, Ceramic. Rows are semantic paint roles, not arbitrary
// pixel colors. Every cross-palette repeated value must retain its role.
const PALETTES: [[u32; 3]; 14] = [
    [0x07111cff, 0x0d0b19ff, 0x101213ff], // canvas
    [0x0c1927ff, 0x171329ff, 0x181b1cff], // panel
    [0x142638ff, 0x231e39ff, 0x242728ff], // raised
    [0x294761ff, 0x4c4269ff, 0x41413eff], // edge
    [0x79d9ffff, 0xbba6ffff, 0xe8ba88ff], // accent
    [0x9ee6ffff, 0xcebfffff, 0xf2d3aaff], // accent hover
    [0xedf5ffff, 0xf0edffff, 0xf2efebff], // text
    [0xafc1d5ff, 0xb9b0cbff, 0xbcbdbbff], // secondary text
    [0x859cb5ff, 0x9589afff, 0x929594ff], // muted
    [0x163349ff, 0x382e55ff, 0x352e26ff], // selected surface
    [0x1d4057ff, 0x463666ff, 0x45392aff], // selected hover
    [0x102132ff, 0x201a33ff, 0x202323ff], // hover
    [0x182b3dff, 0x2c2442ff, 0x2c3030ff], // disabled surface
    [0x06101aff, 0x100d1dff, 0x111315ff], // ink on accent (separate from surface)
];

pub const fn rgba(hex: u32) -> Vec4 {
    vec4(((hex >> 24) & 255) as f32 / 255.0, ((hex >> 16) & 255) as f32 / 255.0,
        ((hex >> 8) & 255) as f32 / 255.0, (hex & 255) as f32 / 255.0)
}

fn retarget(value: &mut [f32], choice: HeptaTheme) -> bool {
    if value.len() != 4 || value.iter().any(|v| !v.is_finite()) { return false; }
    let packed = value.iter().fold(0_u32, |p, v| (p << 8) | (v.clamp(0.0, 1.0) * 255.0).round() as u32);
    let Some(row) = PALETTES.iter().find(|row| row.contains(&packed)) else { return false; };
    let c = rgba(row[choice.index()]);
    let next = [c.x, c.y, c.z, c.w];
    if value == next { return false; }
    value.copy_from_slice(&next);
    true
}

/// Selection affects only application paint; owners are deliberately not reachable here.
pub fn select(cx: &mut Cx, choice: HeptaTheme) {
    *cx.global::<HeptaTheme>() = choice;
    cx.redraw_all();
}

fn material(value: &mut [f32], id: LiveId, choice: HeptaTheme) -> bool {
    if value.len() != 1 { return false; }
    let index = choice.index();
    let next = if id == id!(hepta_radius) { [6.0, 12.0, 9.0][index] }
        else if id == id!(hepta_material) { index as f32 }
        else if id == id!(hepta_edge) { [0.8, 1.0, 0.6][index] }
        else { return false; };
    if value[0] == next { return false; }
    value[0] = next;
    true
}

#[derive(Clone, Default)]
struct MaterialSlots {
    stride: usize,
    colors: Vec<usize>,
    uniforms: Vec<(LiveId, usize, usize)>,
}

#[derive(Default)]
struct PaintCache(std::collections::HashMap<usize, Option<MaterialSlots>>);

fn owned_material(cx: &Cx, shader: usize) -> Option<MaterialSlots> {
    let mapping = &cx.draw_shaders.shaders[shader].mapping;
    // A deliberate app-owned tag is mandatory. A matching RGBA value alone is
    // never authority to recolor an image, avatar, rich text, or another widget.
    if !mapping.dyn_uniforms.inputs.iter().any(|i| i.id == id!(hepta_owned_material)) {
        return None;
    }
    Some(MaterialSlots {
        stride: mapping.instances.total_slots,
        colors: mapping.instances.inputs.iter()
            .filter(|i| i.slots == 4 && i.id.to_string().contains("color"))
            .map(|i| i.offset).collect(),
        uniforms: mapping.dyn_uniforms.inputs.iter()
            .filter(|i| (i.slots == 4 && i.id.to_string().contains("color"))
                || matches!(i.id, x if x == id!(hepta_radius) || x == id!(hepta_edge) || x == id!(hepta_material)))
            .map(|i| (i.id, i.offset, i.slots)).collect(),
    })
}

/// Resolve only tagged application material shaders. Cached slot layouts avoid
/// searching shader metadata for every glyph or frame. Textures, arbitrary vec4
/// inputs, shader scope constants and untagged draw calls are never inspected.
/// States interpolate the resolved inputs on GPU, preserving hover/focus blends.
pub fn paint(cx: &mut Cx) {
    let choice = *cx.global::<HeptaTheme>();
    let mut cache = std::mem::take(&mut cx.global::<PaintCache>().0);
    let lists: Vec<_> = cx.draw_lists.id_iter().collect();
    for list_id in lists {
        let count = cx.draw_lists[list_id].draw_items.len();
        for index in 0..count {
            let Some(shader) = cx.draw_lists[list_id].draw_items[index].draw_call().map(|call| call.draw_shader_id.index) else { continue; };
            let slots = cache.entry(shader).or_insert_with(|| owned_material(cx, shader));
            let Some(slots) = slots else { continue; };
            let item = &mut cx.draw_lists[list_id].draw_items[index];
            let Some(call) = item.kind.draw_call_mut() else { continue; };
            if slots.stride > 0 && let Some(buffer) = item.instances.as_mut() {
                for instance in buffer.chunks_exact_mut(slots.stride) {
                    for offset in &slots.colors {
                        call.instance_dirty |= retarget(&mut instance[*offset..*offset + 4], choice);
                    }
                }
            }
            for (id, offset, size) in &slots.uniforms {
                let Some(value) = call.dyn_uniforms.get_mut(*offset..*offset + *size) else { continue; };
                call.uniforms_dirty |= if *size == 4 { retarget(value, choice) } else { material(value, *id, choice) };
            }
        }
    }
    cx.global::<PaintCache>().0 = cache;
    // Only the app window's pass clear, never an off-screen image/font pass.
    let windows: Vec<_> = cx.windows.id_iter().collect();
    for window in windows {
        if let Some(pass) = cx.windows[window].main_pass_id {
            let color = rgba(PALETTES[0][choice.index()]);
            if cx.passes[pass].clear_color != color {
                cx.passes[pass].clear_color = color;
                cx.passes[pass].paint_dirty = true;
            }
        }
    }
}

script_mod! {
    use mod.prelude.widgets.*
    use mod.widgets.*

    // Opaque material: gradients suggest glass/metal, while every text surface
    // stays opaque and readable on both native and browser backends.
    mod.widgets.HeptaPanel = RoundedView {
        show_bg: true
        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            color: #x171329
            color_2: #x231e39
            border_color: #x4c4269
            hepta_radius: uniform(12.0)
            hepta_edge: uniform(1.0)
            hepta_material: uniform(1.0)
            pixel: fn() {
                let sdf = Sdf2d.viewport(self.pos * self.rect_size)
                sdf.box(0.5, 0.5, self.rect_size.x - 1.0, self.rect_size.y - 1.0, self.hepta_radius)
                let prism = max(0.0, 1.0 - abs(self.hepta_material - 1.0))
                let ceramic = max(0.0, self.hepta_material - 1.0)
                let sheen = pow(max(0.0, 1.0 - self.pos.y), 3.0) * (0.25 + prism * 0.34 - ceramic * 0.14)
                sdf.fill_keep(mix(self.color, self.color_2, sheen))
                sdf.stroke(self.border_color, self.hepta_edge)
                return sdf.result
            }
        }
    }

    mod.widgets.HeptaThemeButton = Button {
        padding: Inset{left: 10, right: 10, top: 6, bottom: 6}
        draw_bg +: {
            hepta_owned_material: uniform(1.0)
            color: #x231e39, color_hover: #x382e55, color_down: #x463666
            color_focus: #x382e55, border_color: #x4c4269, border_color_focus: #xbba6ff
            border_radius: 6.0, border_size: 1.0
        }
        draw_text +: {color: #xf0edff, color_hover: #xf0edff, color_down: #xf0edff, text_style: theme.font_regular {font_size: 9}}
    }

    mod.widgets.HeptaThemeBar = mod.widgets.HeptaPanel {
        width: Fill, height: 44
        padding: Inset{left: 20, right: 10, top: 5, bottom: 5}
        flow: Right
        spacing: 6
        align: Align{y: 0.5}
        draw_bg +: {
            color_accent: uniform(#xbba6ff)
            pixel: fn() {
                let p = self.pos * self.rect_size
                let sdf = Sdf2d.viewport(p)
                sdf.rect(0.0, 0.0, self.rect_size.x, self.rect_size.y)
                sdf.fill(mix(self.color, self.color_2, self.pos.x * 0.38))
                if self.hepta_material < 0.5 {
                    // Titanium: a restrained orbital horizon, not a screenshot.
                    sdf.circle(self.rect_size.x * 0.55, self.rect_size.y * 4.6, self.rect_size.y * 4.5)
                    sdf.stroke(self.color_accent * 0.32, 1.0)
                    sdf.circle(self.rect_size.x * 0.64, 9.0, 5.0)
                    sdf.stroke(self.color_accent * 0.45, 0.8)
                } else if self.hepta_material < 1.5 {
                    // Prism: quiet facets across the top rail.
                    sdf.move_to(self.rect_size.x * 0.31, 0.0)
                    sdf.line_to(self.rect_size.x * 0.37, self.rect_size.y)
                    sdf.line_to(self.rect_size.x * 0.46, 0.0)
                    sdf.stroke(self.color_accent * 0.18, 0.8)
                } else {
                    // Ceramic: a slim champagne seam in matte charcoal.
                    sdf.rect(0.0, self.rect_size.y - 1.0, self.rect_size.x, 1.0)
                    sdf.fill(self.color_accent * 0.18)
                }
                return sdf.result
            }
        }
        Label { text: "H E P T A" draw_text +: {color: #xf0edff, text_style: theme.font_regular {font_size: 13}} }
        View {width: Fill, height: Fit}
        theme_a := mod.widgets.HeptaThemeButton { text: "Titanium" }
        theme_b := mod.widgets.HeptaThemeButton { text: "Prism" }
        theme_c := mod.widgets.HeptaThemeButton { text: "Ceramic" }
    }
}

#[cfg(test)]
#[path = "hepta_theme_tests.rs"]
mod tests;
