use super::*;

#[test]
fn effect_binding_has_strict_bounded_identity_and_round_trips() {
    let value = CodexEffectBinding {
        run_id: "run.1".to_string(),
        generation: 3,
        expected_revision: 2,
        request_digest: "1".repeat(64),
        context_digest: "2".repeat(64),
        compilation_receipt_digest: "3".repeat(64),
    };
    value.validate().unwrap();
    let mut json = serde_json::to_value(&value).unwrap();
    assert_eq!(
        serde_json::from_value::<CodexEffectBinding>(json.clone()).unwrap(),
        value
    );
    json["terminal_observed"] = serde_json::json!(true);
    assert!(serde_json::from_value::<CodexEffectBinding>(json).is_err());
    for revision in [0, u64::MAX] {
        let mut changed = value.clone();
        changed.expected_revision = revision;
        assert!(changed.validate().is_err());
    }
    for digest in ["0".repeat(64), "F".repeat(64), "1".repeat(65)] {
        let mut changed = value.clone();
        changed.request_digest = digest;
        assert!(changed.validate().is_err());
    }
}
