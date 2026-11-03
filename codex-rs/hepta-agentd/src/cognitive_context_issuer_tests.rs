use super::*;

fn context(receipt: &str) -> CognitiveContextSnapshot {
    let mut snapshot = CognitiveContextSnapshot {
        snapshot_digest: Digest32::of_bytes(b"owner-cut").to_string(),
        read_digest: Digest32::of_bytes(b"exact-id-read").to_string(),
        omitted_records: 0,
        items: ["first", "second"]
            .into_iter()
            .map(|content| CognitiveContextItem {
                memory_id: content.to_string(),
                revision: 1,
                content: content.to_string(),
                content_sha256: Digest32::of_bytes(content.as_bytes()).to_string(),
            })
            .collect(),
        plan: None,
    };
    let evaluated_context_digest = ContextEnvelope::from(&snapshot)
        .digest()
        .unwrap()
        .to_string();
    snapshot.plan = Some(CognitiveContextPlan {
        evaluated_context_digest,
        plan_receipt_digest: Digest32::of_bytes(receipt.as_bytes()).to_string(),
        read_allowed: true,
    });
    snapshot
}

fn planned(snapshot: CognitiveContextSnapshot) -> PlannedContextRead {
    PlannedContextRead::new(snapshot, "owner", 1, Instant::now(), 100, 1_000_100).unwrap()
}

#[test]
fn issuance_binds_exact_native_wire_order_owner_body_and_receipt() {
    let issuer = ContextPlanIssuer::default();
    let snapshot = issuer.issue(planned(context("original"))).unwrap();
    assert_eq!(
        ContextEnvelope::from(&snapshot).digest().unwrap(),
        Digest32::of_bytes(&serde_json::to_vec(&snapshot).unwrap())
    );
    issuer.validate("owner", 1, &snapshot).unwrap();
    assert!(issuer.issue(planned(snapshot.clone())).is_err());
    issuer
        .validate("owner", /*body_generation*/ 1, &snapshot)
        .unwrap();
    assert!(issuer.validate("other-owner", 1, &snapshot).is_err());
    assert!(issuer.validate("owner", 2, &snapshot).is_err());
    assert!(
        ContextPlanIssuer::default()
            .validate("owner", 1, &snapshot)
            .is_err()
    );
    let mut swapped = snapshot.clone();
    swapped.items.swap(0, 1);
    let mut plan = swapped.plan.take().unwrap();
    plan.evaluated_context_digest = ContextEnvelope::from(&swapped)
        .digest()
        .unwrap()
        .to_string();
    swapped.plan = Some(plan);
    assert!(issuer.validate("owner", 1, &swapped).is_err());
    let mut forged_receipt = snapshot.clone();
    forged_receipt.plan.as_mut().unwrap().plan_receipt_digest =
        Digest32::of_bytes(b"self-computed-plan").to_string();
    assert!(issuer.validate("owner", 1, &forged_receipt).is_err());
    issuer.retract(&snapshot);
    assert!(issuer.validate("owner", 1, &snapshot).is_err());
}

#[test]
fn expired_issuance_cannot_publish_or_survive_final_use() {
    let issuer = ContextPlanIssuer::default();
    let mut expired_read = planned(context("too-late"));
    expired_read.deadline = Instant::now() - Duration::from_secs(1);
    assert!(issuer.issue(expired_read).is_err());
    let snapshot = issuer.issue(planned(context("live"))).unwrap();
    let receipt = receipt_digest(&snapshot).unwrap();
    issuer
        .issued
        .lock()
        .unwrap()
        .get_mut(&receipt)
        .unwrap()
        .deadline = Instant::now() - Duration::from_secs(1);
    assert!(issuer.validate("owner", 1, &snapshot).is_err());
    assert!(issuer.issued.lock().unwrap().is_empty());
}

#[test]
fn issuance_has_bounded_capacity_and_does_not_evict_live_receipts() {
    let issuer = ContextPlanIssuer::default();
    let first = issuer.issue(planned(context("first"))).unwrap();
    for index in 1..MAX_ISSUED_CONTEXTS {
        issuer.issue(planned(context(&index.to_string()))).unwrap();
    }
    assert!(issuer.issue(planned(context("overflow"))).is_err());
    issuer.validate("owner", 1, &first).unwrap();
    let receipt = receipt_digest(&first).unwrap();
    issuer
        .issued
        .lock()
        .unwrap()
        .get_mut(&receipt)
        .unwrap()
        .deadline = Instant::now() - Duration::from_secs(1);
    issuer.issue(planned(context("after-expiry"))).unwrap();
    assert_eq!(issuer.issued.lock().unwrap().len(), MAX_ISSUED_CONTEXTS);
}

#[test]
fn complete_json_budget_includes_content_escaping_and_plan_fields() {
    let issuer = ContextPlanIssuer::default();
    let snapshot = issuer.issue(planned(context("bounded"))).unwrap();
    let mut oversized = snapshot.clone();
    oversized.items[0].content = "x".repeat(32 * 1024);
    assert!(ContextEnvelope::from(&oversized).digest().is_err());
    assert!(issuer.validate("owner", 1, &oversized).is_err());
    assert!(issuer.issue(planned(oversized)).is_err());
    let mut escaped = snapshot;
    escaped.items[0].content = "\n".repeat(crate::MAX_COGNITIVE_CONTEXT_BYTES / 2);
    assert!(ContextEnvelope::from(&escaped).digest().is_err());
}
