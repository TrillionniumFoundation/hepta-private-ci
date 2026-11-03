use super::*;

#[test]
fn bounded_wire_json_cannot_expand_into_unbounded_gui_diagnostics() {
    let mut value = serde_json::json!(vec!["value"; 40_000]);
    for _ in 0..64 {
        value = serde_json::json!([value]);
    }
    assert!(serde_json::to_vec(&value).unwrap().len() < 1024 * 1024);
    let error = render_runtime_status(&value).unwrap_err();
    assert!(error.to_string().contains("presentation byte bound"));
}

#[test]
fn presentation_writer_rejects_the_first_byte_over_the_limit() {
    let mut writer = BoundedStatus::default();
    writer
        .write_all(&vec![b'x'; MAX_RENDERED_STATUS_BYTES])
        .unwrap();
    assert!(writer.write_all(b"x").is_err());
    assert_eq!(writer.0.len(), MAX_RENDERED_STATUS_BYTES);
}

#[test]
fn native_control_projection_preserves_exact_owner_identity_without_authority() {
    let view = crate::model::RuntimeView {
        session_id: "native.session".into(),
        session_generation: 8,
        generation: 15,
        revision: u64::MAX,
        digest: "a".repeat(64),
        modules: vec!["ui.native".into(), "runtime.agentd".into()],
    };
    let projected = project_native_runtime_view("native.endpoint", &view).unwrap();
    assert_eq!(
        projected,
        hepta_control_ui::native_projection::NativeReadOnlyProjection {
            observation: hepta_control_ui::native_projection::NativeObservation {
                endpoint_id: "native.endpoint".into(),
                session_id: view.session_id,
                session_generation: 8,
                generation: 15,
                revision: u64::MAX,
                digest: view.digest,
                modules: vec!["runtime.agentd".into(), "ui.native".into()],
            },
            read_only: true,
            mutation_available: false,
        }
    );
}

#[test]
fn native_control_projection_rejects_ambiguous_or_oversized_module_lists() {
    let mut view = crate::model::RuntimeView {
        session_id: "native.session".into(),
        session_generation: 1,
        generation: 1,
        revision: 1,
        digest: "a".repeat(64),
        modules: vec!["ui.native".into(), "ui.native".into()],
    };
    assert!(project_native_runtime_view("native.endpoint", &view).is_err());
    view.modules = (0..1001).map(|index| format!("module.{index}")).collect();
    assert!(project_native_runtime_view("native.endpoint", &view).is_err());
}
