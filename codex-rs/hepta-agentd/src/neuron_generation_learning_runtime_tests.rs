//! Real publication, journal and Fleet actor handoff with synthetic learning
//! evidence and worker output. This does not qualify training or Chain use.

use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::super::support as host;
use super::support;
use crate::AgentdError;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::AgentdGenerationUpdateRuntimeV1;
use crate::NeuronGenerationLearningReadErrorV1;
use crate::learning_retained_task_operation_id_v1;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_runtime::verify_learning_use_readback_test_bytes;
use crate::neuron_generation_service::spawn_neuron_generation_service;
use crate::neuron_generation_update_bootstrap::learning_test_baseline;
use crate::neuron_generation_update_bootstrap::learning_test_decision;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;
use crate::prepare_agentd_generation_same_model_task_v1;
use crate::recover_agentd_generation_update_v1;

struct LearningRuntime {
    host: host::Fixture,
    publication: Fixture,
    coordinator: LearningIterationCoordinatorV1,
    runtime: AgentdGenerationUpdateRuntimeV1,
    control: support::Control,
    selection: LearningIterationObservationV1,
}

impl LearningRuntime {
    async fn new() -> anyhow::Result<Self> {
        let mut host = host::Fixture::new().await;
        let baseline = learning_test_baseline()?;
        host.config.manifest.bundle_digest = baseline.digest()?.into_array();
        host.config.initial.manifest_digest = host.config.manifest.digest()?;
        let mut next = host.config.clone();
        next.initial.scope.run_id.push_str("-learning-next");
        next.initial.generation += 1;
        next.initial.writer_epoch += 1;
        next.task_digest = Digest32::of_bytes(b"next learning task").into_array();
        let publication = Fixture::new_with_target(host.config.clone(), next)?;
        let coordinator = learning_test_decision(&publication, baseline, "none")?;
        let prepared = prepare_agentd_generation_same_model_task_v1(
            publication.current.clone(),
            publication.authorities()?,
            publication.stopped_old()?,
            publication.selection()?,
            publication.target_create()?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: learning_retained_task_operation_id_v1(&coordinator)?.to_string(),
            },
        )?;
        let grant = publication.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&grant)?;
        let selection = ready.read_learning_selection(&coordinator)?;
        let control = support::Control::default();
        let runtime = ready.into_runtime(
            support::next_config(&mut host, 2).await?,
            control.clone(),
            host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default(),
        )?;
        Ok(Self {
            host,
            publication,
            coordinator,
            runtime,
            control,
            selection,
        })
    }
}

#[tokio::test]
async fn ordinary_actor_reads_actual_use_and_cold_recovery_without_reexecution()
-> anyhow::Result<()> {
    let mut f = LearningRuntime::new().await?;
    let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
    for change in [
        "principal",
        "agent",
        "cell",
        "run",
        "operation",
        "bundle",
        "decision",
    ] {
        let other = learning_test_decision(
            &f.publication,
            f.coordinator.snapshot().request.selected_bundle.clone(),
            change,
        )?;
        assert!(
            f.runtime
                .handle
                .read_learning_selection(&other)
                .await
                .is_err(),
            "{change}"
        );
    }
    let selection = f
        .runtime
        .handle
        .read_learning_selection(&f.coordinator)
        .await?;
    assert_eq!(selection, f.selection);
    f.coordinator
        .record(learning_test_receipt(&f.coordinator, selection), 20)?;
    let request = support::request(
        &f.publication.target_config,
        f.runtime.handle.snapshot().await?,
    );
    let intent = request.intent()?;
    assert!(matches!(
        f.runtime
            .handle
            .read_learning_next_use(&f.coordinator, &intent)
            .await,
        Err(NeuronGenerationLearningReadErrorV1::Observation(
            AgentdError::Invalid(_)
        ))
    ));
    assert!(
        f.runtime
            .handle
            .read_learning_next_use_readback(&f.coordinator, &intent)
            .await
            .is_err()
    );
    let receipt = f.runtime.handle.step(request.clone()).await?;
    assert!(matches!(
        f.runtime
            .handle
            .read_learning_next_use(&f.coordinator, &intent)
            .await?,
        LearningIterationObservationV1::RetainedModelNextUse { .. }
    ));
    let observed = f.runtime.handle.observe_generation().await?;
    let pending = f
        .runtime
        .handle
        .read_learning_next_use_readback(&f.coordinator, &intent)
        .await?;
    verify_learning_use_readback_test_bytes(
        &pending,
        &f.publication.target_config.manifest,
        &receipt,
        &observed,
        "retained_pending",
    )?;
    let chunk = observed
        .pending_output()
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("missing output"))?;
    let output_path = f.host.directory.path().join("learning-output");
    std::fs::write(&output_path, &chunk.bytes)?;
    std::fs::File::open(&output_path)?.sync_all()?;
    std::fs::File::open(f.host.directory.path())?.sync_all()?;
    f.runtime
        .handle
        .acknowledge(
            chunk.clone(),
            Digest32::of_bytes(&chunk.bytes).into_array(),
            CellTaskCostV2::new(observed.cost().identity())?,
        )
        .await?;
    assert!(f.runtime.handle.drain().await?);
    let first = f
        .runtime
        .handle
        .read_learning_next_use(&f.coordinator, &intent)
        .await?;
    let exported = f
        .runtime
        .handle
        .read_learning_next_use_readback(&f.coordinator, &intent)
        .await?;
    verify_learning_use_readback_test_bytes(
        &exported,
        &f.publication.target_config.manifest,
        &receipt,
        &f.runtime.handle.observe_generation().await?,
        "retained_acked",
    )?;
    assert_ne!(pending, exported);
    let retained = (
        f.publication.bytes("current.json")?,
        f.publication.bytes("target-journal")?,
        f.publication.bytes("target-witness")?,
        f.publication.bytes("final-use/authority.claims")?,
    );
    let intent_digest = f.runtime.publication.intent_digest();
    tasks.shutdown().await;
    drop(f.runtime);
    drop(tasks);
    f.coordinator =
        LearningIterationCoordinatorV1::from_snapshot(f.coordinator.snapshot().clone())?;
    let ready = recover_agentd_generation_update_v1(
        f.publication.reopen_current()?,
        f.publication.authorities()?,
        f.publication.selection()?,
        f.publication.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: learning_retained_task_operation_id_v1(&f.coordinator)?.to_string(),
            intent_digest,
        },
    )?;
    f.runtime = ready.into_runtime(
        support::next_config(&mut f.host, 6).await?,
        f.control.clone(),
        f.host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
    assert_eq!(
        f.runtime
            .handle
            .read_learning_next_use(&f.coordinator, &intent)
            .await?,
        first
    );
    assert_eq!(
        f.runtime
            .handle
            .read_learning_next_use_readback(&f.coordinator, &intent)
            .await?,
        exported
    );
    assert_eq!(f.runtime.handle.step(request).await?, receipt);
    let mut wrong = intent;
    wrong.task_digest = f.publication.old_config.task_digest;
    assert!(
        f.runtime
            .handle
            .read_learning_next_use(&f.coordinator, &wrong)
            .await
            .is_err()
    );
    assert!(
        f.runtime
            .handle
            .read_learning_next_use_readback(&f.coordinator, &wrong)
            .await
            .is_err()
    );
    assert_eq!(
        (
            f.control.executions.load(Ordering::SeqCst),
            f.control.reads.load(Ordering::SeqCst)
        ),
        (1, 0)
    );
    assert_eq!(std::fs::read(output_path)?, chunk.bytes);
    assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
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
    Ok(())
}

