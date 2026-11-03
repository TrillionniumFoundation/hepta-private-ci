//! Original immutable operation-ledger evidence for interrupted preparation.

use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn waiting_operation_rechecks_its_owner_under_the_original_writer_lease() -> FixtureResult<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    let proof = fixture.writer.observe_unused_scope(&scope).await?;
    let current = Arc::new(AtomicBool::new(true));
    let checks = Arc::new(AtomicUsize::new(0));
    let payload = "{\"request\":\"original checked admission\"}";
    let operation = OperationIntentV1::new(
        StableId::new("original-checked-admission")?, StableId::new(fixture.writer.owner_agent_id().as_str())?,
        StableId::new("destination:fixture:model")?, Digest32::of_bytes(payload.as_bytes()),
        Digest32::of_bytes(b"fixture scope"), Generation::new(1)?, None,
    )?;
    let allowed = current.clone();
    let observed_checks = checks.clone();
    let mut admission = Box::pin(fixture.writer.prepare_operation_checked(operation, "native.model", payload, move || {
        observed_checks.fetch_add(1, Ordering::SeqCst);
        if !allowed.load(Ordering::SeqCst) {
            return Err(ProductionWriterError::AuthorityRejected("original execution revision was replaced".to_owned()));
        }
        Ok(())
    }));
    assert!(tokio::time::timeout(std::time::Duration::from_millis(25), &mut admission).await.is_err());
    assert_eq!(checks.load(Ordering::SeqCst), 0, "the check belongs after the retained writer fence");
    current.store(false, Ordering::SeqCst);
    drop(proof);
    let result = tokio::time::timeout(std::time::Duration::from_secs(2), admission).await?;
    assert!(result.is_err(), "a queued caller cannot retain its earlier owner observation");
    assert_eq!(checks.load(Ordering::SeqCst), 1);
    drop(fixture.writer.observe_unused_scope(&scope).await?);
    assert_eq!(fixture.final_use.capacity()?.used_nonces, 0);
    Ok(())
}

#[tokio::test]
async fn unused_scope_is_bound_to_the_same_live_writer_and_rejects_every_admitted_state() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    let other_scope = Sha256Digest::for_bytes(b"another fixture scope");
    let proof = fixture.writer.observe_unused_scope(&scope).await.expect("scope has never admitted an operation");
    proof.verify_binding(&fixture.writer, &scope).expect("exact original writer");
    proof.verify_binding(&fixture.writer.clone(), &scope).expect("clone retains the original owner instance");
    assert!(proof.verify_binding(&fixture.writer, &other_scope).is_err());
    let second = Fixture::new().await.expect("effect entry fixture");
    assert_eq!(second.writer.owner_agent_id(), fixture.writer.owner_agent_id());
    assert_eq!(second.writer.lease_id(), fixture.writer.lease_id());
    assert!(proof.verify_binding(&second.writer, &scope).is_err(),
        "the same agent/lease names in another store are not the original live owner");
    drop(proof);

    let (queued, binding) = fixture.queued("scope-proof-original-operation").await.expect("original operation fixture");
    assert!(fixture.writer.observe_unused_scope(&scope).await.is_err(),
        "queued alone already disproves never-admitted, even before a FinalUse grant");
    let signed = fixture.grant(&binding, "scope-proof-original-grant").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued,
    ).await.expect("original entry claim");
    assert!(tokio::time::timeout(std::time::Duration::from_millis(25),
        fixture.writer.observe_unused_scope(&scope)).await.is_err(),
        "a pending original entry retains its existing read permit");
    let currentness = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    let entered = entry.revalidate().await.expect("current original writer")
        .enter(&currentness).expect("original one-shot entry");
    assert!(tokio::time::timeout(std::time::Duration::from_millis(25),
        fixture.writer.observe_unused_scope(&scope)).await.is_err(),
        "an entered original effect still excludes preparation recovery");
    drop(entered);
    assert!(fixture.writer.observe_unused_scope(&scope).await.is_err(),
        "after physical entry releases its guard the immutable row still rejects recovery");
    fixture.writer.settle_effect_entry(observation, super::super::super::ProductionTargetOutcome::Committed {
        receipt: "scope-proof-original-terminal".to_owned(),
    }).await.expect("original terminal settlement");
    assert!(fixture.writer.observe_unused_scope(&scope).await.is_err(),
        "terminal immutable rows still forbid restarting preparation");
    drop(fixture.writer.observe_unused_scope(&other_scope).await.expect("unrelated scope stays independent"));

    let Fixture { _temp, writer, live, final_use: _, issuer: _ } = fixture;
    let store = writer.store.clone();
    let authority = writer.authority().clone();
    let lease_id = writer.lease_id().to_owned();
    writer.release().await.expect("original terminal lease can close");
    drop(writer);
    // A real lease generation transition requires fresh externally verified
    // authority material. Reusing the prior fencing token must stay rejected.
    let successor_authority = ProductionAuthorityLease::from_verified_parts(
        authority.agent_id.clone(),
        Sha256Digest::for_bytes(b"fixture next effect-entry authority"),
        authority.authority_epoch + 1,
        authority.owner_epoch + 1,
        authority.lease_expires_at_unix_seconds,
        ProductionAuthorityToken::from_verified_bytes(b"fixture-next-token".to_vec())
            .expect("distinct fixture successor token"),
    ).expect("independent fixture successor authority");
    let successor = ProductionDurableWriter::open_with_live_verifier(
        store, successor_authority, Arc::new(FixtureVerifier(live)), lease_id, /*generation*/ 2,
    ).await.expect("original owner's next lease generation");
    assert!(successor.observe_unused_scope(&scope).await.is_err(),
        "the same immutable lease history survives a real generation change");
    drop(successor.observe_unused_scope(&other_scope).await.expect("unrelated scope in successor generation"));
}

