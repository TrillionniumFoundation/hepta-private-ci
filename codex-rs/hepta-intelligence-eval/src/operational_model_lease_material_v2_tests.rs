#![allow(clippy::unwrap_used)]
use super::*;
use serde_json::json;
fn closure() -> serde_json::Value {
    let pin = Digest32::of_bytes(b"actual immutable code").to_string();
    let source = |path| json!({"path":path,"digest":pin});
    json!({"schema":"hepta.cpu-neuron.implementation-closure.v2","worker_host":source("/code/worker"),"fixed_encoder_program":source("/code/encoder.py"),"encoder_runtime":source("/code/runtime"),"encoder_helper_sources":[source("/code/helper.py")],"numpy_sources":[source("/code/numpy/core.so")]})
}
#[test]
fn original_implementation_closure_cannot_alias_or_omit_a_required_program() {
    let original = closure();
    assert_eq!(
        serde_json::from_value::<ImplementationClosure>(original.clone())
            .unwrap()
            .sources()
            .unwrap()
            .len(),
        5
    );
    for (field, value) in [
        ("worker_host", original["encoder_runtime"].clone()),
        ("encoder_helper_sources", json!([])),
        ("numpy_sources", json!([])),
        ("schema", json!("older caller declaration")),
    ] {
        let mut changed = original.clone();
        changed[field] = value;
        assert!(
            serde_json::from_value::<ImplementationClosure>(changed)
                .unwrap()
                .sources()
                .is_err()
        );
    }
}
#[test]
fn caller_goal_or_expiry_cannot_enter_the_immutable_code_closure() {
    for field in ["goal_digest", "request_id", "expires_at_ms"] {
        let mut changed = closure();
        changed[field] = json!(123);
        assert!(serde_json::from_value::<ImplementationClosure>(changed).is_err());
    }
}