#[tokio::test]
async fn running_actor_refuses_current_withdrawal_and_revocation() -> anyhow::Result<()> {
    for phase in ["before_use", "after_use"] {
        for change in ["current", "withdrawal", "revocation"] {
            let mut f = LearningRuntime::new().await?;
            let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
            assert_eq!(
                f.runtime
                    .handle
                    .read_learning_selection(&f.coordinator)
                    .await?,
                f.selection
            );
            let mut use_coordinator = f.coordinator.clone();
            use_coordinator.record(
                learning_test_receipt(&use_coordinator, f.selection.clone()),
                20,
            )?;
            let request = support::request(
                &f.publication.target_config,
                f.runtime.handle.snapshot().await?,
            );
            let intent = request.intent()?;
            if phase == "after_use" {
                f.runtime.handle.step(request).await?;
                f.runtime
                    .handle
                    .read_learning_next_use_readback(&use_coordinator, &intent)
                    .await?;
            }
            match change {
                "current" => f.publication.advance_artifact_current()?,
                "withdrawal" => f.publication.withdraw()?,
                "revocation" => {
                    let mut head = f.publication.authority.revocation_head()?;
                    head.revision += 1;
                    head.revoked_grant_ids
                        .insert(f.runtime.publication.signed_grant().grant.grant_id.clone());
                    f.publication.authority.update_revocations(head)?;
                }
                _ => anyhow::bail!("unknown mutation"),
            }
            assert!(
                f.runtime
                    .handle
                    .read_learning_selection(&f.coordinator)
                    .await
                    .is_err(),
                "{change}"
            );
            assert!(
                f.runtime
                    .handle
                    .read_learning_next_use_readback(&use_coordinator, &intent)
                    .await
                    .is_err(),
                "{change}"
            );
            assert_eq!(
                f.control.executions.load(Ordering::SeqCst),
                usize::from(phase == "after_use")
            );
            assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
            tasks.shutdown().await;
        }
    }
    Ok(())
}

#[tokio::test]
async fn unpublished_actor_refuses_learning_readback_and_keeps_transport_errors()
-> anyhow::Result<()> {
    let f = LearningRuntime::new().await?;
    let (handle, bootstrap) = neuron_generation_channel_v2(
        &f.host.identity,
        f.host.journal(),
        f.host.control.clone(),
        f.host.clock(),
        /*capacity*/ 1,
    )?;
    let intent = support::request(
        &f.publication.target_config,
        f.publication.target_config.initial.clone(),
    )
    .intent()?;
    let first = handle.read_learning_next_use_readback(&f.coordinator, &intent);
    tokio::pin!(first);
    host::poll_pending(first.as_mut());
    assert!(matches!(
        handle.read_learning_selection(&f.coordinator).await,
        Err(NeuronGenerationLearningReadErrorV1::Runtime(
            CellGenerationErrorV2::Capacity
        ))
    ));
    let (mut tasks, lifetime) = host::host();
    spawn_neuron_generation_service(&mut tasks, bootstrap, Arc::clone(f.host.state()), lifetime)?;
    assert!(matches!(
        first.await,
        Err(NeuronGenerationLearningReadErrorV1::Observation(
            AgentdError::GenerationFenced(_)
        ))
    ));
    tasks.shutdown().await;
    assert!(matches!(
        handle.read_learning_selection(&f.coordinator).await,
        Err(NeuronGenerationLearningReadErrorV1::Runtime(
            CellGenerationErrorV2::Unavailable
        ))
    ));
    Ok(())
}
