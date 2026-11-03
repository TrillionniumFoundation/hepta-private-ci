//! Real widget and AccessKit-tree checks; no screen-reader or OS-effect claim.
use super::*;
use crate::ui::input_event_tests::app_fixture;
use eframe::App as _;
use egui::accesskit::{Node, TreeUpdate};

fn render(
    app: &mut HeptaNativeApp,
    context: &egui::Context,
    events: Vec<egui::Event>,
) -> TreeUpdate {
    let mut frame = eframe::Frame::_new_kittest();
    let mut output = context.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(1600.0, 1600.0),
            )),
            events,
            ..Default::default()
        },
        |ui| app.ui(ui, &mut frame),
    );
    let tree = output.platform_output.accesskit_update.take().unwrap();
    output.drop_without_applying_deltas();
    tree
}

fn label_node<'a>(tree: &'a TreeUpdate, label: &str) -> &'a Node {
    tree.nodes
        .iter()
        .map(|(_, node)| node)
        .find(|node| node.label().or_else(|| node.value()) == Some(label))
        .unwrap_or_else(|| panic!("missing accessible label: {label}"))
}

fn click(app: &mut HeptaNativeApp, context: &egui::Context, label: &str) {
    let tree = render(app, context, Vec::new());
    let bounds = label_node(&tree, label).bounds().unwrap();
    let position = egui::pos2(
        ((bounds.x0 + bounds.x1) / 2.0) as f32,
        ((bounds.y0 + bounds.y1) / 2.0) as f32,
    );
    for pressed in [true, false] {
        render(
            app,
            context,
            vec![
                egui::Event::PointerMoved(position),
                egui::Event::PointerButton {
                    pos: position,
                    button: egui::PointerButton::Primary,
                    pressed,
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
    }
}

fn labelled_fields(tree: &TreeUpdate, ids: &[&str]) -> Vec<String> {
    ids.iter()
        .map(|id| {
            let id = egui::Id::new(id).accesskit_id();
            let node = &tree.nodes.iter().find(|(key, _)| *key == id).unwrap().1;
            let [label] = node.labelled_by() else {
                panic!("input must have exactly one explicit label");
            };
            tree.nodes
                .iter()
                .find(|(key, _)| key == label)
                .unwrap()
                .1
                .value()
                .unwrap()
                .to_owned()
        })
        .collect()
}

#[test]
fn native_forms_associate_visible_labels_with_actual_text_inputs() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    let context = egui::Context::default();
    context.enable_accesskit();
    let tree = render(&mut app, &context, Vec::new());
    assert_eq!(
        labelled_fields(
            &tree,
            &[
                "native-operation-subject",
                "native-operation-id",
                "native-notification-title",
                "native-notification-body",
                "native-operation-grant",
            ],
        ),
        [
            "Authority subject",
            "Operation ID",
            "Notification title",
            "Notification body",
            "Signed grant path"
        ]
    );
    app.screen = Screen::Updates;
    let tree = render(&mut app, &context, Vec::new());
    assert_eq!(
        labelled_fields(&tree, &["native-update-manifest", "native-update-package"]),
        ["Signed manifest path", "Package path"]
    );
    assert!(app.all_tasks_idle());
}

#[test]
fn native_accessibility_controls_change_language_and_zoom_with_pointer_input() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.screen = Screen::Accessibility;
    let context = egui::Context::default();
    context.enable_accesskit();
    click(&mut app, &context, "中文");
    assert_eq!(app.locale, Locale::Chinese);
    click(&mut app, &context, "English");
    assert_eq!(app.locale, Locale::English);
    for (label, expected) in [("125%", 1.25), ("150%", 1.5), ("100%", 1.0)] {
        click(&mut app, &context, label);
        render(&mut app, &context, Vec::new());
        assert_eq!(context.zoom_factor(), expected);
    }
    assert!(app.all_tasks_idle());
}

#[test]
fn native_blocked_form_buttons_explain_and_do_not_dispatch() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    let context = egui::Context::default();
    context.enable_accesskit();
    let tree = render(&mut app, &context, Vec::new());
    assert_eq!(
        ["Prepare exact binding", "Execute with signed grant"]
            .map(|label| label_node(&tree, label).is_disabled()),
        [true, true]
    );
    label_node(
        &tree,
        "Verify or refresh the runtime snapshot before preparing an operation.",
    );
    click(&mut app, &context, "Execute with signed grant");
    app.screen = Screen::Updates;
    let tree = render(&mut app, &context, Vec::new());
    assert!(label_node(&tree, "Verify & stage").is_disabled());
    label_node(&tree, "Choose both files or enter their absolute paths.");
    click(&mut app, &context, "Verify & stage");
    assert!(app.all_tasks_idle());
    assert_eq!(
        (app.operation_message, app.update_message, app.last_error),
        (None, None, None)
    );
}

