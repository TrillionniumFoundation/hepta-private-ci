use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_arg0::Arg0DispatchPaths;
use codex_hepta_agentd::*;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde_json::Value;
use tokio::time::sleep;
use tokio::time::timeout;

use super::descriptor::Input;
use super::lifecycle::Host;
use super::lifecycle::ShutdownExpectation;
use super::lifecycle::host_config;
use super::lifecycle::ordinary_session;
use super::lifecycle::owner_files;
use super::observations::cancellation;
use super::observations::deliver;
use super::observations::original_result;

fn save(path: &Path, value: &Value) -> Result<()> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

pub(super) async fn run(
    input: Input,
    output: &Path,
    host: Host,
    arg0_paths: &Arg0DispatchPaths,
) -> Result<()> {
    let started = Instant::now();
    save(
        &output.join("START.json"),
        &serde_json::json!({
            "schema": "hepta.v13.owner-acceptance-start.v1", "authority": "DENY_ALL",
            "descriptor_sha256": input.digest.to_string(), "source_digest": input.descriptor.source_digest,
            "ordinary_runtime_requested": true, "historical_publication_is_live_authority": false,
            "included_in_junit": false,
        }),
    )?;
    let result = execute(input, output, host, arg0_paths).await;
    match result {
        Ok(mut receipt) => {
            receipt["acceptance_wall_micros"] =
                Value::from(u64::try_from(started.elapsed().as_micros())?);
            receipt["acceptance_wall_is_inclusive_envelope"] = Value::Bool(true);
            save(&output.join("RESULT.json"), &receipt)
        }
        Err(error) => {
            save(
                &output.join("FAILURE.json"),
                &serde_json::json!({
                    "schema": "hepta.v13.owner-acceptance-failure.v1", "authority": "DENY_ALL",
                    "error": format!("{error:#}"), "owners_retained": true,
                    "acceptance_wall_micros": u64::try_from(started.elapsed().as_micros())?,
                    "included_in_junit": false,
                }),
            )?;
            Err(error)
        }
    }
}

