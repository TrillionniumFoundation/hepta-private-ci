//! First signed publication, original-operation recovery and a real V13
//! verifier rejection followed by explicit owner retirement. No STOP proposal
//! or successful trained inference is manufactured by this fixture.

use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellRuntimeSnapshotV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::V13TaskInputV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::support::Fixture;
use super::support::next_spawn;
use super::support::start;
use super::super::support::runtime_config;
use super::super::super::support::Fixture as HostFixture;
use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationPredecessorCompletionV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_process_identity_digest_v1;
use crate::neuron_v13_generation_update::AgentdV13GenerationUpdateInputsV1;
use crate::neuron_v13_generation_update::prepare_agentd_v13_generation_cold_drained_update_v1;

#[tokio::test]
async fn initial_ready_rejects_wrong_runtime_identity_and_queue_before_preparation_cost()
-> anyhow::Result<()> {
    for change in ["identity", "queue"] {
        let f = Fixture::new()?;
        let prepared = f.prepare()?;
        let intent_digest = prepared.intent_digest();
        let signed = f.current.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&signed)?;
        let before = f.bytes()?;
        let other = HostFixture::new()?;
        let identity = if change == "identity" { &other.identity } else { &f.host.identity };
        let mut options = f.options();
        if change == "queue" {
            options.queue_capacity += 1;
        }
        let result = ready.into_runtime(runtime_config(identity)?, options);
        if change == "identity" {
            assert!(matches!(result, Err(AgentdError::GenerationFenced(_))));
        } else {
            assert!(matches!(result, Err(AgentdError::Invalid(message))
                if message.contains("initial runtime queue differs")));
        }
        assert_eq!(f.bytes()?, before);
        assert!(f.host.owner_bytes()?[2].is_empty());
        assert_eq!(f.current.authority.capacity()?.used_nonces, 1);
        // Reopening the actual original publication succeeds after the failed
        // consuming assembly; no lower actor or duplicate charge was hidden.
        drop(f.recover(intent_digest).await?);
        assert_eq!(f.bytes()?, before);
    }
    Ok(())
}

