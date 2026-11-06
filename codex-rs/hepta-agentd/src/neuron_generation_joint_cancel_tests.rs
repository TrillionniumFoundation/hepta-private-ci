//! Cancel an ordinary trained-asset admission without assuming child launch.

use std::fs;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use tokio::time::sleep;
use tokio::time::timeout;

use super::Clock;
use super::Fixture;
use super::ModelFixture;
use super::TestResult;
use super::evidence_directory;
use super::execute;
use super::install_model;
use super::request;
use super::start_service;
use super::trained;

#[tokio::test]
async fn historical_trained_joint_admission_cancel_retains_predecessor_cost_and_receipt_on_reopen()
-> TestResult {
    let mut fixture = Fixture::new().await;
    let epoch = Instant::now();
    let clock: Clock =
        Arc::new(move || u64::try_from(epoch.elapsed().as_micros()).unwrap_or(u64::MAX - 1) + 1);
    let (worker, assets) = install_model(
        &mut fixture,
        Arc::clone(&clock),
        ModelFixture::HistoricalTrained,
    )?;
    let public_digest = Digest32::of_bytes(&assets.public).into_array();
    let (handle, mut tasks) =
        start_service(&fixture, Arc::clone(&worker), Arc::clone(&clock)).await?;
    let (_, initialized) = execute(
        &handle,
        &clock,
        public_digest,
        "trained-cancel-init",
        JointGenerationCommandV1::Init {
            seed: 17,
            sampler: JointGenerationSamplerV1::Mean,
        },
    )
    .await?;
    assert_eq!(
        initialized.disposition,
        CellGenerationDispositionV2::Advanced
    );
    let predecessor = handle.snapshot().await?;
    assert!(!predecessor.state.is_empty());
    let initial_cost = handle.task_cost().await?;
    let mut original = request("trained-cancel-shared", predecessor.clone());
    original.input = serde_json::to_vec(&JointGenerationInputV1 {
        public_digest,
        command: JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Shared,
        },
    })?;
    original.admitted_at_micros = clock();
    original.deadline_micros = original.admitted_at_micros + 30_000_000;
    let digest = original.digest()?;
    assert_eq!(
        handle.step(original.clone()).await,
        Err(CellGenerationErrorV2::Pending)
    );
    // Persist the actual owner intent immediately after admission. There is no
    // timing barrier or substitute worker: Shared may be unlaunched, interrupted
    // or already completed, but its result must never be adopted after this.
    handle.cancel(digest).await?;
    let cancelled = timeout(Duration::from_secs(35), async {
        loop {
            match handle.reconcile(digest).await {
                Ok(receipt) => return Ok(receipt),
                Err(CellGenerationErrorV2::Pending) => sleep(Duration::from_millis(10)).await,
                Err(error) => return Err(error),
            }
        }
    })
    .await??;
    assert_eq!(
        cancelled.disposition,
        CellGenerationDispositionV2::Cancelled
    );
    assert_eq!(cancelled.request_digest, digest);
    cancelled.cost.validate()?;
    // Two control observations, optionally one interrupted process envelope or
    // five successfully completed process phases. No compute work is invented.
    assert!(matches!(cancelled.cost.entries().len(), 2 | 3 | 7));
    assert!(cancelled.cost.entries().iter().all(|entry| {
        entry.accounting == CellCostAccountingV2::Exclusive
            && entry.metrics.wall_micros.is_some()
            && entry.metrics.cpu_micros.is_none()
            && entry.metrics.energy_microjoules.is_none()
    }));
    for stage in [CellCostStageV2::Queue, CellCostStageV2::Persistence] {
        assert!(
            cancelled
                .cost
                .entries()
                .iter()
                .any(|entry| entry.stage == stage)
        );
    }
    let mut expected = predecessor.clone();
    expected.revision += 1;
    let snapshot = handle.snapshot().await?;
    assert_eq!(snapshot, expected);
    assert_eq!(handle.pending_output().await?, None);
    assert_eq!(handle.pending_request().await?, None);
    let cost = handle.task_cost().await?;
    cost.validate()?;
    assert_eq!(
        cost.entries().len(),
        initial_cost.entries().len() + cancelled.cost.entries().len()
    );
    assert!(
        initial_cost
            .entries()
            .iter()
            .chain(cancelled.cost.entries())
            .all(|entry| { cost.entries().contains(entry) })
    );
    let original_control = fs::read(fixture.directory.path().join("joint-control.log"))?;
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(handle);
    fixture.reopen_state().await;
    let (handle, mut tasks) = start_service(&fixture, worker, clock).await?;
    assert_eq!(handle.snapshot().await?, snapshot);
    assert_eq!(handle.pending_output().await?, None);
    assert_eq!(handle.pending_request().await?, None);
    assert_eq!(handle.task_cost().await?, cost);
    assert_eq!(handle.step(original).await?, cancelled);
    assert_eq!(handle.task_cost().await?, cost);
    assert_eq!(
        fs::read(fixture.directory.path().join("joint-control.log"))?,
        original_control
    );
    assert!(handle.drain().await?);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(handle);
    let journal = fixture.journal();
    assert!(journal.is_drained()?);
    assert_eq!(journal.snapshot()?, &snapshot);
    assert_eq!(journal.task_cost()?, &cost);
    assert_eq!(journal.pending_output()?, None);
    let evidence = evidence_directory("joint-trained-cancel-")?;
    fs::write(
        evidence.path().join("predecessor-state.hps"),
        &predecessor.state,
    )?;
    fs::write(evidence.path().join("state.hps"), &snapshot.state)?;
    fs::write(evidence.path().join("prefix.hgc"), &snapshot.prefix)?;
    fs::write(evidence.path().join("control.log"), &original_control)?;
    let provenance: serde_json::Value = serde_json::from_str(trained::PROVENANCE)?;
    let receipt = serde_json::json!({
        "schema": "hepta.historical-trained-agentd-cancellation.v1",
        "provenance": provenance,
        "runtime_digest": fixture.config.manifest.runtime_digest,
        "device_digest": fixture.config.manifest.device_digest,
        "manifest_digest": fixture.config.manifest.digest()?,
        "initialized": initialized,
        "cancelled": cancelled,
        "cost": cost,
        "state_sha256": Digest32::of_bytes(&snapshot.state).to_string(),
        "control_sha256": Digest32::of_bytes(&original_control).to_string(),
        "predecessor_state_and_prefix_preserved": true,
        "reopen_and_retry_preserved_receipt_and_cost": true,
        "shared_child_launch_guaranteed": false,
        "new_training_updates": 0,
        "scope": "Actual trained Init then immediate admission-cancel of Shared through the ordinary Agentd owner; only observed work is charged.",
        "not_covered": ["Guaranteed interruption during numeric execution", "Forced process death", "Natural-task quality", "CPU/energy"]
    });
    fs::write(
        evidence.path().join("CANCELLATION.json"),
        serde_json::to_vec_pretty(&receipt)?,
    )?;
    let retained = evidence.keep();
    println!(
        "historical trained Joint cancellation evidence: {}",
        retained.display()
    );
    Ok(())
}
