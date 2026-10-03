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
