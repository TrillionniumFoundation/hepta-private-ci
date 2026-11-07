use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agentd::NeuronGenerationRuntimeHandleV2;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde_json::Value;
use tokio::time::sleep;
use tokio::time::timeout;

pub(super) async fn original_result(
    handle: &NeuronGenerationRuntimeHandleV2,
    request: &CellGenerationRequestV2,
    mut result: Result<CellGenerationReceiptV2, CellGenerationErrorV2>,
) -> Result<CellGenerationReceiptV2> {
    Ok(timeout(Duration::from_secs(120), async {
        loop {
            match result {
                Ok(receipt) => return Ok(receipt),
                Err(CellGenerationErrorV2::Pending) => sleep(Duration::from_millis(5)).await,
                Err(error) => return Err(error),
            }
            result = handle.reconcile(request.digest()?).await;
        }
    })
    .await
    .context("original V13 request remained pending")??)
}

pub(super) async fn deliver(
    handle: &NeuronGenerationRuntimeHandleV2,
    request: &CellGenerationRequestV2,
    chunk: CellOutputChunkV2,
    path: &Path,
    identity: CellTaskCostIdentityV2,
) -> Result<Digest32> {
    let started = Instant::now();
    let mut receiver = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    receiver.write_all(&chunk.bytes)?;
    receiver.sync_all()?;
    File::open(path.parent().context("receiver output has no parent")?)?.sync_all()?;
    let wall_micros = u64::try_from(started.elapsed().as_micros())?;
    let delivery_hash = Digest32::of_bytes(&chunk.bytes);
    let acknowledgement = Digest32::of_parts(&[
        b"hepta.v13.actual-file-delivery.v1\0",
        &request.digest()?,
        delivery_hash.as_array(),
    ])
    .into_array();
    let mut cost = CellTaskCostV2::new(identity)?;
    cost.record(CellCostEntryV2 {
        event_id: acknowledgement,
        identity,
        stage: CellCostStageV2::Persistence,
        outcome: CellCostOutcomeV2::Succeeded,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(wall_micros),
            storage_write_bytes: Some(u64::try_from(chunk.bytes.len())?),
            ..CellCostMetricsV2::default()
        },
    })?;
    handle.acknowledge(chunk, acknowledgement, cost).await?;
    ensure!(
        handle.pending_output().await?.is_none(),
        "delivered outbox remains unacknowledged"
    );
    Ok(delivery_hash)
}

/// Request cancellation only after observing this operation as pending. The
/// receipt records the completion race separately and never claims that an
/// observed cancellation proves a model kernel was physically preempted.
pub(super) async fn cancellation(
    handle: &NeuronGenerationRuntimeHandleV2,
    original: &CellGenerationRequestV2,
    clock: &dyn Fn() -> u64,
    output: &Path,
    identity: CellTaskCostIdentityV2,
) -> Result<Value> {
    let before = handle.snapshot().await?;
    let now = clock();
    ensure!(now > 0, "host clock is unavailable");
    let request = CellGenerationRequestV2 {
        operation_id: "v13-cancel-observation".into(),
        predecessor: before.clone(),
        admitted_at_micros: now,
        deadline_micros: now
            .checked_add(120_000_000)
            .context("request deadline overflow")?,
        ..original.clone()
    };
    let admission = handle.step(request.clone()).await;
    let (pending_observed, receipt) = match admission {
        Err(CellGenerationErrorV2::Pending) => {
            ensure!(
                handle.pending_request().await?.as_ref() == Some(&request),
                "pending operation changed before cancellation"
            );
            handle.cancel(request.digest()?).await?;
            let receipt =
                original_result(handle, &request, handle.reconcile(request.digest()?).await)
                    .await?;
            ensure!(
                receipt.disposition == CellGenerationDispositionV2::Cancelled,
                "persisted cancellation did not settle as cancelled"
            );
            let after = handle.snapshot().await?;
            ensure!(
                after.state == before.state
                    && after.prefix == before.prefix
                    && handle.pending_output().await?.is_none(),
                "cancelled proposal published output or state"
            );
            (true, receipt)
        }
        Ok(receipt) => {
            ensure!(
                receipt.disposition == CellGenerationDispositionV2::Advanced,
                "cancellation probe completed with unexpected disposition: {:?}",
                receipt.disposition
            );
            let chunk = handle
                .pending_output()
                .await?
                .context("completed cancellation probe lacks outbox")?;
            deliver(
                handle,
                &request,
                chunk,
                &output.join("CANCEL-RACE-DELIVERED.jsonl"),
                identity,
            )
            .await?;
            (false, receipt)
        }
        Err(error) => return Err(error.into()),
    };
    ensure!(
        handle.pending_request().await?.is_none(),
        "cancellation probe still pending"
    );
    Ok(serde_json::json!({
        "request": request,
        "pending_observed": pending_observed,
        "cancel_intent_persisted": pending_observed,
        "completed_before_cancel_request": !pending_observed,
        "receipt": receipt,
        "physical_model_preemption_claimed": false,
    }))
}
