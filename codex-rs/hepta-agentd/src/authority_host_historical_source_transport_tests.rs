//! Wire parsing does not authenticate a publisher or complete a Root handoff.

use pretty_assertions::assert_eq;

use super::*;

#[test]
fn original_source_capture_commands_reject_peer_chosen_material() -> anyhow::Result<()> {
    for kind in ["capture_source", "capture_ack"] {
        let request = serde_json::json!({
            "schema": 1,
            "purpose": SOURCE_CAPTURE_PURPOSE,
            "request_id": 7,
            "profile": "already-bound-profile",
            "command": {"kind": kind}
        });
        let decoded: Request = serde_json::from_value(request.clone())?;
        assert_eq!(serde_json::to_value(decoded)?, request);
        for (name, value) in [
            ("path", serde_json::json!("/peer/chosen/source")),
            ("pin", serde_json::json!("peer-chosen-digest")),
            ("identity", serde_json::json!({"pid": 17})),
            ("observation", serde_json::json!([1, 2, 3])),
            ("completed", serde_json::json!(true)),
        ] {
            let mut changed = request.clone();
            changed["command"][name] = value.clone();
            assert!(serde_json::from_value::<Request>(changed).is_err());
            let mut changed = request.clone();
            changed[name] = value;
            assert!(serde_json::from_value::<Request>(changed).is_err());
        }
    }
    Ok(())
}
