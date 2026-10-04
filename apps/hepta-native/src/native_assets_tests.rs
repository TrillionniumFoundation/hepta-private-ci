use super::*;

mod foreign_font_reference {
    use hepta_robrix_ui::makepad_widgets::*;

    script_mod! {
        use mod.res.*
        // Same historical literal, but this is not the pinned SDK draw module.
        mod.foreign_font_reference = crate_resource("self:../../widgets/resources/IBMPlexSans-Text.ttf")
    }
}

#[test]
fn actual_shared_app_resources_are_complete_and_foreign_aliases_fail_closed() {
    let mut cx = new_cx_with_font_set(Box::new(|_, _| {}), FontSet::International);
    // Match app_main before Startup: resource loading reads the native clock.
    cx.init_cx_os();
    configure(&mut cx, None);
    cx.with_vm(|vm| {
        let value = <hepta_robrix_ui::app::App as AppMain>::script_mod(vm);
        assert!(!value.is_err());
        let _root = vm.bx.heap.new_object_ref(value.as_object().unwrap());
        let mut app = <hepta_robrix_ui::app::App as ScriptNew>::script_from_value(vm, value);
        <hepta_robrix_ui::app::App as AppMain>::after_new_from_script(vm, &mut app);
        vm.gc();
        let resources = vm.host.cx_mut().script_data.resources.resources.clone();
        // Check every actual entry, including binary resources and the default
        // DrawText reference. Filtering dependency_path would hide the old bug.
        for resource in resources.borrow().iter() {
            assert!(
                matches!(&resource.data, CxScriptResourceData::Loaded(data) if !data.is_empty()),
                "actual shared App contains an unloaded resource"
            );
        }

        let count = resources.borrow().len();
        foreign_font_reference::script_mod(vm);
        assert_eq!(resources.borrow().len(), count + 1);
        let foreign = resources.borrow().last().unwrap().abs_path.clone();
        assert!(resources.borrow().last().unwrap().dependency_path.is_none());
        assert!(
            vm.host
                .cx_mut()
                .get_resource_font_bytes_by_path(&foreign)
                .is_none()
        );
        vm.host.cx_mut().load_script_resource_by_path(&foreign);
        assert!(matches!(&resources.borrow().last().unwrap().data,
            CxScriptResourceData::Error(detail) if detail == "native resource is not embedded"));

        let unknown = makepad_platform::script::res::register_crate_resource_path(
            vm,
            "makepad_widgets/resources/not-in-fixed-inventory.ttf",
        );
        let heap_key = vm.bx.heap.heap_key();
        let handle = unknown.as_handle().unwrap();
        let path = vm
            .host
            .cx_mut()
            .get_resource_abs_path(heap_key, handle)
            .unwrap();
        vm.host.cx_mut().load_script_resource_by_path(&path);
        assert!(vm.host.cx_mut().get_resource(heap_key, handle).is_none());
        assert!(
            vm.host
                .cx_mut()
                .get_resource_font_bytes(heap_key, handle)
                .is_none()
        );
    });
}

// Exercise the production layout source without exporting renderer internals.
#[path = "../../hepta-control-ui/rust/robrix-ui/src/native_status_layout.rs"]
mod status_layout;

#[test]
fn status_layout_reserves_measured_raster_overhang() {
    let mut summary = String::new();
    for width in [48.0, 1280.0] {
        let mut cx = Cx::new(Box::new(|_, _| {}));
        let event = DrawEvent::default();
        let mut draw = CxDraw::new(&mut cx, &event);
        let mut cx = Cx2d::new(&mut draw);
        cx.begin_root_turtle(dvec2(width, 80.0), Layout::default());
        status_layout::begin(&mut cx, Walk::new(Size::fill(), Size::fit()));
        let text = cx.walk_turtle(Walk::fixed(width - 8.0, 14.0));
        let bounds = cx.end_turtle();
        cx.end_turtle();
        // First glyph measured in hosted Linux run 37171431236. This is a
        // layout regression using its overhang, not another raster/GPU claim.
        let glyph = Rect {
            pos: text.pos + dvec2(-1.413333415985107, 1.083332061767578),
            size: dvec2(11.25, 12.916666030883789),
        };
        let clipped = glyph.clip((bounds.pos, bounds.pos + bounds.size));
        assert_eq!(glyph, clipped, "status layout clipped the measured quad");
        summary.push_str(&format!(
            "width={width:.0} text=({:.2},{:.2}) status=({:.2},{:.2},{:.2},{:.2}) glyph=({:.2},{:.2},{:.2},{:.2}) unclipped=true\n",
            text.pos.x, text.pos.y,
            bounds.pos.x, bounds.pos.y, bounds.size.x, bounds.size.y,
            glyph.pos.x, glyph.pos.y, glyph.size.x, glyph.size.y,
        ));
    }
    insta::with_settings!({prepend_module_to_snapshot => false}, {
        insta::assert_snapshot!("robrix_status_raster_overhang_layout", summary);
    });
}
