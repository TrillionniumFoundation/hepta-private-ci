//! Fixed embedded resources for the Linux development candidate. Production
//! relocation qualification also requires the owned memory-priority SDK patch.

use hepta_robrix_ui::makepad_widgets::makepad_platform::script::res::CxScriptResourceData;
use hepta_robrix_ui::makepad_widgets::*;
use std::io::Write;

include!(concat!(env!("OUT_DIR"), "/native-assets.rs"));

struct AssetRoots {
    _root: ScriptObjectRef,
}

pub(crate) fn configure(cx: &mut Cx, font_override: Option<Vec<u8>>) {
    let root = cx.with_vm(|vm| {
        vm.bx.code.crate_manifests.borrow_mut().extend(
            CRATE_MANIFESTS
                .iter()
                .map(|(name, path)| ((*name).into(), (*path).into())),
        );
        let heap_key = vm.bx.heap.heap_key();
        let root = vm.bx.heap.new_with_proto(NIL);
        let root_ref = vm.bx.heap.new_object_ref(root);
        for (logical, embedded) in ASSETS {
            let bytes = if logical.ends_with("LXGWWenKaiRegular.ttf")
                || logical.ends_with("LXGWWenKaiBold.ttf")
                || logical.ends_with("NotoSansSC-Regular.otf")
                || logical.ends_with("NotoSansSC-Bold.otf")
            {
                font_override.as_deref().unwrap_or(embedded)
            } else {
                embedded
            };
            let module = vm.module(id!(res));
            let function = vm
                .bx
                .heap
                .value(module, id!(binary_resource).into(), NoTrap);
            let array: ScriptValue = vm.bx.heap.new_array_from_vec_u8(bytes.to_vec()).into();
            let memory = vm.call(function, &[array]);
            let memory_handle = memory.as_handle().expect("official binary resource handle");
            vm.bx.heap.vec_push(root, NIL, memory, NoTrap);
            let data = vm
                .host
                .cx_mut()
                .get_resource(heap_key, memory_handle)
                .expect("embedded bytes");
            let reference =
                makepad_platform::script::res::register_crate_resource_path(vm, logical);
            let handle = reference
                .as_handle()
                .expect("fixed logical resource handle");
            vm.bx.heap.vec_push(root, NIL, reference, NoTrap);
            let resources = vm.host.cx_mut().script_data.resources.resources.clone();
            let mut resources = resources.borrow_mut();
            let resource = resources
                .iter_mut()
                .find(|r| r.has_handle(heap_key, handle))
                .expect("registered resource");
            assert_eq!(resource.dependency_path.as_deref(), Some(*logical));
            assert!(matches!(resource.data, CxScriptResourceData::NotLoaded));
            resource.data = CxScriptResourceData::Loaded(data);
        }
        root_ref
    });
    // Retain both memory and logical handles across later VM collections.
    cx.set_global(AssetRoots { _root: root });
}

pub fn write_notices(output: &mut impl Write) -> std::io::Result<()> {
    output.write_all(b"Hepta native Linux development candidate: embedded asset notices\n\n")?;
    output.write_all(b"Unmodified Liberation 1.04.93.devel corresponding source is included in this executable. Export its original tar.gz with:\n  hepta-native --font-source liberation\nSHA-256: fe3ea5f7a2d3bdea8b8f0d82cdc6c07d14ace67c6e06d7aa33b83fd9e640adae\n\n")?;
    for (name, notice) in NOTICES {
        writeln!(output, "--- {name} ---")?;
        output.write_all(notice)?;
        output.write_all(b"\n")?;
    }
    Ok(())
}

pub fn write_liberation_source(output: &mut impl Write) -> std::io::Result<()> {
    output.write_all(LIBERATION_SOURCE)
}

#[cfg(test)]
#[path = "native_assets_tests.rs"]
mod tests;
