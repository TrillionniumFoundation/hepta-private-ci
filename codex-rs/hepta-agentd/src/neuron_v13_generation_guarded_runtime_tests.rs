//! A real verifier rejection through the published 03 owner and ordinary
//! Fleet/service lifecycle. Invalid closure assets never qualify V13 inference.

use std::fs;
use std::time::Duration;

use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::V13TaskInputV1;
use codex_hepta_types::AuthorityPosture;
use pretty_assertions::assert_eq;
use tokio::time::sleep;
use tokio::time::timeout;

use super::support::Fixture;
use super::support::runtime_config;
use crate::AgentdError;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_v13_generation_update::prepare_agentd_v13_generation_cold_same_model_task_v1;
use crate::neuron_v13_generation_update::prepare_agentd_v13_generation_cold_update_v1;
use crate::neuron_v13_generation_update::recover_agentd_v13_generation_update_v1;

#[tokio::test]
async fn cold_typed_publication_recovery_charges_preparation_once_and_replays_real_v13_rejection()
-> anyhow::Result<()> {
    typed_publication_recovery(/*same_model*/ false).await
}

#[tokio::test]
async fn cold_same_model_v13_task_uses_typed_worker_and_cold_recovery_without_reexecution()
-> anyhow::Result<()> {
    typed_publication_recovery(/*same_model*/ true).await
}

async fn typed_publication_recovery(same_model: bool) -> anyhow::Result<()> {
    let mut f = if same_model {
        Fixture::same_model()?
    } else {
        Fixture::new()?
    };
    let old_bytes = (
        f.update.bytes("old-journal")?,
        f.update.bytes("old-witness")?,
    );
    let prepare = if same_model {
        assert_eq!(
            f.update.old_config.manifest,
            f.host.config.generation.manifest
        );
        prepare_agentd_v13_generation_cold_same_model_task_v1
    } else {
        prepare_agentd_v13_generation_cold_update_v1
    };
    let prepared = prepare(
        f.update.current.clone(),
        f.update.authorities()?,
        f.predecessor()?,
        f.update.selection()?,
        f.inputs()?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "cold-v13-publication".into(),
        },
    )?;
    let intent_digest = prepared.intent_digest();
    let signed = f.update.sign(prepared.final_use_binding())?;
    let before_publication = f.host.owner_bytes()?;
    assert_eq!(&before_publication[0][..8], b"HPTACG03");
    assert_eq!(before_publication[0].len(), 40);
    assert!(before_publication[2].is_empty());
    assert_eq!(f.update.authority.capacity()?.used_nonces, 0);

    let ready = prepared.publish(&signed)?;
    assert_eq!(f.update.authority.capacity()?.used_nonces, 1);
    assert_eq!(f.host.owner_bytes()?, before_publication);
    let claims = f.update.bytes("final-use/authority.claims")?;
    let current_bytes = f.update.bytes("current.json")?;
    let mut runtime = ready.into_runtime(runtime_config(&f.host.identity)?, f.options())?;
    assert_eq!(runtime.publication.authority(), AuthorityPosture::DENY_ALL);
    let (mut tasks, state) = f.start(&mut runtime).await?;
    assert_eq!(
        runtime.handle.snapshot().await?,
        f.host.config.generation.initial
    );
    let preparation = f
        .host
        .prepared
        .worker()
        .preparation_cost(CellTaskCostIdentityV2 {
            task_digest: f.host.config.generation.task_digest,
            source_digest: f.host.config.generation.manifest.source_digest,
        })?;
    assert!(preparation.metrics.wall_micros.is_some());
    assert!(preparation.metrics.cpu_micros.is_none());
    assert_eq!(
        runtime.handle.task_cost().await?.entries(),
        std::slice::from_ref(&preparation)
    );
    let now = (f.host.prepared.worker().clock())();
    let request = CellGenerationRequestV2 {
        operation_id: "guarded-real-v13-rejection".into(),
        task_digest: f.host.config.generation.task_digest,
        source_frontier: f.host.config.generation.source_frontier,
        predecessor: runtime.handle.snapshot().await?,
        input: V13TaskInputV1 {
            schema: "hepta.v13.task-input.v1".into(),
            text: "Sort this new task payload".into(),
            payload: serde_json::json!([3, 1, 2]),
        }
        .encode()?,
        admitted_at_micros: now,
        deadline_micros: now + 15_000_000,
    };
    let receipt = super::super::settle(&runtime.handle, request.clone()).await?;
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Rejected);
    assert!(receipt.cost.entries().iter().any(|entry| {
        entry
            .metrics
            .communication_bytes
            .is_some_and(|bytes| bytes > 0)
    }));
    assert!(
        receipt
            .cost
            .entries()
            .iter()
            .all(|entry| entry.metrics.energy_microjoules.is_none())
    );
    assert_eq!(runtime.handle.pending_request().await?, None);
    assert_eq!(runtime.handle.pending_output().await?, None);
    assert!(runtime.handle.drain().await?);
    let observation = runtime.handle.observe_generation().await?;
    assert!(observation.snapshot().state.is_empty());
    assert!(observation.snapshot().prefix.is_empty());
    assert_eq!(
        observation
            .cost()
            .entries()
            .iter()
            .filter(|entry| entry.event_id == preparation.event_id)
            .count(),
        1
    );
    assert!(!fs::read(&f.host.paths[2])?.is_empty());
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(runtime);
    drop(tasks);
    drop(state);
    let retained = f.host.owner_bytes()?;
    f.next_spawn()?;

    // The actual worker/preparation and Linux boot remain the same. Only the
    // complete Fleet spawn identity changes; Cell writer epoch does not.
    let ready = timeout(Duration::from_secs(5), async {
        loop {
            match recover_agentd_v13_generation_update_v1(
                f.update.reopen_current()?,
                f.update.authorities()?,
                f.update.selection()?,
                f.inputs()?,
                AgentdGenerationUpdateRecoveryV1 {
                    operation_id: "cold-v13-publication".into(),
                    intent_digest,
                },
            ) {
                Ok(ready) => return Ok::<_, anyhow::Error>(ready),
                Err(AgentdError::Invalid(message)) if message == "WriterUnavailable" => {
                    sleep(Duration::from_millis(1)).await;
                }
                Err(error) => return Err(error.into()),
            }
        }
    })
    .await??;
    assert_eq!(f.host.owner_bytes()?, retained);
    let mut runtime = ready.into_runtime(runtime_config(&f.host.identity)?, f.options())?;
    assert_eq!(f.host.owner_bytes()?, retained);
    let (mut tasks, state) = f.start(&mut runtime).await?;
    assert_eq!(runtime.handle.observe_generation().await?, observation);
    assert_eq!(runtime.handle.step(request).await?, receipt);
    assert_eq!(f.host.owner_bytes()?, retained);
    assert_eq!(f.update.bytes("current.json")?, current_bytes);
    assert_eq!(f.update.bytes("final-use/authority.claims")?, claims);
    assert_eq!(f.update.authority.capacity()?.used_nonces, 1);
    assert_eq!(
        (
            f.update.bytes("old-journal")?,
            f.update.bytes("old-witness")?
        ),
        old_bytes
    );
    assert!(runtime.handle.drain().await?);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(runtime);
    drop(state);
    Ok(())
}
