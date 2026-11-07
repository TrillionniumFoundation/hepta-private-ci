//! Two real selected task replacements, including the cold terminal boundary.
//! This uses ordinary Fleet/service assembly with an explicit synthetic worker.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationReceiptV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::super::support as host;
use super::support;
use crate::AgentdError;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::AgentdGenerationUpdateRuntimeV1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::RECORDS;
use crate::prepare_agentd_generation_cold_update_v1;
use crate::prepare_agentd_generation_update_v1;
use crate::recover_agentd_generation_update_v1;

#[tokio::test]
async fn cold_takeover_rejects_real_stopped_drained_but_unacknowledged_output() -> anyhow::Result<()>
{
    let host = host::Fixture::new().await;
    let update = Fixture::new(host.config)?;
    let mut old = update.old_journal()?;
    let request = support::request(&update.old_config, old.snapshot()?.clone());
    old.admit(request.clone(), /*now_micros*/ 20)?;
    let mut control = support::Control::default();
    let proposal = control.execute_generation(&update.old_config.manifest, &request)?;
    old.commit(proposal, /*now_micros*/ 21)?;
    old.drain()?;
    assert!(old.snapshot()?.stopped);
    assert!(!old.is_drained()?);
    let chunk = old
        .pending_output()?
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("missing real unacknowledged output"))?;
    drop(old);
    let before = (
        update.bytes("old-journal")?,
        update.bytes("old-witness")?,
        update.bytes("current.json")?,
    );
    let result = prepare_agentd_generation_cold_update_v1(
        update.current.clone(),
        update.authorities()?,
        AgentdGenerationUpdatePredecessorFilesV1 {
            file: update.file("old-journal")?,
            witness: update.witness("old-witness", &update.old_config)?,
            config: update.old_config.clone(),
            max_records: RECORDS,
        },
        update.selection()?,
        update.target_create()?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "unacknowledged-cold-update".into(),
        },
    );
    assert!(
        matches!(result, Err(AgentdError::Invalid(ref reason)) if reason == "cold predecessor requires STOP, exact output ACK and drain")
    );
    assert_eq!(
        (
            update.bytes("old-journal")?,
            update.bytes("old-witness")?,
            update.bytes("current.json")?
        ),
        before
    );
    assert!(update.bytes("target-journal")?.is_empty());
    assert_eq!(update.authority.capacity()?.used_nonces, 0);
    assert_eq!(update.old_journal()?.pending_output()?, Some(&chunk));
    Ok(())
}

