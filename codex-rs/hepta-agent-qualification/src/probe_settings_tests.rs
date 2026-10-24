//! Static privacy and unsupported-protocol boundaries; no installed auth.
#![allow(clippy::expect_used, reason = "explicit model-owner settings fixtures")]

use super::*;
use pretty_assertions::assert_eq;

#[test]
fn lite_is_rejected_before_qualification_admission() {
    let mut model = codex_models_manager::model_info::model_info_from_slug("qualification-fixture");
    require_ordinary_model(&model).expect("ordinary model");
    model.use_responses_lite = true;
    assert!(require_ordinary_model(&model).is_err());
}

#[test]
fn unsafe_metadata_labels_retain_only_identity_not_sensitive_text() {
    let secret = "https://SECRET@private.invalid/path?token=SECRET";
    let report = identifier(secret);
    assert_eq!(report["value"], Value::Null);
    assert_eq!(report["bytes"].as_u64(), Some(secret.len() as u64));
    assert!(!report.to_string().contains("SECRET"));
    assert_eq!(identifier("max")["value"], "max");
}
