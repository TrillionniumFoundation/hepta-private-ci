//! Complete the original SDK's registered resources from the verified package.
//! The fixed 337566c SDK retains one draw-level legacy relative font reference.
//! Resolve only that exact declaration; never guess a file by its basename.

use makepad_widgets::makepad_platform::script::res::CxScriptResourceData;
use makepad_widgets::*;

const LEGACY_TEXT_FONT: &str = "/../../widgets/resources/IBMPlexSans-Text.ttf";
const PACKAGED_TEXT_FONT: &str = "makepad_widgets/resources/IBMPlexSans-Text.ttf";

pub(crate) fn register_packaged_app(
    vm: &mut ScriptVm,
    register: fn(&mut ScriptVm) -> ScriptValue,
) -> ScriptValue {
    if !vm.with_cx(|cx| cx.package_root.is_some()) {
        return register(vm);
    }
    let draw_manifest = vm
        .bx
        .code
        .crate_manifests
        .borrow()
        .get("makepad_draw")
        .cloned();
    if let Some(draw_manifest) = draw_manifest {
        vm.with_cx_mut(|cx| map_legacy_text_font(cx, &draw_manifest));
    }
    let value = register(vm);
    vm.with_cx_mut(load_registered_resources);
    value
}

fn map_legacy_text_font(cx: &mut Cx, draw_manifest: &str) {
    let legacy = format!("{draw_manifest}{LEGACY_TEXT_FONT}");
    for resource in cx.script_data.resources.resources.borrow_mut().iter_mut() {
        if resource.abs_path == legacy && resource.dependency_path.is_none() {
            resource.dependency_path = Some(PACKAGED_TEXT_FONT.into());
            // Some original font constructors have already attempted the
            // malformed path. Retry only this exact repaired alias through
            // the SDK loader, retaining its handles and absolute identity.
            if matches!(resource.data, CxScriptResourceData::Error(_)) {
                resource.data = CxScriptResourceData::NotLoaded;
            }
        }
    }
}

fn load_registered_resources(cx: &mut Cx) {
    let paths = cx
        .script_data
        .resources
        .resources
        .borrow()
        .iter()
        .map(|resource| resource.abs_path.clone())
        .collect::<Vec<_>>();
    // load_all_script_resources intentionally defers FontPolicy members.
    // This packaged product validates every registered resource before its
    // first frame, so complete them through the same original loader too.
    for path in paths {
        cx.load_script_resource_by_path(&path);
    }
}

#[cfg(test)]
#[path = "native_resources_tests.rs"]
mod tests;
