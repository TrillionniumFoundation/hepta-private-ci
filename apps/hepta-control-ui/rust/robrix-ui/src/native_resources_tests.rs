use super::*;
use makepad_widgets::makepad_platform::script::res::CxScriptResource;

fn resource(path: &str, dependency_path: Option<&str>) -> CxScriptResource {
    CxScriptResource {
        abs_path: path.into(),
        dependency_path: dependency_path.map(str::to_owned),
        web_url: None,
        data: CxScriptResourceData::NotLoaded,
        handles: Vec::new(),
    }
}

#[test]
fn only_the_original_registered_draw_alias_is_repaired() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let original = format!("/exact/sdk/draw{LEGACY_TEXT_FONT}");
    let unrelated = format!("/other/sdk/draw{LEGACY_TEXT_FONT}");
    cx.script_data.resources.resources.borrow_mut().extend([
        resource(&original, None),
        resource(&unrelated, None),
        resource("/exact/sdk/draw/../../widgets/resources/other.ttf", None),
        resource(
            "/exact/sdk/widgets/resources/IBMPlexSans-Text.ttf",
            Some(PACKAGED_TEXT_FONT),
        ),
    ]);
    map_legacy_text_font(&mut cx, "/exact/sdk/draw");
    let paths = cx
        .script_data
        .resources
        .resources
        .borrow()
        .iter()
        .map(|resource| resource.dependency_path.clone())
        .collect::<Vec<_>>();
    assert_eq!(
        paths,
        vec![
            Some(PACKAGED_TEXT_FONT.into()),
            None,
            None,
            Some(PACKAGED_TEXT_FONT.into())
        ]
    );
}

#[test]
fn the_sdk_loader_reads_policy_fonts_and_retains_real_missing_errors() {
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "hepta-resource-test-{}-{unique}",
        std::process::id()
    ));
    std::fs::create_dir(&root).unwrap();
    struct Remove(std::path::PathBuf);
    impl Drop for Remove {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    let _cleanup = Remove(root.clone());
    let font = root.join(PACKAGED_TEXT_FONT);
    std::fs::create_dir_all(font.parent().unwrap()).unwrap();
    std::fs::write(font, b"resource loader test bytes").unwrap();
    let mut cx = Cx::new(Box::new(|_, _| {}));
    cx.set_font_set(FontSet::International);
    // Exercise the actual SDK package loader. No renderer/window or font
    // shaping success is inferred from these deliberately non-font bytes.
    cx.package_root = Some(root.to_str().unwrap().into());
    cx.script_data.resources.resources.borrow_mut().extend([
        resource(
            "/exact/sdk/widgets/resources/IBMPlexSans-Text.ttf",
            Some(PACKAGED_TEXT_FONT),
        ),
        resource(
            "/missing.svg",
            Some("makepad_widgets/resources/missing.svg"),
        ),
    ]);
    cx.load_all_script_resources();
    assert!(matches!(
        cx.script_data.resources.resources.borrow()[0].data,
        CxScriptResourceData::NotLoaded
    ));
    load_registered_resources(&mut cx);
    let resources = cx.script_data.resources.resources.borrow();
    assert!(
        matches!(&resources[0].data, CxScriptResourceData::Loaded(bytes)
        if bytes.as_slice() == b"resource loader test bytes")
    );
    assert!(matches!(resources[1].data, CxScriptResourceData::Error(_)));
}
