//! Layout shared by the actual status widget and its CPU geometry regression.
use super::*;

pub(super) fn begin(cx: &mut Cx2d, walk: Walk) {
    cx.begin_turtle(
        walk,
        Layout {
            flow: Flow::right_wrap(),
            // Raster atlas quads extend beyond the text advance box. Keep
            // that overhang inside this turtle's clip, not merely inside
            // the surrounding panel. Readiness still checks every quad.
            padding: Inset {
                left: 4.0,
                right: 4.0,
                top: 4.0,
                bottom: 4.0,
            },
            ..Default::default()
        },
    );
}