async fn execute(
    input: Input,
    output: &Path,
    host: Host,
    arg0_paths: &Arg0DispatchPaths,
) -> Result<Value> {
    let Host { registry, config } = host;
    let Input {
        descriptor,
        digest,
        files,
        retained,
    } = input;
    let prepared = prepare_agentd_v13_generation_worker_v1(
        V13GenerationProcessConfigV1 {
            interpreter_argv0: descriptor.interpreter_argv0.clone(),
            interpreter_digest: descriptor.interpreter.sha256.into_array(),
            worker_digest: descriptor.worker.sha256.into_array(),
            source_digest: descriptor.source_digest,
            device_digest: V13GenerationProcessWorkerV1::observed_device_digest()?,
            closure: descriptor.closure.clone(),
            phase_cpu_seconds: 15,
            address_space_bytes: 4 * 1024_u64.pow(3),
            wall_limit: Duration::from_secs(60),
        },
        files,
    )?;
    let task_bytes = descriptor.task.encode()?;
    let task_digest = Digest32::of_bytes(&task_bytes).into_array();
    let identity = config.identity().clone();
    let CellLearningBindingV2::Resumable { weights, .. } = &descriptor.closure.learning else {
        anyhow::bail!("complete resumable learning binding required");
    };
    let manifest = CellBackendManifestV2 {
        profile: V13GenerationProcessWorkerV1::PROFILE.into(),
        source_digest: descriptor.source_digest,
        bundle_digest: prepared.worker().bundle_digest(),
        runtime_digest: prepared.worker().runtime_digest(),
        device_digest: V13GenerationProcessWorkerV1::observed_device_digest()?,
        encoder: Some(descriptor.closure.encoder_digest),
        head: Some(*weights),
        memory: None,
        world_model: None,
        decoder: None,
        input_schema: V13GenerationProcessWorkerV1::input_schema_digest(),
        state_schema: V13GenerationProcessWorkerV1::state_schema_digest(),
        output_schema: V13GenerationProcessWorkerV1::output_schema_digest(),
        learning: descriptor.closure.learning.clone(),
        evolution: descriptor.evolution.clone(),
        max_input_bytes: 8192,
        max_state_bytes: 1,
        max_delta_bytes: 65_536,
        max_prefix_bytes: 65_536,
        max_step_cost_entries: 8,
        max_ack_cost_entries: 1,
    };
    let mut admission = AgentdV13GenerationBootstrapConfigV1 {
        expected_identity_digest: neuron_generation_process_identity_digest_v1(&identity)?,
        expected_boot_id_digest: prepared.boot_id_digest(),
        generation: CellGenerationConfigV2 {
            initial: CellRuntimeSnapshotV2 {
                scope: CellGenerationScopeV2 {
                    principal_digest: Digest32::of_parts(&[
                        b"hepta.v13.local-acceptance-principal.v1\0",
                        digest.as_array(),
                    ])
                    .into_array(),
                    agent_id: identity.agent_id.to_string(),
                    cell_id: "v13-pinned-task".into(),
                    run_id: digest.to_string(),
                },
                manifest_digest: manifest.digest()?,
                generation: 1,
                writer_epoch: 1,
                revision: 0,
                state: Vec::new(),
                prefix: Vec::new(),
                stopped: false,
            },
            manifest,
            source_frontier: descriptor.closure.source_version,
            task_digest,
        },
        max_records: 128,
        control_capacity: 16,
        queue_capacity: 4,
        rpc_timeout: Duration::from_secs(1),
    };
    let (handle, bootstrap) = bootstrap_agentd_v13_generation_v1(
        &identity,
        admission.clone(),
        owner_files(output, V13GenerationOwnerModeV1::InitializeEmpty, &retained)?,
        V13GenerationOwnerModeV1::InitializeEmpty,
        &prepared,
    )?;
    let config = config.with_neuron_generation_bootstrap(bootstrap)?;
    let first = ordinary_session(
        config,
        arg0_paths,
        &registry,
        ShutdownExpectation::UnacknowledgedOutput,
        || async {
            let now = (prepared.worker().clock())();
            ensure!(now > 0, "host clock is unavailable");
            let request = CellGenerationRequestV2 {
                operation_id: "v13-new-task".into(),
                task_digest,
                source_frontier: descriptor.closure.source_version,
                predecessor: handle.snapshot().await?,
                input: task_bytes.clone(),
                admitted_at_micros: now,
                deadline_micros: now
                    .checked_add(120_000_000)
                    .context("request deadline overflow")?,
            };
            let receipt = original_result(
                &handle,
                &request,
                prepared.worker().clock().as_ref(),
                handle.step(request.clone()).await,
            )
            .await?;
            ensure!(
                receipt.disposition == CellGenerationDispositionV2::Advanced,
                "original V13 task did not succeed: {:?}",
                receipt.disposition
            );
            let chunk = handle
                .pending_output()
                .await?
                .ok_or_else(|| anyhow::anyhow!("successful task has no durable outbox"))?;
            ensure!(
                !chunk.bytes.is_empty() && !handle.drain().await?,
                "unacknowledged output must block drain"
            );
            let snapshot = handle.snapshot().await?;
            let cost = handle.task_cost().await?;
            save(
                &output.join("UNACKNOWLEDGED.json"),
                &serde_json::json!({
                    "request": request, "receipt": receipt, "snapshot": snapshot,
                    "outbox": chunk, "task_cost": cost, "delivered": false,
                }),
            )?;
            Ok((request, receipt, snapshot, cost, chunk))
        },
    )
    .await?;
    let (request, receipt, before_reopen, before_reopen_cost, chunk) = first.value;
    save(
        &output.join("FIRST-SHUTDOWN.json"),
        &serde_json::json!({
            "observed_error": first.shutdown_error, "runtime_tasks_joined": true,
            "generation_drain_completed": false, "delivery_acknowledged": false,
        }),
    )?;
    drop(handle);
    let control_before = fs::read(output.join("control.journal"))?;
    registry.compare_and_transition(
        &identity.agent_id,
        /*expected_generation*/ 4,
        AgentLifecycle::Starting,
    )?;
    let config = host_config(&identity, /*spawn*/ 5)?;
    config.require_neuron_generation_profile()?;
    let reopened_identity = config.identity().clone();
    admission.expected_identity_digest =
        neuron_generation_process_identity_digest_v1(&reopened_identity)?;
    let (handle, bootstrap) = timeout(Duration::from_secs(5), async {
        loop {
            match bootstrap_agentd_v13_generation_v1(
                &reopened_identity,
                admission.clone(),
                owner_files(output, V13GenerationOwnerModeV1::Reopen, &retained)?,
                V13GenerationOwnerModeV1::Reopen,
                &prepared,
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
    let config = config.with_neuron_generation_bootstrap(bootstrap)?;
    let second = ordinary_session(
        config,
        arg0_paths,
        &registry,
        ShutdownExpectation::Drained,
        || async {
            ensure!(
                handle.snapshot().await? == before_reopen
                    && handle.task_cost().await? == before_reopen_cost,
                "reopen changed the original snapshot or charged preparation twice"
            );
            ensure!(
                handle.pending_output().await?.as_ref() == Some(&chunk),
                "reopen lost or changed the unacknowledged output"
            );
            ensure!(
                handle.step(request.clone()).await? == receipt,
                "reopen changed original result"
            );
            ensure!(
                fs::read(output.join("control.journal"))? == control_before,
                "readback dispatched new computation"
            );
            ensure!(
                !handle.drain().await?,
                "unacknowledged reopened output did not block drain"
            );
            let delivery_hash = deliver(
                &handle,
                &request,
                chunk.clone(),
                &output.join("DELIVERED.jsonl"),
                before_reopen_cost.identity(),
            )
            .await?;
            ensure!(handle.drain().await?, "acknowledged owner did not drain");
            handle.resume().await?;
            let cancellation = cancellation(
                &handle,
                &request,
                prepared.worker().clock().as_ref(),
                output,
                before_reopen_cost.identity(),
            )
            .await?;
            ensure!(
                handle.drain().await?,
                "settled cancellation owner did not drain"
            );
            Ok((
                delivery_hash,
                cancellation,
                handle.snapshot().await?,
                handle.task_cost().await?,
            ))
        },
    )
    .await?;
    let (delivery_hash, cancellation, snapshot, cost) = second.value;
    drop(handle);
    let preparation = prepared.worker().preparation_cost(cost.identity())?;
    ensure!(
        cost.entries()
            .iter()
            .filter(|entry| entry.event_id == preparation.event_id)
            .count()
            == 1,
        "preparation receipt is missing or duplicated"
    );
    Ok(serde_json::json!({
        "schema": "hepta.v13.owner-acceptance-result.v1", "authority": "DENY_ALL",
        "descriptor_sha256": digest.to_string(), "source_digest": descriptor.source_digest,
        "manifest": admission.generation.manifest, "closure": descriptor.closure,
        "identity_digests": [neuron_generation_process_identity_digest_v1(&identity)?.to_string(),
            neuron_generation_process_identity_digest_v1(&reopened_identity)?.to_string()],
        "task": descriptor.task, "task_digest": task_digest, "request": request, "receipt": receipt,
        "snapshot_before_reopen": before_reopen, "task_cost_before_reopen": before_reopen_cost,
        "snapshot": snapshot, "task_cost": cost, "delivered_sha256": delivery_hash.to_string(),
        "cancellation_observation": cancellation, "ordinary_runtime_attempts": 2,
        "first_shutdown_error": first.shutdown_error, "second_shutdown_error": second.shutdown_error,
        "real_app_server_readiness": true, "unacknowledged_outbox_survived_reopen": true,
        "cold_original_result_readback": true, "preparation_recorded_once": true,
        "historical_publication_is_live_authority": false, "current_source_owner_checked": false,
        "live_adoption": false, "cli_model_selection_added": false, "included_in_junit": false,
        "storage_root_rollback_qualified": false,
    }))
}
