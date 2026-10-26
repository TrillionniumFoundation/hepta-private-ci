use super::*;

#[test]
fn current_sdk_window_drives_initial_and_changed_accessible_bounds_without_events() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let window = WindowHandle::new(&mut cx);
    let window_id = window.window_id();
    let layout = Rect {
        pos: dvec2(20.0, 30.0),
        size: dvec2(100.0, 50.0),
    };

    // Use the original SDK window pool and conversion methods. No synthetic
    // geometry event initializes an accessibility cache, even on the first
    // observation at 144 DPI. Position is in physical X11 screen pixels.
    cx.windows[window_id].is_created = true;
    cx.windows[window_id].os_dpi_factor = Some(1.5);
    cx.windows[window_id].window_geom = WindowGeom {
        dpi_factor: 1.5,
        position: dvec2(150.0, 60.0),
        inner_size: dvec2(1280.0, 800.0),
        ..Default::default()
    };
    let physical_window = AccessibleRect {
        x0: 150.0,
        y0: 60.0,
        x1: 2070.0,
        y1: 1260.0,
    };
    assert_eq!(
        (
            window_bounds(&cx, window_id),
            layout_bounds(&cx, window_id, layout)
        ),
        (
            physical_window,
            AccessibleRect {
                x0: 30.0,
                y0: 45.0,
                x1: 180.0,
                y1: 120.0,
            }
        )
    );

    // A later platform geometry update changes layout units for the same
    // physical window. Again, no event is delivered to this projection.
    cx.windows[window_id].os_dpi_factor = Some(2.0);
    cx.windows[window_id].window_geom.dpi_factor = 2.0;
    cx.windows[window_id].window_geom.inner_size = dvec2(960.0, 600.0);
    assert_eq!(
        (
            window_bounds(&cx, window_id),
            layout_bounds(&cx, window_id, layout)
        ),
        (
            physical_window,
            AccessibleRect {
                x0: 40.0,
                y0: 60.0,
                x1: 240.0,
                y1: 160.0,
            }
        )
    );

    // SDK layout overrides are part of its effective DPI; a cached native
    // scale or window_geom.dpi_factor alone must not replace that contract.
    cx.windows[window_id].dpi_override = Some(1.0);
    cx.windows[window_id].window_geom.inner_size = dvec2(1920.0, 1200.0);
    assert_eq!(
        (
            window_bounds(&cx, window_id),
            layout_bounds(&cx, window_id, layout)
        ),
        (
            physical_window,
            AccessibleRect {
                x0: 20.0,
                y0: 30.0,
                x1: 120.0,
                y1: 80.0,
            }
        )
    );
}
