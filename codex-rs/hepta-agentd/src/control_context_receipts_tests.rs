use super::*;
use crate::CognitiveContextPlan;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn profiles() -> Profiles {
    Profiles {
        retrieval: Some(digest("retrieval")),
        ranker: Some(digest("ranker")),
    }
}

fn entry(now: Instant) -> Entry {
    Entry {
        request_binding: digest("owner-generation-request-query-limit"),
        response_binding: digest("complete-ordered-response"),
        profiles: profiles(),
        lifecycle_generation: 2,
        issued: now,
        expires: now + CONTEXT_LEASE,
    }
}

fn require(
    receipts: &ContextPlanReceipts,
    plan: Digest32,
    entry: &Entry,
    now: Instant,
) -> Result<Digest32, AgentdError> {
    receipts.require(
        plan,
        entry.response_binding,
        entry.profiles,
        entry.lifecycle_generation,
        now,
    )
}

#[test]
fn an_issued_unchanged_receipt_is_accepted() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let entry = entry(now);
    let plan = digest("native-plan");
    receipts.publish(plan, entry.clone(), now).expect("publish");
    assert_eq!(
        require(&receipts, plan, &entry, now).expect("current receipt"),
        entry.binding(plan)
    );
}

#[test]
fn changing_only_the_native_plan_receipt_digest_is_rejected() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let entry = entry(now);
    receipts.publish(digest("native-plan"), entry.clone(), now).expect("publish");
    assert!(require(&receipts, digest("tampered-plan"), &entry, now).is_err());
}

#[test]
fn swapping_another_issued_plan_cannot_rebind_its_response() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let first = entry(now);
    let mut second = first.clone();
    second.response_binding = digest("other-response");
    second.request_binding = digest("other-request");
    receipts.publish(digest("first-plan"), first.clone(), now).expect("first");
    receipts.publish(digest("second-plan"), second, now).expect("second");
    assert!(require(&receipts, digest("second-plan"), &first, now).is_err());
}

#[test]
fn retrieval_and_ranker_configuration_are_separately_fenced() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let original = entry(now);
    let plan = digest("plan");
    receipts.publish(plan, original.clone(), now).expect("publish");
    for changed in [
        Profiles { retrieval: None, ranker: original.profiles.ranker },
        Profiles { retrieval: original.profiles.retrieval, ranker: None },
        Profiles { retrieval: Some(digest("new-retrieval")), ranker: original.profiles.ranker },
        Profiles { retrieval: original.profiles.retrieval, ranker: Some(digest("new-ranker")) },
    ] {
        let mut candidate = original.clone();
        candidate.profiles = changed;
        assert!(require(&receipts, plan, &candidate, now).is_err());
    }
}

#[test]
fn lifecycle_generation_change_closes_final_use() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let mut entry = entry(now);
    let plan = digest("plan");
    receipts.publish(plan, entry.clone(), now).expect("publish");
    entry.lifecycle_generation += 1;
    assert!(require(&receipts, plan, &entry, now).is_err());
}

#[test]
fn expiry_and_clock_regression_are_fail_closed_without_sleeping() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now() + Duration::from_secs(1);
    let entry = entry(now);
    let plan = digest("plan");
    receipts.publish(plan, entry.clone(), now).expect("publish");
    assert!(require(&receipts, plan, &entry, now - Duration::from_nanos(1)).is_err());
    assert!(require(&receipts, plan, &entry, entry.expires).is_err());
    assert!(require(&receipts, plan, &entry, entry.expires - Duration::from_nanos(1)).is_ok());
}

#[test]
fn late_publication_cannot_create_a_fresh_lease() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let entry = entry(now);
    assert!(receipts.publish(digest("late"), entry.clone(), entry.expires).is_err());
}

#[test]
fn replay_does_not_extend_the_original_expiry() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let original = entry(now);
    let plan = digest("plan");
    receipts.publish(plan, original.clone(), now).expect("publish");
    let mut replay = original.clone();
    replay.expires += Duration::from_secs(60);
    receipts.publish(plan, replay, now).expect("equal identity replay");
    assert!(require(&receipts, plan, &original, original.expires).is_err());
}

#[test]
fn a_receipt_cannot_be_reassigned_to_another_request() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let original = entry(now);
    let plan = digest("plan");
    receipts.publish(plan, original.clone(), now).expect("publish");
    let mut changed = original.clone();
    changed.request_binding = digest("another-owner-generation-request-query-limit");
    assert!(receipts.publish(plan, changed, now).is_err());
    assert!(require(&receipts, plan, &original, now).is_ok());
}

#[test]
fn restarting_the_listener_does_not_resurrect_old_receipts() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    let entry = entry(now);
    let plan = digest("plan");
    receipts.publish(plan, entry.clone(), now).expect("publish");
    drop(receipts);
    let restarted = ContextPlanReceipts::default();
    assert!(require(&restarted, plan, &entry, now).is_err());
}

#[test]
fn capacity_is_bounded_and_only_expired_receipts_are_reclaimed() {
    let receipts = ContextPlanReceipts::default();
    let now = Instant::now();
    for index in 0..MAX_RECEIPTS {
        receipts.publish(digest(&format!("plan-{index}")), entry(now), now).expect("bounded slot");
    }
    assert!(receipts.publish(digest("overflow"), entry(now), now).is_err());
    let later = now + CONTEXT_LEASE;
    receipts.publish(digest("after-expiry"), entry(later), later).expect("expired slots reclaimed");
    assert_eq!(receipts.entries.lock().expect("test lock").len(), 1);
}

#[test]
fn full_response_binding_includes_the_plan_receipt_digest() {
    let mut snapshot = CognitiveContextSnapshot {
        snapshot_digest: digest("snapshot").to_string(),
        read_digest: digest("read").to_string(),
        omitted_records: 0,
        items: Vec::new(),
        plan: Some(CognitiveContextPlan {
            evaluated_context_digest: digest("context").to_string(),
            plan_receipt_digest: digest("plan").to_string(),
            read_allowed: false,
        }),
    };
    let original = snapshot_binding(&snapshot).expect("original binding");
    snapshot.plan.as_mut().expect("plan").plan_receipt_digest = digest("tampered").to_string();
    assert_ne!(snapshot_binding(&snapshot).expect("changed binding"), original);
}
