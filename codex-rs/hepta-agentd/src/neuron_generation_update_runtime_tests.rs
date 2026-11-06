//! Updated generations use the existing Fleet/config/service path. The worker
//! is explicitly synthetic; CURRENT, signatures, nonce state and journals are
//! real file owners supplied by the shared fixture.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::support as host;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::prepare_agentd_generation_update_v1;
use crate::recover_agentd_generation_update_v1;

#[path = "neuron_generation_same_model_runtime_tests.rs"]
mod same_model;
#[path = "neuron_generation_update_successive_tests.rs"]
mod successive;
#[path = "neuron_generation_update_runtime_support.rs"]
mod support;

#[tokio::test]
async fn normal_runtime_reset_and_journal_reopen_keep_original_receipt() -> anyhow::Result<()> {
    let mut host = host::Fixture::new().await;
    let update = Fixture::new(host.config.clone())?;
    let old = update.stopped_old()?;
    let old_prefix = old.snapshot()?.prefix.clone();
    let old_bytes = (update.bytes("old-journal")?, update.bytes("old-witness")?);
    let prepared = prepare_agentd_generation_update_v1(
        update.current.clone(),
        update.authorities()?,
        old,
        update.selection()?,
        update.target_create()?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "runtime-replace".into(),
        },
    )?;
    let intent_digest = prepared.intent_digest();
    let grant = update.sign(prepared.final_use_binding())?;
    let ready = prepared.publish(&grant)?;
    assert_eq!(
        (update.bytes("old-journal")?, update.bytes("old-witness")?),
        old_bytes
    );

    let config = support::next_config(&mut host, 2).await?;
    let control = support::Control::default();
    let mut runtime = ready.into_runtime(
        config,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    assert_eq!(runtime.publication.authority(), AuthorityPosture::DENY_ALL);
    let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
    let initial = runtime.handle.snapshot().await?;
    assert_eq!(initial, update.target_config.initial);
    assert!(initial.prefix.is_empty());
    assert!(!old_prefix.is_empty());

    let request = support::request(&update.target_config, initial);
    let receipt = runtime.handle.step(request.clone()).await?;
    let undelivered = runtime.handle.observe_generation().await?;
    assert!(undelivered.snapshot().stopped);
    assert!(!undelivered.is_terminal());
    assert_eq!(undelivered.snapshot().prefix, support::OUTPUT);
    assert_eq!(runtime.handle.step(request.clone()).await?, receipt);
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    let chunk = undelivered
        .pending_output()
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("stopped successor has no real outbox"))?;
    let path = host.directory.path().join("delivered-updated-task");
    let mut receiver = OpenOptions::new().create_new(true).write(true).open(path)?;
    receiver.write_all(&chunk.bytes)?;
    receiver.sync_all()?;
    File::open(host.directory.path())?.sync_all()?;
    runtime
        .handle
        .acknowledge(
            chunk.clone(),
            Digest32::of_parts(&[b"test-receiver-synced", &chunk.bytes]).into_array(),
            CellTaskCostV2::new(undelivered.cost().identity())?,
        )
        .await?;
    assert!(runtime.handle.observe_generation().await?.is_terminal());
    assert!(runtime.handle.drain().await?);
    let observed = runtime.handle.observe_generation().await?;
    let retained = (
        update.bytes("target-journal")?,
        update.bytes("target-witness")?,
    );
    let final_use = update.authority.current_external_frontier()?;
    tasks.shutdown().await;
    drop(runtime);
    drop(tasks);

    let recovered = recover_agentd_generation_update_v1(
        update.reopen_current()?,
        update.authorities()?,
        update.selection()?,
        update.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: "runtime-replace".into(),
            intent_digest,
        },
    )?;
    let config = support::next_config(&mut host, 6).await?;
    let mut runtime = recovered.into_runtime(
        config,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
    assert_eq!(runtime.handle.observe_generation().await?, observed);
    assert_eq!(runtime.handle.step(request).await?, receipt);
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    assert_eq!(control.reads.load(Ordering::SeqCst), 0);
    assert_eq!(
        (
            update.bytes("target-journal")?,
            update.bytes("target-witness")?
        ),
        retained
    );
    assert_eq!(
        (update.bytes("old-journal")?, update.bytes("old-witness")?),
        old_bytes
    );
    assert_eq!(update.authority.current_external_frontier()?, final_use);
    tasks.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn live_current_withdrawal_and_revocation_block_dispatch_and_reopen() -> anyhow::Result<()> {
    for change in ["current", "withdrawal", "revocation"] {
        let mut host = host::Fixture::new().await;
        let update = Fixture::new(host.config.clone())?;
        let prepared = prepare_agentd_generation_update_v1(
            update.current.clone(),
            update.authorities()?,
            update.stopped_old()?,
            update.selection()?,
            update.target_create()?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: "live-guard-update".into(),
            },
        )?;
        let intent_digest = prepared.intent_digest();
        let grant = update.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&grant)?;
        let config = support::next_config(&mut host, 2).await?;
        let control = support::Control::default();
        let mut runtime = ready.into_runtime(
            config,
            control.clone(),
            host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default(),
        )?;
        let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
        let request = support::request(&update.target_config, runtime.handle.snapshot().await?);
        // Retain an actually authenticated selection before the real owner
        // changes. Recovery must not treat that old value as a fresh permit.
        let selected_before = update.selection()?;
        let journal_before = update.bytes("target-journal")?;
        match change {
            "current" => update.advance_artifact_current()?,
            "withdrawal" => update.withdraw()?,
            "revocation" => {
                let mut head = update.authority.revocation_head()?;
                head.revision += 1;
                head.revoked_grant_ids.insert(grant.grant.grant_id.clone());
                update.authority.update_revocations(head)?;
            }
            _ => unreachable!("fixed fixture cases"),
        }
        assert!(runtime.handle.step(request).await.is_err(), "{change}");
        assert_eq!(control.executions.load(Ordering::SeqCst), 0, "{change}");
        assert_eq!(update.bytes("target-journal")?, journal_before, "{change}");
        tasks.shutdown().await;
        drop(runtime);
        drop(tasks);
        assert!(
            recover_agentd_generation_update_v1(
                update.reopen_current()?,
                update.authorities()?,
                selected_before,
                update.target_reopen()?,
                AgentdGenerationUpdateRecoveryV1 {
                    operation_id: "live-guard-update".into(),
                    intent_digest,
                },
            )
            .is_err(),
            "{change}"
        );
        assert_eq!(update.bytes("target-journal")?, journal_before, "{change}");
    }
    Ok(())
}
