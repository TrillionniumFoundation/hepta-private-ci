use super::*;
use crate::CognitiveContextItem;

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap()
}

fn unplanned() -> CognitiveContextSnapshot {
    CognitiveContextSnapshot {
        snapshot_digest: Digest32::of_bytes(b"owner-snapshot").to_string(),
        read_digest: Digest32::of_bytes(b"owner-read").to_string(),
        omitted_records: 0,
        items: vec![CognitiveContextItem {
            memory_id: "memory:plan".to_string(),
            revision: 1,
            content: "bounded verified content".to_string(),
            content_sha256: Digest32::of_bytes(b"bounded verified content").to_string(),
        }],
        plan: None,
    }
}

#[test]
fn publication_binds_receipt_owner_generation_and_ordered_payload() {
    let mut response = unplanned();
    let owner_read = parse_digest(&response.read_digest).unwrap();
    let fresh = evaluate(&owner(), /*body_generation*/ 7, &response, /*observed_at_micros*/ 100).unwrap();
    response.read_digest = bind(&owner(), /*body_generation*/ 7, owner_read, &fresh.plan).unwrap().to_string();
    response.plan = Some(fresh.plan);
    let recovered = verify_publication(&owner(), /*body_generation*/ 7, owner_read, &response).unwrap();
    assert_eq!(serde_json::to_vec(&recovered).unwrap(), serde_json::to_vec(&unplanned()).unwrap());

    let mut changed = response.clone();
    changed.plan.as_mut().unwrap().plan_receipt_digest = Digest32::of_bytes(b"substituted").to_string();
    assert!(verify_publication(&owner(), /*body_generation*/ 7, owner_read, &changed).is_err());
    assert!(verify_publication(&owner(), /*body_generation*/ 8, owner_read, &response).is_err());
    let other = AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap();
    assert!(verify_publication(&other, /*body_generation*/ 7, owner_read, &response).is_err());
    let mut changed = response.clone();
    changed.items[0].content.push('!');
    assert!(verify_publication(&owner(), /*body_generation*/ 7, owner_read, &changed).is_err());
    let mut changed = response;
    changed.plan.as_mut().unwrap().read_allowed = false;
    assert!(verify_publication(&owner(), /*body_generation*/ 7, owner_read, &changed).is_err());
}

#[test]
fn fresh_plan_deadline_is_half_open_and_rejects_clock_regression() {
    let fresh = evaluate(&owner(), /*body_generation*/ 1, &unplanned(), /*observed_at_micros*/ 100).unwrap();
    assert!(fresh.plan.read_allowed);
    assert!(fresh.ensure_current(/*now_micros*/ 100).is_ok());
    assert!(fresh.ensure_current(/*now_micros*/ 1_000_099).is_ok());
    assert!(fresh.ensure_current(/*now_micros*/ 1_000_100).is_err());
    assert!(fresh.ensure_current(/*now_micros*/ 99).is_err());
    assert!(evaluate(&owner(), /*body_generation*/ 1, &unplanned(), u64::MAX).is_err());
}

#[test]
fn historical_plan_is_not_reused_as_a_future_plan() {
    let response = unplanned();
    let old = evaluate(&owner(), /*body_generation*/ 1, &response, /*observed_at_micros*/ 100).unwrap();
    assert!(old.ensure_current(/*now_micros*/ 2_000_100).is_err());
    let current = evaluate(&owner(), /*body_generation*/ 1, &response, /*observed_at_micros*/ 2_000_100).unwrap();
    assert!(current.ensure_current(/*now_micros*/ 2_000_100).is_ok());
    assert_ne!(old.plan.plan_receipt_digest, current.plan.plan_receipt_digest);
    assert_eq!(old.plan.evaluated_context_digest, current.plan.evaluated_context_digest);
    let mut empty = response;
    empty.items.clear();
    let abstain = evaluate(&owner(), /*body_generation*/ 1, &empty, /*observed_at_micros*/ 2_000_100).unwrap();
    assert!(!abstain.plan.read_allowed);
}
