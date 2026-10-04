#![cfg(all(feature = "robrix-preview", target_os = "linux"))]

use hepta_robrix_ui::makepad_widgets::Cx;
use hepta_robrix_ui::makepad_widgets::makepad_platform::script::res::CxScriptResource;
use hepta_robrix_ui::makepad_widgets::makepad_platform::script::res::CxScriptResourceData;
use sha2::Digest;
use std::process::Command;
use std::rc::Rc;

#[test]
fn embedded_font_bytes_override_a_conflicting_real_file() {
    let root = tempfile::TempDir::new().unwrap();
    let path = root.path().join("font.ttf");
    std::fs::write(&path, b"conflicting filesystem bytes").unwrap();
    let cx = Cx::new(Box::new(|_, _| {}));
    let embedded = Rc::new(b"embedded font bytes".to_vec());
    cx.script_data
        .resources
        .resources
        .borrow_mut()
        .push(CxScriptResource {
            abs_path: path.to_str().unwrap().to_owned(),
            dependency_path: Some("test/resources/font.ttf".into()),
            web_url: None,
            data: CxScriptResourceData::Loaded(Rc::clone(&embedded)),
            handles: Vec::new(),
        });
    let loaded = cx
        .get_resource_font_bytes_by_path(path.to_str().unwrap())
        .unwrap();
    assert_eq!(loaded.as_slice(), embedded.as_slice());
    assert_eq!(
        std::fs::read(path).unwrap(),
        b"conflicting filesystem bytes"
    );
}

#[test]
fn absent_embedded_resource_never_recovers_from_a_real_file() {
    let root = tempfile::TempDir::new().unwrap();
    let path = root.path().join("missing.png");
    std::fs::write(&path, b"filesystem must not satisfy missing inventory").unwrap();
    let path = path.to_str().unwrap();
    let mut cx = Cx::new(Box::new(|_, _| {}));
    cx.script_data
        .resources
        .resources
        .borrow_mut()
        .push(CxScriptResource {
            abs_path: path.into(),
            dependency_path: Some("test/resources/missing.png".into()),
            web_url: None,
            data: CxScriptResourceData::NotLoaded,
            handles: Vec::new(),
        });
    assert!(cx.get_resource_font_bytes_by_path(path).is_none());
    cx.load_script_resource_by_path(path);
    let resources = cx.script_data.resources.resources.borrow();
    assert!(
        matches!(&resources[0].data, CxScriptResourceData::Error(detail)
        if detail == "native resource is not embedded")
    );
    assert!(
        cx.get_resource_font_bytes_by_path("unregistered font")
            .is_none()
    );
}

fn early_command(args: &[&str]) -> std::process::Output {
    let root = tempfile::TempDir::new().unwrap();
    // There is deliberately no launch config, gateway, keyring, state root,
    // display, network service or GUI. These commands must return before any
    // of those owners are initialized and must write only to their streams.
    let output = Command::new(env!("CARGO_BIN_EXE_hepta-native"))
        .args(args)
        .current_dir(root.path())
        .env("XDG_CONFIG_HOME", root.path())
        .env_remove("DISPLAY")
        .env_remove("WAYLAND_DISPLAY")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 0);
    output
}

#[test]
fn source_export_is_exact_and_has_no_runtime_side_effects() {
    let output = early_command(&["--font-source", "liberation"]);
    assert_eq!(output.stdout.len(), 2_255_959);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(&output.stdout)),
        "fe3ea5f7a2d3bdea8b8f0d82cdc6c07d14ace67c6e06d7aa33b83fd9e640adae"
    );
}

#[test]
fn original_notices_are_readable_before_runtime_initialization() {
    let output = early_command(&["--font-notices"]);
    let text = String::from_utf8(output.stdout).unwrap();
    for expected in [
        "--font-source liberation",
        "GNU GENERAL PUBLIC LICENSE",
        "SIL OPEN FONT LICENSE",
        "LaTeX Project Public License",
        "Liberation-1.04.93.devel-License.txt",
    ] {
        assert!(text.contains(expected), "missing notice: {expected}");
    }
}
