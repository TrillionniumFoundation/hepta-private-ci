//! Parser compatibility only; these metadata fixtures grant no sending right.

use super::SubmissionStatus;
use serde_json::json;

#[test]
fn admitted_submission_requires_original_boolean_idempotent_field() {
    let admitted = json!({
        "type": "admitted",
        "run_id": "original-run",
        "objective_digest": "11".repeat(32),
        "hard_constraint_digest": "22".repeat(32),
        "publication_digest": "33".repeat(32),
        "chain_digest": "44".repeat(32),
        "disposition": "compiled",
        "idempotent": false,
        "response_generation": 1,
    });
    for idempotent in [false, true] {
        let mut value = admitted.clone();
        value["idempotent"] = json!(idempotent);
        assert!(matches!(
            serde_json::from_value::<SubmissionStatus>(value).expect("original admitted schema"),
            SubmissionStatus::Admitted { .. }
        ));
    }

    let mut missing = admitted.clone();
    missing.as_object_mut().unwrap().remove("idempotent");
    assert!(serde_json::from_value::<SubmissionStatus>(missing).is_err());

    for invalid in [json!(null), json!("false"), json!(0), json!([]), json!({})] {
        let mut value = admitted.clone();
        value["idempotent"] = invalid;
        assert!(serde_json::from_value::<SubmissionStatus>(value).is_err());
    }

    for unknown in ["_idempotent", "unrecognized"] {
        let mut value = admitted.clone();
        value[unknown] = json!(true);
        assert!(serde_json::from_value::<SubmissionStatus>(value).is_err());
    }
}
