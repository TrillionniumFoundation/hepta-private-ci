//! The original production writer, real SQLite ledgers and real claim transitions.
use super::*;
use crate::{LocalReconcileOutcome, ProductionDispatchReceipt, ProductionScopeClaimState, ProductionTargetOutcome};
use pretty_assertions::assert_eq;

async fn complete_original(fixture: &Fixture, operation_id: &str, receipt: &str)
    -> FixtureResult<ProductionDispatchReceipt> {
    let (queued, binding) = fixture.queued(operation_id).await?;
    let signed = fixture.grant(&binding, &format!("grant:{operation_id}"))?;
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued,
    ).await?;
    let current = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    let entered = entry.revalidate().await?.enter(&current)?;
    drop(entered);
    Ok(fixture.writer.settle_effect_entry(observation,
        ProductionTargetOutcome::Committed { receipt: receipt.to_owned() }).await?)
}

#[tokio::test]
async fn frontier_keeps_every_original_state_and_excludes_new_operation_admission() -> FixtureResult<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    let (queued, _) = fixture.queued("frontier:queued").await?;
    let queued_request = fixture.writer.resolve_operation_request(&queued.occurrence_key, "destination:fixture:model").await?;
    let terminal = complete_original(&fixture, "frontier:terminal", "原始终结凭据").await?;
    let frontier = fixture.writer.observe_scope_frontier(&scope).await?;
    frontier.verify_binding(&fixture.writer.clone(), &scope)?;
    assert_eq!(frontier.records().len(), 2);
    let queued = frontier.records().iter().find(|row| row.request().occurrence_key == "frontier:queued")
        .ok_or("queued original row missing")?;
    assert_eq!(queued.request(), &queued_request);
    assert_eq!(queued.state(), LocalOutcomeState::Queued);
    assert!(queued.terminal_receipt().is_none());
    assert!(queued.claims().is_empty());
    let completed = frontier.records().iter().find(|row| row.request().occurrence_key == "frontier:terminal")
        .ok_or("terminal original row missing")?;
    assert_eq!(completed.request(), &terminal.request);
    assert_eq!(completed.terminal_event_id(), Some(terminal.local_event_id.as_str()));
    assert_eq!(completed.terminal_receipt(), Some("原始终结凭据"));
    assert_eq!(completed.state(), LocalOutcomeState::Committed);
    assert_eq!(completed.claims().iter().map(|claim| claim.state()).collect::<Vec<_>>(),
        vec![ProductionScopeClaimState::Claimed, ProductionScopeClaimState::Entered, ProductionScopeClaimState::Settled]);
    let mut next = Box::pin(fixture.queued("frontier:next"));
    assert!(tokio::time::timeout(std::time::Duration::from_millis(25), &mut next).await.is_err());
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_operation_ledger WHERE lease_id = ?")
        .bind(fixture.writer.lease_id()).fetch_one(&fixture.writer.store.pool).await?;
    assert_eq!(count, 2);
    frontier.verify_binding(&fixture.writer, &scope)?;
    drop(frontier);
    tokio::time::timeout(std::time::Duration::from_secs(2), next).await??;
    let frontier = fixture.writer.observe_scope_frontier(&scope).await?;
    assert_eq!(frontier.records().len(), 3);
    Ok(())
}

#[tokio::test]
async fn committed_terminal_event_does_not_fabricate_a_settled_dispatch_claim() -> FixtureResult<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    let (queued, binding) = fixture.queued("frontier:terminal-ack-gap").await?;
    let signed = fixture.grant(&binding, "grant:terminal-ack-gap")?;
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued,
    ).await?;
    let current = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    let entered = entry.revalidate().await?.enter(&current)?;
    drop(entered);
    // The real first settlement commit, before the separate original claim
    // settlement commit. No SQL row is edited and no terminal receipt is invented.
    let original = fixture.writer.lease.reconcile_with_terminal_receipt(
        "frontier:terminal-ack-gap", LocalReconcileOutcome::Committed, "fixture terminal observed output",
    ).await?;
    let frontier = fixture.writer.observe_scope_frontier(&scope).await?;
    let row = frontier.records().first().ok_or("original operation missing")?;
    assert_eq!(row.state(), LocalOutcomeState::Committed);
    assert_eq!(row.terminal_event_id(), Some(original.event_id.as_str()));
    assert_eq!(row.terminal_receipt(), Some("fixture terminal observed output"));
    assert_eq!(row.claims().last().ok_or("original claim missing")?.state(), ProductionScopeClaimState::Entered);
    drop(frontier);
    crate::operation_claims::settle_reconciled(&fixture.writer.store, "frontier:terminal-ack-gap",
        fixture.writer.generation(), fixture.writer.lease.fencing_token(), now_unix_ms()?).await?;
    drop(observation);
    let frontier = fixture.writer.observe_scope_frontier(&scope).await?;
    assert_eq!(frontier.records()[0].claims().last().ok_or("settled claim missing")?.state(), ProductionScopeClaimState::Settled);
    Ok(())
}

#[tokio::test]
async fn frontier_rejects_corrupt_claim_chain_instead_of_trusting_its_latest_state() -> FixtureResult<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    complete_original(&fixture, "frontier:damaged", "fixture terminal").await?;
    drop(fixture.writer.observe_scope_frontier(&scope).await?);
    // Deliberate storage damage in this fixture bypasses its immutable trigger.
    sqlx::query("DROP TRIGGER cognitive_operation_dispatch_claims_no_update")
        .execute(&fixture.writer.store.pool).await?;
    sqlx::query("UPDATE cognitive_operation_dispatch_claims SET previous_sha256 = ? WHERE operation_id = ? AND claim_sequence = 2")
        .bind(Sha256Digest::for_bytes(b"not the original predecessor").as_str())
        .bind("frontier:damaged").execute(&fixture.writer.store.pool).await?;
    assert!(fixture.writer.observe_scope_frontier(&scope).await.is_err());
    Ok(())
}

