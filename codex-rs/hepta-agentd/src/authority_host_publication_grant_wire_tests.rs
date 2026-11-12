//! Strict data framing only; no Root owner or issuance is constructed here.

use super::*;

#[test]
fn c_grant_wire_accepts_only_original_cut_equality_fields() -> anyhow::Result<()> {
    let valid = serde_json::json!({"schema":2,"purpose":PublicationVersion::DurableV2.purpose(),
        "request_id":7,"profile":"pinned", "command":{"kind":"issue_final_use","expected":"head","intent":"intent"}});
    let request: Request = serde_json::from_value(valid.clone())?;
    assert_eq!(serde_json::to_value(request)?, valid);
    for key in ["binding", "writer", "proof", "policy", "signed", "expiry"] {
        let mut changed = valid.clone();
        changed["command"][key] = serde_json::json!({"peer":"cannot-select"});
        assert!(
            serde_json::from_value::<Request>(changed).is_err(),
            "accepted {key}"
        );
    }
    for key in ["expected", "intent"] {
        let mut changed = valid.clone();
        changed["command"]
            .as_object_mut()
            .ok_or_else(|| anyhow::anyhow!("command object"))?
            .remove(key);
        assert!(
            serde_json::from_value::<Request>(changed).is_err(),
            "missing {key}"
        );
    }
    let mut changed = valid;
    changed["issuer"] = serde_json::json!("peer-selected");
    assert!(serde_json::from_value::<Request>(changed).is_err());
    Ok(())
}
