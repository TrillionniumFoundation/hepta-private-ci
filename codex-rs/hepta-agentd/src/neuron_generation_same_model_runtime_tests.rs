//! Ordinary Fleet/service handoff with the same selected model. The control
//! worker is synthetic; real files/signatures exercise ownership and recovery.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::super::support as host;
use super::support;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::neuron_generation_current::NeuronGenerationPredecessorCompletionV1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::RECORDS;
use crate::prepare_agentd_generation_cold_same_model_task_v1;
use crate::recover_agentd_generation_update_v1;

#[tokio::test]
async fn cold_same_model_task_runs_new_input_and_recovers_receipt_without_reexecution()
-> anyhow::Result<()> {
    let mut host = host::Fixture::new().await;
    let mut next = host.config.clone();
    next.initial.scope.run_id.push_str("-same-model");
    next.initial.generation += 1;
    next.initial.writer_epoch += 1;
    next.task_digest = Digest32::of_bytes(b"next real task binding, same model").into_array();
    let f = Fixture::new_with_target(host.config.clone(), next)?;
    assert_eq!(f.old_config.manifest, f.target_config.manifest);
    drop(f.stopped_old()?);
    let old_bytes = (f.bytes("old-journal")?, f.bytes("old-witness")?);
    let selected = f.selection()?;
    let selection = selected.observation().clone();
    let prepared = prepare_agentd_generation_cold_same_model_task_v1(
        f.reopen_current()?,
        f.authorities()?,
        AgentdGenerationUpdatePredecessorFilesV1 {
            file: f.file("old-journal")?,
            witness: f.witness("old-witness", &f.old_config)?,
            config: f.old_config.clone(),
            max_records: RECORDS,
        },
        selected,
        f.target_create()?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "same-model-next-task".into(),
        },
    )?;
    let intent_digest = prepared.intent_digest();
    let signed = f.sign(prepared.final_use_binding())?;
    let ready = prepared.publish(&signed)?;
    let control = support::Control::default();
    let mut runtime = ready.into_runtime(
        support::next_config(&mut host, 2).await?,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    assert_eq!(
        runtime.publication.completion(),
        NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
    );
    let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
    assert_eq!(runtime.handle.snapshot().await?, f.target_config.initial);
    assert!(
        runtime
            .handle
            .step(support::request(
                &f.old_config,
                f.old_config.initial.clone()
            ))
            .await
            .is_err()
    );
    assert_eq!(control.executions.load(Ordering::SeqCst), 0);
    let mut request = support::request(&f.target_config, runtime.handle.snapshot().await?);
    request.input = vec![91, 92, 93];
    let receipt = runtime.handle.step(request.clone()).await?;
    assert_eq!(runtime.handle.step(request.clone()).await?, receipt);
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    let observed = runtime.handle.observe_generation().await?;
    assert_eq!(observed.snapshot().state, request.input);
    let chunk = observed
        .pending_output()
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("new task has no durable output"))?;
    let delivered = host.directory.path().join("same-model-delivery");
    let mut receiver = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&delivered)?;
    receiver.write_all(&chunk.bytes)?;
    receiver.sync_all()?;
    File::open(host.directory.path())?.sync_all()?;
    runtime
        .handle
        .acknowledge(
            chunk.clone(),
            Digest32::of_parts(&[b"same-model-delivery", &chunk.bytes]).into_array(),
            CellTaskCostV2::new(observed.cost().identity())?,
        )
        .await?;
    assert!(runtime.handle.drain().await?);
    let complete = runtime.handle.observe_generation().await?;
    let retained = (
        f.bytes("target-journal")?,
        f.bytes("target-witness")?,
        f.bytes("final-use/authority.claims")?,
    );
    tasks.shutdown().await;
    drop(runtime);
    drop(tasks);

    let ready = recover_agentd_generation_update_v1(
        f.reopen_current()?,
        f.authorities()?,
        f.selection()?,
        f.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: "same-model-next-task".into(),
            intent_digest,
        },
    )?;
    let mut runtime = ready.into_runtime(
        support::next_config(&mut host, 6).await?,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
    assert_eq!(runtime.handle.observe_generation().await?, complete);
    assert_eq!(runtime.handle.step(request).await?, receipt);
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    assert_eq!(control.reads.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(delivered)?, chunk.bytes);
    assert_eq!(f.selection()?.observation(), &selection);
    assert_eq!(f.old_config.manifest, f.target_config.manifest);
    assert_eq!(
        (
            f.bytes("target-journal")?,
            f.bytes("target-witness")?,
            f.bytes("final-use/authority.claims")?
        ),
        retained
    );
    assert_eq!(
        (f.bytes("old-journal")?, f.bytes("old-witness")?),
        old_bytes
    );
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    tasks.shutdown().await;
    drop(runtime);
    drop(tasks);
    assert_eq!(
        CellGenerationJournalV2::open_guarded(
            f.file("old-journal")?,
            f.witness("old-witness", &f.old_config)?,
            f.old_config.clone(),
            RECORDS,
            f.reopen_current()?,
        )
        .err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );

    // Identical model bytes do not make an old selection current after the
    // actual artifact owner advances. Cold recovery must read the live owner.
    let stale = f.selection()?;
    f.advance_artifact_current()?;
    assert!(
        recover_agentd_generation_update_v1(
            f.reopen_current()?,
            f.authorities()?,
            stale,
            f.target_reopen()?,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: "same-model-next-task".into(),
                intent_digest
            },
        )
        .is_err()
    );
    assert_eq!(
        (
            f.bytes("target-journal")?,
            f.bytes("target-witness")?,
            f.bytes("final-use/authority.claims")?
        ),
        retained
    );
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    Ok(())
}
