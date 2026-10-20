//! Keep the actual native status layout beside its emitted draw instances.
//! A successful subset of glyphs is not a complete readiness observation.
use makepad_widgets::*;

#[path = "native_status_layout.rs"]
mod layout;

script_mod! {
    use mod.prelude.widgets.*
    use mod.widgets.*
    mod.widgets.NativeStatus = #(NativeStatus::register_widget(vm)) {
        width: Fill height: Fit
        draw_text +: {text_style: mod.widgets.HEPTA_REGULAR {font_size: 10} color: #d8e1f1}
    }
}

#[derive(Script, ScriptHook, Widget)]
pub struct NativeStatus {
    #[uid]
    uid: WidgetUid,
    #[source]
    source: ScriptObjectRef,
    #[redraw]
    #[live]
    pub draw_text: DrawText,
    #[walk]
    walk: Walk,
    #[rust]
    text: String,
    #[rust]
    area: Area,
    #[rust]
    pub expected_ink: Option<usize>,
}

impl Widget for NativeStatus {
    fn text(&self) -> String {
        self.text.clone()
    }

    fn set_text(&mut self, cx: &mut Cx, text: &str) {
        if self.text != text {
            self.text = text.to_owned();
            self.expected_ink = None;
            self.redraw(cx);
        }
    }

    fn draw_walk(&mut self, cx: &mut Cx2d, _scope: &mut Scope, walk: Walk) -> DrawStep {
        let walk = cx.resolve_walk(walk, ResolveAt::BeforeBegin);
        layout::begin(cx, walk);
        let width = cx
            .turtle()
            .max_width(walk)
            .or_else(|| {
                let rect = cx.turtle().inner_rect();
                (!rect.size.x.is_nan()).then_some(rect.size.x)
            })
            .map(|width| width.max(0.0) as f32 / self.draw_text.font_scale.max(0.0001));
        let layout = self
            .draw_text
            .layout(cx, 0.0, 0.0, width, true, Align::default(), &self.text);
        self.expected_ink = None;
        if !layout.is_truncated && layout.text.as_str() == self.text {
            let dpi = cx.current_dpi_factor() as f32;
            let mut expected = Some(0usize);
            for row in &layout.rows {
                for glyph in &row.glyphs {
                    let dpx = glyph.font_size_in_lpxs * dpi;
                    if glyph.id == 0
                        || !dpx.is_finite()
                        || dpx <= 0.0
                        || cx.fonts.borrow().should_use_slug_glyph(dpx)
                    {
                        expected = None;
                        break;
                    }
                    let image = glyph.font.has_glyph_raster_image(glyph.id, dpx);
                    let outline = glyph.font.glyph_outline_rc(glyph.id);
                    let ink = image
                        || outline.as_ref().is_some_and(|outline| {
                            let size = outline.size_in_ems();
                            size.width > 0.0 && size.height > 0.0
                        });
                    if ink {
                        expected = expected.and_then(|count| count.checked_add(1));
                    } else if !row
                        .text
                        .get(glyph.cluster..)
                        .and_then(|text| text.chars().next())
                        .is_some_and(char::is_whitespace)
                    {
                        expected = None;
                        break;
                    }
                }
                if expected.is_none() {
                    break;
                }
            }
            self.expected_ink = expected.filter(|count| *count > 0);
        }
        // The same layout used for the expected count is passed unchanged to
        // the actual SDK draw. Do not rerasterize after a failed allocation.
        self.draw_text.draw_walk_laidout(cx, walk, &layout);
        cx.end_turtle_with_area(&mut self.area);
        DrawStep::done()
    }
}
