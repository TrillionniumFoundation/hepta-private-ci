use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_neuron::*;
use pretty_assertions::assert_eq;
use tokio::time::sleep;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::*;
use crate::RuntimeTasks;
use crate::neuron_generation_service::spawn_neuron_generation_service;

#[path = "neuron_v13_generation_bootstrap_test_support.rs"]
mod support;

use support::Fixture;

#[test]
fn identity_epoch_and_closure_mismatch_leave_all_owner_files_untouched() -> Result<()> {
    let f = Fixture::new()?;
    let before = f.owner_bytes()?;
    for case in 0..7 {
        let mut config = f.config.clone();
        let mut identity = f.identity.clone();
        match case {
            0 => identity.resources.memory_limit_mib += 1,
            1 => identity.spawn_generation += 1,
            2 => config.expected_boot_id_digest = Digest32::of_bytes(b"different-boot"),
            3 => config.generation.source_frontier = [99; 32],
            4 => {
                config.generation.manifest.learning =
                    CellLearningBindingV2::Frozen { weights: [25; 32] }
            }
            5 => config.generation.initial.state = vec![1],
            6 => config.queue_capacity = 0,
            _ => unreachable!(),
        }
        assert!(
            bootstrap_agentd_v13_generation_v1(
                &identity,
                config,
                f.files()?,
                V13GenerationOwnerModeV1::InitializeEmpty,
                &f.prepared
            )
            .is_err()
        );
        assert_eq!(f.owner_bytes()?, before);
    }
    assert!(
        bootstrap_agentd_v13_generation_v1(
            &f.identity,
            f.config.clone(),
            f.files()?,
            V13GenerationOwnerModeV1::Reopen,
            &f.prepared
        )
        .is_err()
    );
    assert_eq!(f.owner_bytes()?, before);
    Ok(())
}

#[test]
fn actual_owner_descriptor_aliases_and_wrong_flags_fail_before_decode_or_write() -> Result<()> {
    let f = Fixture::new()?;
    let before = f.owner_bytes()?;
    let asset_before = fs::read(&f.model_path)?;
    for case in 0..5 {
        let mut files = f.files()?;
        match case {
            0 => files.journal = File::open(&f.paths[0])?,
            1 => {
                files.control = OpenOptions::new()
                    .read(true)
                    .write(true)
                    .open(&f.paths[2])?
            }
            2 => {
                files.journal = OpenOptions::new()
                    .read(true)
                    .append(true)
                    .open(&f.paths[0])?
            }
            3 => {
                files.witness = OpenOptions::new()
                    .read(true)
                    .write(true)
                    .open(&f.paths[0])?
            }
            4 => {
                files.journal = OpenOptions::new()
                    .read(true)
                    .write(true)
                    .open(&f.model_path)?
            }
            _ => unreachable!(),
        }
        assert!(
            bootstrap_agentd_v13_generation_v1(
                &f.identity,
                f.config.clone(),
                files,
                V13GenerationOwnerModeV1::InitializeEmpty,
                &f.prepared
            )
            .is_err()
        );
        assert_eq!(f.owner_bytes()?, before);
        assert_eq!(fs::read(&f.model_path)?, asset_before);
    }
    Ok(())
}

