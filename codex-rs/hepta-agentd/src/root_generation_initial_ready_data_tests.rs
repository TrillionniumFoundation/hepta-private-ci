use super::*;
use serde_json::json;

#[test]
fn original_initial_ready_request_rejects_payload_and_wrong_binding() -> anyhow::Result<()> {
    let binding = Digest32::of_bytes(b"original sealed bootstrap").to_string();
    let bytes = request(&binding)?;
    require_request(&bytes, &binding)?;
    let original: serde_json::Value = serde_json::from_slice(&bytes)?;
    for (field, value) in [
        ("schema", json!(2)),
        (
            "purpose",
            json!("runtime.cell-generation.initial-publication.v1"),
        ),
        ("request_id", json!(2)),
        (
            "bootstrap",
            json!(Digest32::of_bytes(b"other original Root").to_string()),
        ),
        ("path", json!("/peer/selected/owner")),
        ("command", json!({"kind":"ready", "owner":"peer-metadata"})),
        ("command", json!({"kind":"observe"})),
    ] {
        let mut changed = original.clone();
        changed[field] = value;
        assert!(
            require_request(&serde_json::to_vec(&changed)?, &binding).is_err(),
            "field={field}"
        );
    }
    assert!(
        require_request(
            &bytes,
            &Digest32::of_bytes(b"another bootstrap").to_string()
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn original_initial_ready_reply_requires_exact_canonical_correlation() -> anyhow::Result<()> {
    let binding = Digest32::of_bytes(b"same original bootstrap").to_string();
    let profile = Digest32::of_bytes(b"registered original profile").to_string();
    let bytes = response(&binding, &profile)?;
    assert_eq!(require_response(&bytes, &binding)?, profile);
    let original: serde_json::Value = serde_json::from_slice(&bytes)?;
    for (field, value) in [
        ("schema", json!(0)),
        ("purpose", json!("another.purpose")),
        ("request_id", json!(0)),
        (
            "bootstrap",
            json!(Digest32::of_bytes(b"other bootstrap").to_string()),
        ),
        ("profile", json!("00".repeat(32))),
        ("profile", json!(profile.to_ascii_uppercase())),
        ("completed", json!(true)),
    ] {
        let mut changed = original.clone();
        changed[field] = value;
        assert!(
            require_response(&serde_json::to_vec(&changed)?, &binding).is_err(),
            "field={field}"
        );
    }
    Ok(())
}