#[tokio::test]
async fn successive_selected_tasks_require_closed_terminal_takeover_after_current_advances()
-> anyhow::Result<()> {
    let mut host = host::Fixture::new().await;
    let update = Fixture::new(host.config.clone())?;
    let old = update.stopped_old()?;
    let initial_bytes = (update.bytes("old-journal")?, update.bytes("old-witness")?);
    let prepared = prepare_agentd_generation_update_v1(
        update.current.clone(),
        update.authorities()?,
        old,
        update.selection()?,
        update.target_create()?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "first-selected-update".into(),
        },
    )?;
    let first_intent = prepared.intent_digest();
    let signed = update.sign(prepared.final_use_binding())?;
    let ready = prepared.publish(&signed)?;
    let control = support::Control::default();
    let mut runtime = ready.into_runtime(
        support::next_config(&mut host, 2).await?,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _first_lifetime) = support::start(&mut runtime, &host)?;
    let first_receipt = stop_ack_drain(
        &runtime,
        &update.target_config,
        &host.directory.path().join("first-selected-output"),
    )
    .await?;
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    let first_bytes = (
        update.bytes("target-journal")?,
        update.bytes("target-witness")?,
    );
    tasks.shutdown().await;
    drop(tasks);
    let AgentdGenerationUpdateRuntimeV1 {
        config: old_host_config,
        handle,
        ..
    } = runtime;
    drop(handle);

    // Reconstruct the installed live owner while its selection is still valid.
    // It remains closed: no new RuntimeTasks service has been started.
    let old_live = recover_agentd_generation_update_v1(
        update.reopen_current()?,
        update.authorities()?,
        update.selection()?,
        update.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: "first-selected-update".into(),
            intent_digest: first_intent,
        },
    )?;
    let mut next = update.target_config.clone();
    next.initial.scope.run_id.push_str("-third-task");
    next.initial.generation += 1;
    next.initial.writer_epoch += 1;
    next.task_digest = Digest32::of_parts(&[b"third-task", &next.task_digest]).into_array();
    next.manifest.bundle_digest =
        Digest32::of_parts(&[b"third-bundle", &next.manifest.bundle_digest]).into_array();
    next.initial.manifest_digest = next.manifest.digest()?;
    let selected = update.publish_next_selection(&next.manifest, "third-task-candidate")?;

    // The actual new CURRENT invalidates the old live selection. This rejects
    // in the ordinary channel's snapshot check, before any worker or service.
    let old_start = old_live.into_runtime(
        old_host_config,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    );
    assert!(matches!(old_start, Err(AgentdError::Invalid(ref reason)) if reason == "Unavailable"));
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    assert_eq!(
        (
            update.bytes("target-journal")?,
            update.bytes("target-witness")?
        ),
        first_bytes
    );

    // Only the closed cold entry can now take those exact terminal files under
    // the concrete Control floor. It never returns an old active journal.
    let prepared = prepare_agentd_generation_cold_update_v1(
        update.reopen_current()?,
        update.authorities()?,
        AgentdGenerationUpdatePredecessorFilesV1 {
            file: update.file("target-journal")?,
            witness: update.witness("target-witness", &update.target_config)?,
            config: update.target_config.clone(),
            max_records: RECORDS,
        },
        selected,
        update.named_target_create("third-journal", "third-witness", next.clone())?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "second-selected-update".into(),
        },
    )?;
    assert_ne!(prepared.intent_digest(), first_intent);
    let next_signed = update.sign(prepared.final_use_binding())?;
    assert_ne!(next_signed.grant.nonce, signed.grant.nonce);
    let ready = prepared.publish(&next_signed)?;
    assert_eq!(update.authority.capacity()?.used_nonces, 2);
    assert_eq!(
        (
            update.bytes("target-journal")?,
            update.bytes("target-witness")?
        ),
        first_bytes
    );
    let mut runtime = ready.into_runtime(
        support::next_config(&mut host, 6).await?,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _second_lifetime) = support::start(&mut runtime, &host)?;
    let second_receipt = stop_ack_drain(
        &runtime,
        &next,
        &host.directory.path().join("second-selected-output"),
    )
    .await?;
    assert_ne!(second_receipt.request_digest, first_receipt.request_digest);
    assert_ne!(
        second_receipt.cost.identity().task_digest,
        first_receipt.cost.identity().task_digest
    );
    assert_eq!(control.executions.load(Ordering::SeqCst), 2);
    assert_eq!(control.reads.load(Ordering::SeqCst), 0);
    tasks.shutdown().await;
    drop(runtime);
    drop(tasks);

    let current = update.reopen_current()?;
    assert_eq!(
        CellGenerationJournalV2::open_guarded(
            update.file("target-journal")?,
            update.witness("target-witness", &update.target_config)?,
            update.target_config.clone(),
            RECORDS,
            current,
        )
        .err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(
        (
            update.bytes("target-journal")?,
            update.bytes("target-witness")?
        ),
        first_bytes
    );
    assert_eq!(
        (update.bytes("old-journal")?, update.bytes("old-witness")?),
        initial_bytes
    );
    assert_eq!(update.authority.capacity()?.used_nonces, 2);
    Ok(())
}

async fn stop_ack_drain(
    runtime: &AgentdGenerationUpdateRuntimeV1,
    config: &CellGenerationConfigV2,
    destination: &Path,
) -> anyhow::Result<CellGenerationReceiptV2> {
    let snapshot = runtime.handle.snapshot().await?;
    assert_eq!(snapshot, config.initial);
    assert!(snapshot.prefix.is_empty());
    let mut request = support::request(config, snapshot);
    request.operation_id = format!("stop-{}", config.initial.scope.run_id);
    let receipt = runtime.handle.step(request.clone()).await?;
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Stopped);
    assert_eq!(runtime.handle.step(request).await?, receipt);
    let observation = runtime.handle.observe_generation().await?;
    assert!(observation.snapshot().stopped);
    assert!(!observation.is_terminal());
    let chunk = observation
        .pending_output()
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("missing stopped outbox"))?;
    assert_eq!(chunk.bytes, support::OUTPUT);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(destination)?;
    file.write_all(&chunk.bytes)?;
    file.sync_all()?;
    File::open(
        destination
            .parent()
            .ok_or_else(|| anyhow::anyhow!("receiver directory"))?,
    )?
    .sync_all()?;
    runtime
        .handle
        .acknowledge(
            chunk.clone(),
            Digest32::of_parts(&[b"actual-fixture-delivery", &chunk.bytes]).into_array(),
            CellTaskCostV2::new(observation.cost().identity())?,
        )
        .await?;
    assert!(runtime.handle.drain().await?);
    assert!(runtime.handle.observe_generation().await?.is_terminal());
    Ok(receipt)
}
