use super::*;
use anyhow::Context as _;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn cold_revocation_blocks_existing_checkpoint_adoption_v2() -> anyhow::Result<()> {
    let mut f = UpdatedRuntime::new().await?;
    let baseline = f.publication.old_config.manifest.clone();
    let operation = learning_updated_task_operation_id_v1(&f.coordinator)?.to_string();
    let (mut tasks, lifetime) = support::start(&mut f.runtime, &f.host)?;
    f.coordinator.record(
        learning_test_receipt(&f.coordinator, f.selection.clone()),
        20,
    )?;
    let request = support::request(
        &f.publication.target_config,
        f.runtime.handle.snapshot().await?,
    );
    let intent = request.intent()?;
    let receipt = f.runtime.handle.step(request.clone()).await?;
    let observed = f.runtime.handle.observe_generation().await?;
    let chunk = observed
        .pending_output()
        .cloned()
        .context("expected output before acknowledgement")?;
    // Retain exact delivered bytes before the ordinary acknowledgement.
    let sink = f.host.directory.path().join("adoption-v2-delivery");
    std::fs::write(&sink, &chunk.bytes)?;
    std::fs::File::open(&sink)?.sync_all()?;
    f.runtime
        .handle
        .acknowledge(
            chunk.clone(),
            Digest32::of_bytes(&chunk.bytes).into_array(),
            CellTaskCostV2::new(observed.cost().identity())?,
        )
        .await?;
    assert!(f.runtime.handle.drain().await?);
    let hot = f
        .runtime
        .handle
        .read_learning_updated_next_use_readback(&f.coordinator, &baseline, &intent)
        .await?;
    let retained = (
        f.publication.bytes("current.json")?,
        f.publication.bytes("target-journal")?,
        f.publication.bytes("target-witness")?,
        f.publication.bytes("final-use/authority.claims")?,
    );
    let intent_digest = f.runtime.publication.intent_digest();
    let grant_id = f.runtime.publication.signed_grant().grant.grant_id.clone();
    tasks.shutdown().await;
    drop(tasks);
    drop(lifetime);
    drop(f.runtime);

    let reopen = || -> anyhow::Result<_> {
        Ok(recover_agentd_generation_update_v1(
            f.publication.reopen_current()?,
            f.publication.authorities()?,
            f.publication.selection()?,
            f.publication.target_reopen()?,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: operation.clone(),
                intent_digest,
            },
        )?)
    };
    let ready = reopen()?;
    f.runtime = ready.into_runtime(
        support::next_config(&mut f.host, 6).await?,
        f.control.clone(),
        f.host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
    let cold = f
        .runtime
        .handle
        .read_learning_updated_next_use_readback(&f.coordinator, &baseline, &intent)
        .await?;
    assert_eq!(cold, hot);
    assert_eq!(f.runtime.handle.step(request.clone()).await?, receipt);
    assert_eq!(f.control.executions.load(Ordering::SeqCst), 1);
    assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);

    // A live revocation survives the cold reopen. It must not be undone to
    // make a previously consumed grant appear usable again.
    let mut revocation = f.publication.authority.revocation_head()?;
    revocation.revision += 1;
    revocation.revoked_grant_ids.insert(grant_id);
    f.publication.authority.update_revocations(revocation)?;
    let denied = f
        .runtime
        .handle
        .read_learning_updated_next_use_readback(&f.coordinator, &baseline, &intent)
        .await;
    assert!(denied.is_err());
    // A journal lookup may return the immutable old receipt before checking
    // current admission. That is a read, not a new inference authorization.
    if let Ok(replayed) = f.runtime.handle.step(request).await {
        assert_eq!(replayed, receipt);
    }
    let executions = f.control.executions.load(Ordering::SeqCst);
    assert_eq!(executions, 1);
    assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
    assert_eq!(std::fs::read(sink)?, chunk.bytes);
    assert_eq!(
        (
            f.publication.bytes("current.json")?,
            f.publication.bytes("target-journal")?,
            f.publication.bytes("target-witness")?,
            f.publication.bytes("final-use/authority.claims")?,
        ),
        retained
    );
    tasks.shutdown().await;
    drop(tasks);
    drop(f.runtime);
    let after_revocation = reopen();
    assert!(after_revocation.is_err());
    Ok(())
}
