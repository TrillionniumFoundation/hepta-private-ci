use codex_hepta_contracts::Sha256Digest;
use serde_json::Value;
use serde_json::json;

use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceId;
use crate::EvidenceIssuerRoleV1;
use crate::EvidenceReceiptKindV1;
use crate::QualificationEvidenceEnvelopeV1;
use crate::Verify1Record;
use crate::Verify1Scope;
use crate::Verify1Verdict;
use crate::Verify1VerificationReceipt;
use crate::parse_verify1_payload;
use crate::verify1_receipt_payload;
use crate::verify1_report::python_integer_json;

fn scope() -> Verify1Scope {
    Verify1Scope {
        task_id: "task:typed".to_string(),
        attempt_id: "attempt:typed".to_string(),
        subject_sha256: "a".repeat(64),
        state_version: 3,
        domain: "fixture".to_string(),
        event: "terminal_error".to_string(),
        horizon_start: 4,
        horizon_end: 4,
    }
}

fn risk() -> Value {
    json!({"type":"risk_prediction", "scope":scope(),
        "model":{"base_sha256":"b".repeat(64),"adapter_sha256":null,"policy_sha256":"c".repeat(64)},
        "probability":0.25,"observed_step":0,"evidence_sha256":"d".repeat(64)})
}

fn wrap(raw: String, kind: &str) -> Value {
    json!({"schema_version":1,"payload_type":"hepta.verify1.report",
        "record_type":kind,"record_encoding":"verify1-python-canonical-json-v1",
        "record_sha256":Sha256Digest::for_bytes(raw.as_bytes()).as_str(),"record_json":raw})
}

#[test]
fn hashes_original_python_float_bytes_without_serde_float_equivalence() {
    let raw = serde_json::to_string(&risk())
        .unwrap()
        .replace("0.25", "1e-07");
    let payload = wrap(raw.clone(), "risk_prediction");
    let Verify1Record::RiskPrediction(parsed) = parse_verify1_payload(&payload).unwrap() else {
        panic!("wrong report type");
    };
    assert_eq!(parsed.probability, 1e-7);
    assert_eq!(parsed.scope, scope());
    assert!(raw.contains("1e-07"));
    let mut tampered = payload;
    tampered["record_json"] = json!(raw.replace("1e-07", "0.25"));
    assert!(parse_verify1_payload(&tampered).is_err());
}

#[test]
fn rejects_malformed_identity_probability_duplicates_and_missing_nullable_field() {
    let valid = risk();
    for invalid in [
        json!(-0.1),
        json!(1.1),
        json!(true),
        json!(null),
        json!("NaN"),
        json!({"$serde_json::private::Number":"0.25"}),
    ] {
        let mut row = valid.clone();
        row["probability"] = invalid;
        assert!(parse_verify1_payload(&wrap(row.to_string(), "risk_prediction")).is_err());
    }
    let raw = valid.to_string();
    for malformed in [
        raw.replacen('{', "{\"probability\":0.5,", 1),
        raw.replace("0.25", "1e999"),
        raw.replace("0.25", "NaN"),
        raw.replace("\"adapter_sha256\":null,", ""),
        raw.replacen('{', "{\"unknown_field\":0,", 1),
    ] {
        assert!(parse_verify1_payload(&wrap(malformed, "risk_prediction")).is_err());
    }
    let mut invalid = valid;
    invalid["observed_step"] = json!(5);
    assert!(parse_verify1_payload(&wrap(invalid.to_string(), "risk_prediction")).is_err());
    let mut payload = wrap(raw, "verification_receipt");
    assert!(parse_verify1_payload(&payload).is_err());
    payload["record_type"] = json!("risk_prediction");
    payload["extra"] = json!(true);
    assert!(parse_verify1_payload(&payload).is_err());
}

#[test]
fn calibration_partitions_and_metric_semantics_remain_descriptive() {
    let model = risk()["model"].clone();
    let mut row = json!({"type":"calibration_report","scope":scope(),"model":model,
        "training_source_groups":[],"calibration_source_groups":["cal:a"],
        "confirmation_source_groups":["confirmation:a"],"data_sha256":"e".repeat(64),
        "metric":"brier","metric_kind":"proper_scoring_rule","metric_value":0.2,
        "sample_count":3,"drift":"unknown","assumptions":["descriptive fixture sample"]});
    assert!(matches!(
        parse_verify1_payload(&wrap(row.to_string(), "calibration_report")),
        Ok(Verify1Record::CalibrationReport(_))
    ));
    row["confirmation_source_groups"] = json!(["cal:a"]);
    assert!(parse_verify1_payload(&wrap(row.to_string(), "calibration_report")).is_err());
    row["confirmation_source_groups"] = json!(["confirmation:a"]);
    row["metric_kind"] = json!("outcome_event_frequency");
    assert!(parse_verify1_payload(&wrap(row.to_string(), "calibration_report")).is_err());
}

#[test]
fn integer_receipt_encoding_matches_python_unicode_and_residual_contract() {
    let raw = python_integer_json(&json!({"z":"猴🧪\u{7f}","a":3})).unwrap();
    assert_eq!(raw, br#"{"a":3,"z":"\u7334\ud83e\uddea\u007f"}"#);
    assert!(python_integer_json(&json!({"probability":0.25})).is_err());
    let mut receipt = Verify1VerificationReceipt {
        scope: scope(),
        property: "fixture_property".to_string(),
        assumptions: vec!["trusted owner".to_string()],
        checker_id: "checker:typed".to_string(),
        checker_version: "1".to_string(),
        evidence_sha256: "f".repeat(64),
        checked_step: 4,
        verdict: Verify1Verdict::Proved,
        reason: "finite snapshot".to_string(),
        residual_obligations: vec![],
    };
    assert_eq!(
        parse_verify1_payload(&verify1_receipt_payload(&receipt).unwrap()).unwrap(),
        Verify1Record::VerificationReceipt(receipt.clone())
    );
    receipt
        .residual_obligations
        .push("missing readback".to_string());
    assert!(verify1_receipt_payload(&receipt).is_err());
    receipt.verdict = Verify1Verdict::Unknown;
    assert!(verify1_receipt_payload(&receipt).is_ok());
    receipt.residual_obligations.clear();
    assert!(verify1_receipt_payload(&receipt).is_err());
}

#[test]
fn namespaced_envelope_validates_report_without_interpreting_proved_as_authority() {
    let mut envelope = QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        evidence_id: EvidenceId::parse("evidence:verify1:typed").unwrap(),
        candidate: EvidenceCandidateV1 {
            candidate_id: "candidate:verify1".to_string(),
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
        },
        claim_class: EvidenceClaimClassV1::Fixture,
        receipt_kind: EvidenceReceiptKindV1::Evidence,
        issuer_role: EvidenceIssuerRoleV1::TerminalObserver,
        payload: wrap(risk().to_string(), "risk_prediction"),
        predecessor_evidence_id: None,
        target_evidence_id: None,
        observed_unix_ms: 10,
        expires_unix_ms: None,
        asset_digests: vec![],
    };
    assert!(envelope.validate().is_ok());
    envelope.payload["record_sha256"] = json!("0".repeat(64));
    assert!(envelope.validate().is_err());
    envelope.payload = json!({"existing_generic_payload":true});
    assert!(envelope.validate().is_ok());
}