#[tokio::test]
async fn actual_initial_v13_rejection_replays_then_retires_to_a_new_selected_task()
-> anyhow::Result<()> {
    let mut f = Fixture::new()?;
    let prepared = f.prepare()?;
    let intent_digest = prepared.intent_digest();
    let signed = f.current.sign(prepared.final_use_binding())?;
    let genesis = f.host.owner_bytes()?;
    let ready = prepared.publish(&signed)?;
    assert_eq!(f.host.owner_bytes()?, genesis);
    assert_eq!(genesis[0].len(), 40);
    assert!(genesis[2].is_empty());
    let mut runtime = ready.into_runtime(runtime_config(&f.host.identity)?, f.options())?;
    assert_eq!(runtime.publication.authority(), AuthorityPosture::DENY_ALL);
    let (mut tasks, state) = start(&f.host, &mut runtime.config).await?;
    let preparation = f.host.prepared.worker().preparation_cost(CellTaskCostIdentityV2 {
        task_digest: f.host.config.generation.task_digest,
        source_digest: f.host.config.generation.manifest.source_digest,
    })?;
    assert_eq!(runtime.handle.task_cost().await?.entries(), std::slice::from_ref(&preparation));
    let request = task_request(
        &f.host, &f.host.config.generation,
        runtime.handle.snapshot().await?, "initial-real-v13-rejection",
    )?;
    let receipt = super::super::super::settle(&runtime.handle, request.clone()).await?;
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Rejected);
    assert!(receipt.cost.entries().iter().any(|entry|
        entry.metrics.communication_bytes.is_some_and(|bytes| bytes > 0)));
    assert!(receipt.cost.entries().iter().all(|entry| entry.metrics.energy_microjoules.is_none()));
    assert!(!runtime.handle.snapshot().await?.stopped);
    assert_eq!(runtime.handle.pending_request().await?, None);
    assert_eq!(runtime.handle.pending_output().await?, None);
    assert!(runtime.handle.drain().await?);
    let observation = runtime.handle.observe_generation().await?;
    assert!(!observation.is_terminal());
    assert_eq!(observation.cost().entries().iter()
        .filter(|entry| entry.event_id == preparation.event_id).count(), 1);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(runtime);
    drop(tasks);
    drop(state);
    let retained = f.host.owner_bytes()?;
    let claims = f.current.bytes("final-use/authority.claims")?;
    let current_bytes = f.current.bytes("current.json")?;
    next_spawn(&mut f.host)?;

    let ready = f.recover(intent_digest).await?;
    assert_eq!(f.host.owner_bytes()?, retained);
    let mut runtime = ready.into_runtime(runtime_config(&f.host.identity)?, f.options())?;
    assert_eq!(f.host.owner_bytes()?, retained);
    let (mut tasks, state) = start(&f.host, &mut runtime.config).await?;
    assert_eq!(runtime.handle.observe_generation().await?, observation);
    assert_eq!(runtime.handle.step(request).await?, receipt);
    assert_eq!(f.host.owner_bytes()?, retained);
    assert_eq!(f.current.bytes("current.json")?, current_bytes);
    assert_eq!(f.current.bytes("final-use/authority.claims")?, claims);
    assert_eq!(f.current.authority.capacity()?.used_nonces, 1);
    assert!(runtime.handle.drain().await?);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(runtime);
    drop(tasks);
    drop(state);
    next_spawn(&mut f.host)?;

    // The new task has an independent actual asset preparation and owner
    // files. Its distinct evolution label is explicit fixture data; this
    // test makes no claim of different trained weights or learned capability.
    let next_assets = HostFixture::new()?;
    let mut next = next_assets.config.clone();
    next.expected_identity_digest = neuron_generation_process_identity_digest_v1(&f.host.identity)?;
    next.generation.initial.scope = f.host.config.generation.initial.scope.clone();
    next.generation.initial.scope.run_id = "explicit-owner-retirement-next-task".into();
    next.generation.initial.generation = f.host.config.generation.initial.generation + 1;
    next.generation.initial.writer_epoch = f.host.config.generation.initial.writer_epoch + 1;
    next.generation.task_digest = Digest32::of_bytes(b"new explicitly retired V13 task").into_array();
    next.generation.manifest.evolution.lineage = Digest32::of_bytes(b"test next selected lineage").into_array();
    next.generation.initial.manifest_digest = next.generation.manifest.digest()?;
    next_assets.prepared.worker().validate_manifest(&next.generation.manifest)?;
    let old_ready = f.recover(intent_digest).await?;
    let selected = f.current.publish_next_selection(&next.generation.manifest, "next-v13-task")?;
    assert!(matches!(old_ready.into_runtime(runtime_config(&f.host.identity)?, f.options()),
        Err(AgentdError::Invalid(message)) if message == "Unavailable"));
    assert_eq!(f.host.owner_bytes()?, retained);
    let predecessor = f.predecessor().await?;
    let prepared = prepare_agentd_v13_generation_cold_drained_update_v1(
        f.current.current.clone(), f.current.authorities()?, predecessor, selected,
        AgentdV13GenerationUpdateInputsV1 {
            identity: &f.host.identity,
            config: next.clone(),
            files: next_assets.files()?,
            prepared: &next_assets.prepared,
        },
        AgentdGenerationUpdateRequestV1 { operation_id: "explicit-v13-retirement".into() },
    )?;
    let actual_prepared = f.current.current.recover_operation(
        "explicit-v13-retirement", prepared.intent_digest(),
    )?;
    assert_eq!(actual_prepared.completion(), NeuronGenerationPredecessorCompletionV1::OwnerDrained);
    assert_eq!(prepared.final_use_binding().destination_id, "agentd.cell-generation.replace-drained");
    assert_eq!(f.host.owner_bytes()?, retained);
    let signed = f.current.sign(prepared.final_use_binding())?;
    let ready = prepared.publish(&signed)?;
    assert_eq!(f.current.authority.capacity()?.used_nonces, 2);
    assert_eq!(f.host.owner_bytes()?, retained);
    let mut runtime = ready.into_runtime(runtime_config(&f.host.identity)?, f.options())?;
    assert_eq!(runtime.publication.completion(), NeuronGenerationPredecessorCompletionV1::OwnerDrained);
    assert_eq!(runtime.publication.authority(), AuthorityPosture::DENY_ALL);
    let (mut tasks, state) = start(&f.host, &mut runtime.config).await?;
    assert_eq!(runtime.handle.snapshot().await?, next.generation.initial);
    let next_preparation = next_assets.prepared.worker().preparation_cost(CellTaskCostIdentityV2 {
        task_digest: next.generation.task_digest,
        source_digest: next.generation.manifest.source_digest,
    })?;
    assert_eq!(runtime.handle.task_cost().await?.entries(), std::slice::from_ref(&next_preparation));
    let next_request = task_request(
        &next_assets, &next.generation, runtime.handle.snapshot().await?, "next-real-v13-rejection",
    )?;
    let next_receipt = super::super::super::settle(&runtime.handle, next_request).await?;
    assert_eq!(next_receipt.disposition, CellGenerationDispositionV2::Rejected);
    assert!(!runtime.handle.snapshot().await?.stopped);
    assert!(runtime.handle.drain().await?);
    assert!(!observation.snapshot().stopped);
    assert!(observation.snapshot().prefix.is_empty());
    assert_eq!(f.host.owner_bytes()?, retained);
    let old_binding = CellGenerationOwnerBindingV1::new(&f.host.config.generation, f.host.config.max_records)?;
    assert_eq!(f.current.current.check_current(&old_binding), Err(CellGenerationErrorV2::InvalidBinding));
    let old = f.predecessor().await?;
    assert_eq!(CellGenerationJournalV2::open_guarded(
        old.file, old.witness, old.config, old.max_records, f.current.current.clone(),
    ).err(), Some(CellGenerationErrorV2::InvalidBinding));
    assert_eq!(f.host.owner_bytes()?, retained);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(runtime);
    drop(state);
    Ok(())
}

fn task_request(
    host: &HostFixture,
    config: &CellGenerationConfigV2,
    predecessor: CellRuntimeSnapshotV2,
    operation: &str,
) -> anyhow::Result<CellGenerationRequestV2> {
    let now = (host.prepared.worker().clock())();
    Ok(CellGenerationRequestV2 {
        operation_id: operation.into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor,
        input: V13TaskInputV1 {
            schema: "hepta.v13.task-input.v1".into(),
            text: "Sort this new task payload".into(),
            payload: serde_json::json!([3, 1, 2]),
        }.encode()?,
        admitted_at_micros: now,
        deadline_micros: now + 15_000_000,
    })
}