#[test]
fn preparation_scope_is_sticky_after_lock_failure_and_atomic_between_tasks() -> Result<()> {
    let f = Fixture::new()?;
    let locked_control = OpenOptions::new()
        .read(true)
        .append(true)
        .open(&f.paths[2])?;
    locked_control.try_lock()?;
    assert!(
        matches!(bootstrap_agentd_v13_generation_v1(&f.identity, f.config.clone(), f.files()?,
        V13GenerationOwnerModeV1::InitializeEmpty, &f.prepared),
        Err(AgentdError::Invalid(message)) if message == "WriterUnavailable")
    );
    drop(locked_control);
    let mut other_task = f.config.clone();
    other_task.generation.task_digest = [18; 32];
    assert!(
        matches!(bootstrap_agentd_v13_generation_v1(&f.identity, other_task, f.files()?,
        V13GenerationOwnerModeV1::InitializeEmpty, &f.prepared),
        Err(AgentdError::Invalid(message)) if message.contains("another task scope"))
    );
    assert_eq!(f.owner_bytes()?, vec![Vec::<u8>::new(); 3]);

    let g = Fixture::new()?;
    let mut attempts = Vec::new();
    for name in ["parallel-a", "parallel-b"] {
        let parent = g.paths[0]
            .parent()
            .ok_or_else(|| anyhow::anyhow!("fixture parent"))?;
        let paths = [
            parent.join(format!("{name}-cell")),
            parent.join(format!("{name}-witness")),
            parent.join(format!("{name}-control")),
        ];
        let open = |index: usize| {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .append(index == 2)
                .mode(0o600)
                .open(&paths[index])
        };
        let files = V13GenerationOwnerFilesV1 {
            journal: open(0)?,
            witness: open(1)?,
            control: open(2)?,
        };
        let mut config = g.config.clone();
        config.generation.initial.scope.run_id = name.into();
        attempts.push((paths, files, config));
    }
    let results = std::thread::scope(|scope| {
        let handles: Vec<_> = attempts
            .into_iter()
            .map(|(paths, files, config)| {
                let prepared = &g.prepared;
                let identity = &g.identity;
                scope.spawn(move || {
                    let result = bootstrap_agentd_v13_generation_v1(
                        identity,
                        config,
                        files,
                        V13GenerationOwnerModeV1::InitializeEmpty,
                        prepared,
                    );
                    let result = result.map(drop).map_err(|error| error.to_string());
                    (paths, result)
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| {
                handle
                    .join()
                    .map_err(|_| anyhow::anyhow!("bootstrap thread panicked"))
            })
            .collect::<Result<Vec<_>>>()
    })?;
    assert_eq!(
        results.iter().filter(|(_, result)| result.is_ok()).count(),
        1
    );
    for (paths, result) in results {
        if let Err(error) = result {
            assert!(error.contains("another task scope"));
            for path in paths {
                assert_eq!(fs::metadata(path)?.len(), 0);
            }
        }
    }
    Ok(())
}

async fn settle(
    handle: &NeuronGenerationRuntimeHandleV2,
    request: CellGenerationRequestV2,
) -> Result<CellGenerationReceiptV2> {
    let mut next = handle.step(request.clone()).await;
    Ok(timeout(Duration::from_secs(15), async {
        loop {
            match next {
                Ok(receipt) => return Ok(receipt),
                Err(CellGenerationErrorV2::Pending) => sleep(Duration::from_millis(2)).await,
                Err(error) => return Err(error),
            }
            next = handle.reconcile(request.digest()?).await;
        }
    })
    .await??)
}

#[tokio::test]
async fn real_v13_rejection_retains_cost_and_reopens_original_result_without_repreparation()
-> Result<()> {
    let mut f = Fixture::new()?;
    let (handle, bootstrap) = bootstrap_agentd_v13_generation_v1(
        &f.identity,
        f.config.clone(),
        f.files()?,
        V13GenerationOwnerModeV1::InitializeEmpty,
        &f.prepared,
    )?;
    let opened = f.owner_bytes()?;
    assert!(
        bootstrap_agentd_v13_generation_v1(
            &f.identity,
            f.config.clone(),
            f.files()?,
            V13GenerationOwnerModeV1::Reopen,
            &f.prepared
        )
        .is_err()
    );
    assert_eq!(f.owner_bytes()?, opened);
    f.registry.compare_and_transition(
        &f.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    let state = f.state().await?;
    let cancellation = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(2))?;
    spawn_neuron_generation_service(&mut tasks, bootstrap, Arc::clone(&state), cancellation)?;
    let preparation = f
        .prepared
        .worker()
        .preparation_cost(CellTaskCostIdentityV2 {
            task_digest: f.config.generation.task_digest,
            source_digest: f.config.generation.manifest.source_digest,
        })?;
    assert_eq!(
        handle.task_cost().await?.entries(),
        std::slice::from_ref(&preparation)
    );
    let now = (f.prepared.worker().clock())();
    let request = CellGenerationRequestV2 {
        operation_id: "actual-v13-rejection".into(),
        task_digest: f.config.generation.task_digest,
        source_frontier: f.config.generation.source_frontier,
        predecessor: handle.snapshot().await?,
        input: V13TaskInputV1 {
            schema: "hepta.v13.task-input.v1".into(),
            text: "Sort these new caller numbers".into(),
            payload: serde_json::json!([3, 1, 2]),
        }
        .encode()?,
        admitted_at_micros: now,
        deadline_micros: now + 15_000_000,
    };
    let receipt = settle(&handle, request.clone()).await?;
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Rejected);
    assert!(
        receipt
            .cost
            .entries()
            .iter()
            .any(|e| e.metrics.communication_bytes.is_some_and(|v| v > 0))
    );
    assert!(
        receipt
            .cost
            .entries()
            .iter()
            .all(|e| e.metrics.energy_microjoules.is_none())
    );
    assert_eq!(handle.pending_request().await?, None);
    assert_eq!(handle.pending_output().await?, None);
    let snapshot = handle.snapshot().await?;
    assert!(snapshot.state.is_empty() && snapshot.prefix.is_empty());
    let cost = handle.task_cost().await?;
    assert_eq!(
        cost.entries()
            .iter()
            .filter(|e| e.event_id == preparation.event_id)
            .count(),
        1
    );
    assert!(handle.drain().await?);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(handle);
    drop(state);
    // Follow the real Fleet lifecycle to the next host spawn, retaining the
    // original Cell generation, writer epoch, witness and operation identity.
    for (expected_generation, lifecycle) in [
        (2, AgentLifecycle::Draining),
        (3, AgentLifecycle::Stopped),
        (4, AgentLifecycle::Starting),
    ] {
        f.registry
            .compare_and_transition(&f.identity.agent_id, expected_generation, lifecycle)?;
    }
    f.identity.spawn_generation = 5;
    let retained = f.owner_bytes()?;
    assert!(
        bootstrap_agentd_v13_generation_v1(
            &f.identity,
            f.config.clone(),
            f.files()?,
            V13GenerationOwnerModeV1::Reopen,
            &f.prepared
        )
        .is_err()
    );
    assert_eq!(f.owner_bytes()?, retained);
    f.config.expected_identity_digest = neuron_generation_process_identity_digest_v1(&f.identity)?;
    let (handle, bootstrap) = timeout(Duration::from_secs(5), async {
        loop {
            match bootstrap_agentd_v13_generation_v1(
                &f.identity,
                f.config.clone(),
                f.files()?,
                V13GenerationOwnerModeV1::Reopen,
                &f.prepared,
            ) {
                Ok(value) => return Ok::<_, anyhow::Error>(value),
                Err(AgentdError::Invalid(message)) if message == "WriterUnavailable" => {
                    sleep(Duration::from_millis(1)).await
                }
                Err(error) => return Err(error.into()),
            }
        }
    })
    .await??;
    assert_eq!(f.owner_bytes()?, retained);
    f.registry.compare_and_transition(
        &f.identity.agent_id,
        /*expected_generation*/ 5,
        AgentLifecycle::Running,
    )?;
    let cancellation = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(2))?;
    spawn_neuron_generation_service(&mut tasks, bootstrap, f.state().await?, cancellation)?;
    assert_eq!(handle.snapshot().await?, snapshot);
    assert_eq!(handle.task_cost().await?, cost);
    assert_eq!(handle.step(request).await?, receipt);
    assert_eq!(f.owner_bytes()?, retained);
    assert!(handle.drain().await?);
    tasks.shutdown().await;
    drop(handle);
    Ok(())
}

#[path = "neuron_v13_generation_guarded_tests.rs"]
mod guarded;
