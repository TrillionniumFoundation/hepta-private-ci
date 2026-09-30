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
    writer.write_all(&vec![b'x'; MAX_RENDERED_STATUS_BYTES]).unwrap();
    assert!(writer.write_all(b"x").is_err());
    assert_eq!(writer.0.len(), MAX_RENDERED_STATUS_BYTES);
}
