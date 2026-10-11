use serde_json::json;

use super::session::dynamic_pointer;
use super::session::result;
use crate::QualificationError;

#[test]
fn extracts_only_bounded_dynamic_identifiers() -> Result<(), QualificationError> {
    let value = json!({"thread": {"id": "thread-123"}});
    assert_eq!(
        dynamic_pointer(&value, "/thread/id", "thread")?,
        "thread-123"
    );
    let invalid = json!({"thread": {"id": "thread id"}});
    assert!(dynamic_pointer(&invalid, "/thread/id", "thread").is_err());
    Ok(())
}

#[test]
fn requires_an_explicit_response_result() -> Result<(), QualificationError> {
    assert_eq!(
        result(json!({"result": {"ok": true}}), "test")?,
        json!({"ok": true})
    );
    assert!(result(json!({"id": 1}), "test").is_err());
    Ok(())
}
