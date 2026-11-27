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
use tokio::time::sleep;
use tokio::time::timeout;

pub(super) async fn original_result(
    handle: &NeuronGenerationRuntimeHandleV2,
    request: &CellGenerationRequestV2,
    clock: &dyn Fn() -> u64,
    mut result: Result<CellGenerationReceiptV2, CellGenerationErrorV2>,
) -> Result<CellGenerationReceiptV2> {
    if let Ok(receipt) = result {
        return Ok(receipt);
    }
    let started = clock();
    ensure!(started > 0, "host clock is unavailable");
    let remaining = request
        .deadline_micros
        .checked_sub(started)
        .filter(|remaining| *remaining > 0)
        .context("original V13 request deadline elapsed before readback")?;
    let digest = request.digest()?;
    timeout(Duration::from_micros(remaining), async {
        loop {
            match result {
                Ok(receipt) => return Ok(receipt),
                Err(CellGenerationErrorV2::Pending) => {}
                Err(CellGenerationErrorV2::CommitUncertain) => {
                    // Control RPC timeout can leave a healthy original owner
                    // pending. A poisoned journal/witness fails this read and
                    // still requires guarded owner recovery; never redispatch.
                    ensure!(
                        handle.pending_request().await?.as_ref() == Some(request),
                        "uncertain original operation is no longer pending in the healthy owner"
                    );
                    eprintln!(
                        "{}",
                        serde_json::json!({
                            "schema": "hepta.v13.original-readback-observation.v1",
                            "operation_id": request.operation_id,
                            "request_digest": digest,
                            "observation": "healthy_original_pending_after_uncertain_response",
                        })
                    );
                }
                Err(error) => return Err(error.into()),
            }
            sleep(Duration::from_millis(5)).await;
            let now = clock();
            ensure!(
                now >= started && now < request.deadline_micros,
                "host clock left the original V13 request readback interval"
            );
            result = handle.reconcile(digest).await;
        }
    })
    .await
    .context("original V13 request remained unresolved at its original deadline")?
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
