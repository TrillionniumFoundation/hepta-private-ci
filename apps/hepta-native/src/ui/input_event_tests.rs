use base64::Engine as _;

use super::*;

pub(super) fn app_fixture(root: &std::path::Path) -> HeptaNativeApp {
    let state = root.join("state");
    crate::private_state::PrivateStateRoot::open(state.clone()).unwrap();
    let key_path = root.join("keys.json");
    let key = ed25519_dalek::SigningKey::from_bytes(&[37; 32]);
    std::fs::write(
        &key_path,
        serde_json::to_vec(&serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {"test.key": base64::engine::general_purpose::STANDARD.encode(key.verifying_key().as_bytes())}
        }))
        .unwrap(),
    )
    .unwrap();
    let updater = UpdateManager::new(
        crate::security::TrustedKeySet::from_path(&key_path).unwrap(),
        state.join("updates"),
    )
    .unwrap();
    let runtime = NativeShellRuntime::new(
        Box::new(
            crate::backend::LoopbackGatewayBackend::new(
                "127.0.0.1:9".parse().unwrap(),
                "A".repeat(48),
            )
            .unwrap(),
        ),
        Box::new(crate::platform::SystemPlatformAdapter::new(
            crate::platform::PlatformPolicy::new(Vec::new(), false, false).unwrap(),
        )),
        None,
        crate::journal::OperationJournal::open(state.join("journal.json")).unwrap(),
    );
    // Construct a disconnected presentation without writing the real user's
    // session-reference store or starting any external runtime or OS effect.
    HeptaNativeApp {
        runtime: Arc::new(Mutex::new(runtime)),
        manifest: EndpointManifest {
            endpoint_id: "test.endpoint".into(),
            address: "127.0.0.1:9".into(),
            manifest_digest: "1".repeat(64),
            protocol_version: 2,
        },
        screen: Screen::Operations,
        locale: Locale::English,
        connected: false,
        status_rendered: None,
        view_revision: None,
        ready_view: None,
        gui_frame: 0,
        readiness_frames: ReadinessFrames::default(),
        operations: Vec::new(),
        history_page: 0,
        history_total: 0,
        file_input_focus: None,
        pending_runtime: None,
        pending_read: None,
        pending_picker: None,
        shutdown: Shutdown::default(),
        repaint: Arc::new(Mutex::new(None)),
        last_error: None,
        operation_subject_id: String::new(),
        operation_id: String::new(),
        operation_action: PlatformAction::Notify,
        operation_path: String::new(),
        operation_text: String::new(),
        notification_title: String::new(),
        notification_body: String::new(),
        operation_grant_path: String::new(),
        operation_binding: None,
        operation_message: None,
        startup_recorder: None,
        update_handoff: None,
        pending_update_path: updater.pending_path(),
        pending_update: None,
        updater,
        activate_update_on_exit: Arc::new(AtomicBool::new(false)),
        update_manifest_path: String::new(),
        update_package_path: String::new(),
        update_message: None,
    }
}

fn render_operations(app: &mut HeptaNativeApp, context: &egui::Context, events: Vec<egui::Event>) {
    context
        .run_ui(
            egui::RawInput {
                events,
                ..egui::RawInput::default()
            },
            |ui| app.operations_view(ui),
        )
        .drop_without_applying_deltas();
}

#[test]
fn actual_notification_fields_bound_paste_and_keep_byte_validation() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    let context = egui::Context::default();
    render_operations(&mut app, &context, Vec::new());
    context.memory_mut(|memory| {
        memory.request_focus(egui::Id::new("native-notification-title"));
    });
    render_operations(
        &mut app,
        &context,
        vec![egui::Event::Paste(
            "a".repeat(crate::model::MAX_NOTIFICATION_TITLE_BYTES + 1),
        )],
    );
    assert_eq!(
        app.notification_title,
        "a".repeat(crate::model::MAX_NOTIFICATION_TITLE_BYTES)
    );
    context.memory_mut(|memory| {
        memory.request_focus(egui::Id::new("native-notification-body"));
    });
    render_operations(
        &mut app,
        &context,
        vec![egui::Event::Paste(
            "汉".repeat(crate::model::MAX_NOTIFICATION_BODY_BYTES + 1),
        )],
    );
    assert_eq!(
        app.notification_body,
        "汉".repeat(crate::model::MAX_NOTIFICATION_BODY_BYTES)
    );
    assert!(
        PlatformPayload::Notify {
            title: app.notification_title.clone(),
            body: app.notification_body.clone(),
        }
        .validate()
        .is_err()
    );
}

#[test]
fn switching_action_does_not_redirect_the_previous_fields_keyboard_focus() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    let context = egui::Context::default();
    app.operation_action = PlatformAction::OpenPath;
    render_operations(&mut app, &context, Vec::new());
    context.memory_mut(|memory| memory.request_focus(egui::Id::new("native-operation-path")));
    app.operation_action = PlatformAction::CopyText;
    render_operations(
        &mut app,
        &context,
        vec![egui::Event::Text("must not populate another target".into())],
    );
    assert_eq!(app.operation_text, "");
}

#[test]
fn diagnostic_render_failure_invalidates_presentation_binding_and_readiness() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    let view = RuntimeView {
        session_id: "test.session".into(),
        session_generation: 1,
        generation: 1,
        revision: 1,
        digest: "1".repeat(64),
        modules: vec!["ui.native".into()],
    };
    app.connected = true;
    app.status_rendered = Some("previous snapshot".into());
    app.view_revision = Some(1);
    app.ready_view = Some(view.clone());
    app.operation_binding = Some(PreparedBinding {
        text: "previous final-use binding".into(),
        input: super::binding_prepare::BindingInput::capture(&app).unwrap(),
    });
    app.readiness_frames.observe(1, &view).unwrap();
    let error = "cannot render bounded runtime status: presentation byte bound".to_owned();
    app.handle_task_outcome(UiTaskKind::Refresh, Ok(Err(error.clone())));
    assert_eq!(
        (
            app.connected,
            app.status_rendered,
            app.view_revision,
            app.ready_view,
            app.operation_binding,
            app.last_error,
        ),
        (false, None, None, None, None, Some(error))
    );
    assert!(app.readiness_frames.observe(1, &view).unwrap().is_none());
}