#[test]
fn native_update_recovery_is_visible_and_never_presented_as_confirmed() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.screen = Screen::Updates;
    app.pending_update = Some(PendingUpdateV1 {
        schema: "hepta.native-pending-update.v1".into(),
        manifest: SignedUpdateManifestV1 {
            schema: "hepta.native-update.v1".into(),
            package_digest: "1".repeat(64),
            predecessor_digest: "2".repeat(64),
            evidence_digest: "3".repeat(64),
            platform: std::env::consts::OS.into(),
            architecture: std::env::consts::ARCH.into(),
            backend_protocol_version: 2,
            channel: "stable".into(),
            selected_by: "fixture.reviewer".into(),
            generator_principal: "fixture.builder".into(),
            issued_unix_ms: 1,
            expires_unix_ms: 2,
            key_id: "fixture.key".into(),
            signature_base64: String::new(),
        },
        staged_package: root.path().join("fixture.package"),
        target_path: None,
        backup_path: None,
        status: PendingUpdateStatus::RecoveryRequired,
        transition_unix_ms: 0,
        recovery_reason: Some("Fixture: predecessor cannot be verified".into()),
        handoff: None,
        readiness: None,
    });
    let context = egui::Context::default();
    context.enable_accesskit();
    let tree = render(&mut app, &context, Vec::new());
    label_node(&tree, "Recovery required · inspect the recorded reason");
    label_node(&tree, "Fixture: predecessor cannot be verified");
    assert!(
        !tree
            .nodes
            .iter()
            .any(|(_, node)| node.label() == Some("Activate on restart & close"))
    );
    assert!(app.all_tasks_idle());
    assert!(!app.shutdown.requested());
}

#[test]
fn clicking_an_already_visible_field_does_not_recenter_the_form() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    let context = egui::Context::default();
    let mut frame = eframe::Frame::_new_kittest();
    let mut render = |app: &mut HeptaNativeApp, events| {
        context
            .run_ui(
                egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(
                        egui::Pos2::ZERO,
                        egui::vec2(800.0, 560.0),
                    )),
                    events,
                    ..Default::default()
                },
                |ui| app.ui(ui, &mut frame),
            )
            .drop_without_applying_deltas();
    };
    for _ in 0..3 {
        render(&mut app, Vec::new());
    }
    let id = egui::Id::new("native-operation-subject");
    let before = context.read_response(id).unwrap().rect;
    for pressed in [true, false] {
        render(
            &mut app,
            vec![
                egui::Event::PointerMoved(before.center()),
                egui::Event::PointerButton {
                    pos: before.center(),
                    button: egui::PointerButton::Primary,
                    pressed,
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
    }
    for _ in 0..3 {
        render(&mut app, Vec::new());
    }
    assert_eq!(context.memory(|memory| memory.focused()), Some(id));
    assert_eq!(context.read_response(id).unwrap().rect, before);
    assert!(app.all_tasks_idle());
}
