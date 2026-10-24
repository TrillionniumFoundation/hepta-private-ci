#![allow(clippy::expect_used)]

use super::*;

#[test]
fn inspection_snapshot_redacts_url_control_and_oversized_symbolic_fields() {
    for private in [
        "https://SECRET@private.invalid/?token=secret".to_string(),
        "model\nAuthorization: secret".into(),
        "x".repeat(129),
    ] {
        let value = identifier(&private);
        assert!(value["value"].is_null());
        assert_eq!(
            value["sha256"],
            Digest32::of_bytes(private.as_bytes()).to_string()
        );
        assert!(!value.to_string().contains(&private));
    }
    assert_eq!(
        identifier("custom/gpt-6.1-sol")["value"],
        "custom/gpt-6.1-sol"
    );
}

#[test]
fn inspection_snapshot_serialization_writer_refuses_excess_before_append() {
    let mut writer = BoundedBytes {
        bytes: Vec::new(),
        maximum: 4,
    };
    writer.write_all(b"123").expect("within bound");
    assert!(writer.write_all(b"45").is_err());
    assert_eq!(writer.bytes, b"123");
}