#[tokio::test]
async fn frontier_is_bound_to_original_writer_scope_and_live_authority() -> FixtureResult<()> {
    let fixture = Fixture::new().await?;
    let other = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    let frontier = fixture.writer.observe_scope_frontier(&scope).await?;
    assert!(frontier.verify_binding(&other.writer, &scope).is_err());
    assert!(frontier.verify_binding(&fixture.writer, &Sha256Digest::for_bytes(b"another scope")).is_err());
    fixture.live.store(false, Ordering::SeqCst);
    assert!(frontier.verify_binding(&fixture.writer, &scope).is_err());
    fixture.live.store(true, Ordering::SeqCst);
    let writer = fixture.writer.clone();
    let release = tokio::spawn(async move { writer.release().await });
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while frontier.verify_binding(&fixture.writer, &scope).is_ok() { tokio::task::yield_now().await; }
    }).await?;
    assert!(!release.is_finished());
    drop(frontier);
    release.await??;
    assert!(fixture.writer.observe_scope_frontier(&scope).await.is_err());
    Ok(())
}

#[tokio::test]
async fn frontier_does_not_hide_old_generation_operations_under_a_new_grant() -> FixtureResult<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    complete_original(&fixture, "frontier:old-generation", "fixture terminal").await?;
    let Fixture { _temp, writer, live, final_use: _, issuer: _ } = fixture;
    let store = writer.store.clone();
    let authority = writer.authority().clone();
    let lease_id = writer.lease_id().to_owned();
    writer.release().await?;
    drop(writer);
    let next_authority = ProductionAuthorityLease::from_verified_parts(
        authority.agent_id.clone(), Sha256Digest::for_bytes(b"fixture frontier next authority"),
        authority.authority_epoch + 1, authority.owner_epoch + 1, authority.lease_expires_at_unix_seconds,
        ProductionAuthorityToken::from_verified_bytes(b"fixture-frontier-next-token".to_vec())?,
    )?;
    let next = ProductionDurableWriter::open_with_live_verifier(
        store, next_authority, Arc::new(FixtureVerifier(live)), lease_id, 2,
    ).await?;
    assert!(next.observe_scope_frontier(&scope).await.is_err());
    assert!(next.observe_scope_frontier(&Sha256Digest::for_bytes(b"independent scope")).await?.records().is_empty());
    Ok(())
}

#[tokio::test]
async fn frontier_preserves_real_renewed_and_entered_claim_states() -> FixtureResult<()> {
    let fixture = Fixture::new().await?;
    let scope = Sha256Digest::for_bytes(b"fixture scope");
    let (queued, binding) = fixture.queued("frontier:renewed").await?;
    let claim = fixture.writer.claim_dispatch_lease(&queued, 10000).await?;
    let renewed = fixture.writer.renew_dispatch_claim(&claim, 20000).await?;
    let frontier = fixture.writer.observe_scope_frontier(&scope).await?;
    let row = frontier.records().first().ok_or("renewed operation missing")?;
    assert_eq!(row.state(), LocalOutcomeState::Queued);
    assert_eq!(row.claims().last().ok_or("renewed claim missing")?.receipt(), &renewed);
    assert_eq!(row.claims().last().ok_or("renewed claim missing")?.state(), ProductionScopeClaimState::Renewed);
    drop(frontier);
    let signed = fixture.grant(&binding, "grant:renewed")?;
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued,
    ).await?;
    drop(entry);
    drop(observation);
    let frontier = fixture.writer.observe_scope_frontier(&scope).await?;
    let row = frontier.records().first().ok_or("entered operation missing")?;
    assert_eq!(row.state(), LocalOutcomeState::Indeterminate);
    assert_eq!(row.claims().iter().map(|claim| claim.state()).collect::<Vec<_>>(),
        vec![ProductionScopeClaimState::Claimed, ProductionScopeClaimState::Renewed, ProductionScopeClaimState::Entered]);
    assert!(row.terminal_receipt().is_none());
    Ok(())
}

#[tokio::test]
async fn frontier_is_reconstructed_from_original_store_after_all_writer_handles_close() -> FixtureResult<()> {
    let fixture = Fixture::new().await?;
    let terminal = complete_original(&fixture, "frontier:cold", "fixture cold terminal").await?;
    let Fixture { _temp, writer, live, final_use: _, issuer: _ } = fixture;
    let authority = writer.authority().clone();
    let agent = writer.owner_agent_id().clone();
    let lease_id = writer.lease_id().to_owned();
    // Simulate handle loss, not a durable release or a new generation. This
    // is a real store reopen; an OS-process kill is a separate integration test.
    drop(writer);
    let fleet = HeptaFleetRoot::parse(_temp.path().join("fleet").canonicalize()?)?;
    let store = CognitiveStore::open(&fleet.layout().agent(&agent)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store, authority, Arc::new(FixtureVerifier(live)), lease_id, 1,
    ).await?;
    let frontier = writer.observe_scope_frontier(&Sha256Digest::for_bytes(b"fixture scope")).await?;
    assert_eq!(frontier.records().len(), 1);
    assert_eq!(frontier.records()[0].request(), &terminal.request);
    assert_eq!(frontier.records()[0].terminal_event_id(), Some(terminal.local_event_id.as_str()));
    assert_eq!(frontier.records()[0].terminal_receipt(), Some("fixture cold terminal"));
    assert_eq!(frontier.records()[0].claims().last().ok_or("original settled claim missing")?.state(), ProductionScopeClaimState::Settled);
    Ok(())
}