#[tokio::test]
async fn unused_scope_fence_excludes_concurrent_original_operation_admission() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    let proof = fixture.writer.observe_unused_scope(&scope).await.expect("unused original scope");
    let mut admission = Box::pin(fixture.queued("scope-proof-concurrent-operation"));
    assert!(tokio::time::timeout(std::time::Duration::from_millis(25),
        &mut admission).await.is_err(),
        "the original operation admission cannot pass the retained preparation fence");
    proof.verify_binding(&fixture.writer, &scope).expect("same original scope remains fenced");
    let admitted: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_operation_ledger WHERE lease_id = ? AND owner_agent_id = ? AND scope_sha256 = ?",
    ).bind(fixture.writer.lease_id()).bind(fixture.writer.owner_agent_id().as_str())
        .bind(scope.as_str()).fetch_one(&fixture.writer.store.pool).await.expect("original ledger read");
    assert_eq!(admitted, 0, "the same writer has not registered the pending operation");
    drop(proof);
    tokio::time::timeout(std::time::Duration::from_secs(2), admission).await
        .expect("original operation admission proceeds after preparation releases its guard")
        .expect("original operation fixture");
    assert!(fixture.writer.observe_unused_scope(&scope).await.is_err(),
        "the subsequently durable original operation permanently closes preparation recovery");
}

#[tokio::test]
async fn unused_scope_observation_requires_live_authority_and_cannot_survive_owner_close() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    fixture.live.store(false, Ordering::SeqCst);
    assert!(fixture.writer.observe_unused_scope(&scope).await.is_err());
    fixture.live.store(true, Ordering::SeqCst);
    let proof = fixture.writer.observe_unused_scope(&scope).await.expect("original authority restored");
    fixture.live.store(false, Ordering::SeqCst);
    assert!(proof.verify_binding(&fixture.writer, &scope).is_err(),
        "a retained unused-scope fact cannot outlive revocation of its original owner");
    fixture.live.store(true, Ordering::SeqCst);
    let writer = fixture.writer.clone();
    let release = tokio::spawn(async move { writer.release().await });
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while proof.verify_binding(&fixture.writer, &scope).is_ok() { tokio::task::yield_now().await; }
    }).await.expect("closing the owner invalidates the original proof before release finishes");
    assert!(!release.is_finished(), "the proof retains the existing lease lifetime");
    drop(proof);
    release.await.expect("release task").expect("original lease released");
    assert!(fixture.writer.observe_unused_scope(&scope).await.is_err());
}
