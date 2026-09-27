use super::*;

fn response() -> CognitiveContextSnapshot {
    let digest = Digest32::of_bytes(b"publication-fixture").to_string();
    CognitiveContextSnapshot {
        snapshot_digest: digest.clone(),
        read_digest: digest.clone(),
        omitted_records: 0,
        items: vec![CognitiveContextItem {
            memory_id: "memory:publication".to_string(),
            revision: 1,
            content: "verified content".to_string(),
            content_sha256: Sha256Digest::for_bytes(b"verified content").as_str().to_string(),
        }],
        plan: Some(CognitiveContextPlan {
            evaluated_context_digest: digest.clone(),
            plan_receipt_digest: format!("context-plan-v2:{digest}:{digest}"),
            read_allowed: true,
        }),
    }
}

#[test]
fn learning_digest_covers_the_final_seal_not_the_pre_seal_envelope() {
    let sealed = response();
    let actual = recorded_response_digest(&sealed).expect("delivery digest");
    assert_eq!(
        actual,
        Some(Digest32::of_bytes(
            &serde_json::to_vec(&sealed).expect("encoded final response")
        ))
    );
    let mut before_sealing = response();
    before_sealing.plan.as_mut().expect("plan").plan_receipt_digest =
        Digest32::of_bytes(b"raw-plan-only").to_string();
    assert_ne!(
        actual,
        recorded_response_digest(&before_sealing).expect("raw digest")
    );
}

#[test]
fn abstention_does_not_claim_context_exposure() {
    let mut abstained = response();
    abstained.items.clear();
    abstained.plan.as_mut().expect("plan").read_allowed = false;
    assert_eq!(recorded_response_digest(&abstained).expect("abstain"), None);
}

#[test]
fn delivery_digest_binds_record_order_and_metadata() {
    let original = response();
    let expected = recorded_response_digest(&original).expect("original");
    let mut changed = response();
    changed.omitted_records = 1;
    assert_ne!(
        expected,
        recorded_response_digest(&changed).expect("metadata")
    );
    changed = original;
    changed.items[0].revision = 2;
    assert_ne!(
        expected,
        recorded_response_digest(&changed).expect("revision")
    );
}
