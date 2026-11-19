//! Real isolated owner lifecycle; every result is sampled from actual owners.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_arg0::Arg0DispatchPaths;
use codex_hepta_agentd::NeuronGenerationRuntimeHandleV2;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde::Serialize;
use serde_json::Value;

use super::lifecycle::Host;
use super::observations::deliver;
use super::observations::original_result;

#[path = "artifacts.rs"]
mod artifacts;
#[path = "assembly.rs"]
mod assembly;
#[path = "authority.rs"]
mod authority;
#[path = "flow.rs"]
mod flow;

use assembly::Assets;

fn directory(path: &Path) -> Result<()> {
    ensure!(
        path.is_absolute() && path.file_name().is_some(),
        "directory must be absolute and new"
    );
    let parent = path.parent().context("directory parent missing")?;
    ensure!(
        parent.canonicalize()? == parent,
        "directory parent must be canonical"
    );
    fs::DirBuilder::new().mode(0o700).create(path)?;
    File::open(parent)?.sync_all()?;
    Ok(())
}

fn save(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    File::open(path.parent().context("result parent missing")?)?.sync_all()?;
    Ok(())
}

pub(super) struct Inputs {
    pub descriptor: PathBuf,
    pub expected: Digest32,
    pub output: PathBuf,
    pub root_authority: PathBuf,
    pub second_task: PathBuf,
    pub task_sha: Digest32,
}

pub(super) async fn run(inputs: Inputs, host: Host, arg0_paths: &Arg0DispatchPaths) -> Result<()> {
    let output = &inputs.output;
    save(
        &output.join("START.json"),
        &serde_json::json!({
            "schema": "hepta.v13.guarded-qualification-start.v1", "authority": "DENY_ALL",
            "descriptor_sha256": inputs.expected.to_string(), "second_task_sha256": inputs.task_sha.to_string(),
            "public_fixture_issuers": true, "included_in_junit": false,
        }),
    )?;
    let started = Instant::now();
    let result = flow::execute(&inputs, host, arg0_paths).await;
    match result {
        Ok(mut value) => {
            value["wall_micros"] = Value::from(u64::try_from(started.elapsed().as_micros())?);
            save(&output.join("RESULT.json"), &value)
        }
        Err(error) => {
            save(
                &output.join("FAILURE.json"),
                &serde_json::json!({
                    "schema": "hepta.v13.guarded-qualification-failure.v1", "authority": "DENY_ALL",
                    "error": format!("{error:#}"), "owners_retained": true,
                    "wall_micros": u64::try_from(started.elapsed().as_micros())?,
                }),
            )?;
            Err(error)
        }
    }
}

#[derive(Serialize)]
struct TaskResult {
    request: CellGenerationRequestV2,
    receipt: CellGenerationReceiptV2,
    observation: CellGenerationObservationV1,
    outbox: CellOutputChunkV2,
}

async fn task(
    handle: &NeuronGenerationRuntimeHandleV2,
    assets: &Assets,
    config: &CellGenerationConfigV2,
    input: &V13TaskInputV1,
    operation: &str,
) -> Result<TaskResult> {
    let now = (assets.prepared.worker().clock())();
    ensure!(now > 0, "host clock is unavailable");
    let request = CellGenerationRequestV2 {
        operation_id: operation.into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: handle.snapshot().await?,
        input: input.encode()?,
        admitted_at_micros: now,
        deadline_micros: now.checked_add(120_000_000).context("deadline overflow")?,
    };
    let receipt = original_result(
        handle,
        &request,
        assets.prepared.worker().clock().as_ref(),
        handle.step(request.clone()).await,
    )
    .await?;
    ensure!(
        receipt.disposition == CellGenerationDispositionV2::Advanced,
        "actual V13 inference did not advance: {:?}",
        receipt.disposition
    );
    let outbox = handle
        .pending_output()
        .await?
        .context("successful task has no outbox")?;
    ensure!(
        !outbox.bytes.is_empty() && !handle.drain().await?,
        "unacknowledged output did not block drain"
    );
    let observation = handle.observe_generation().await?;
    Ok(TaskResult {
        request,
        receipt,
        observation,
        outbox,
    })
}

async fn acknowledge(
    handle: &NeuronGenerationRuntimeHandleV2,
    result: &TaskResult,
    path: &Path,
) -> Result<(Digest32, CellGenerationObservationV1)> {
    let digest = deliver(
        handle,
        &result.request,
        result.outbox.clone(),
        path,
        result.observation.cost().identity(),
    )
    .await?;
    ensure!(handle.drain().await?, "acknowledged owner did not drain");
    Ok((digest, handle.observe_generation().await?))
}

fn owner_bytes(path: &Path) -> Result<[Vec<u8>; 3]> {
    Ok([
        fs::read(path.join("cell.journal"))?,
        fs::read(path.join("independent.witness"))?,
        fs::read(path.join("control.journal"))?,
    ])
}
