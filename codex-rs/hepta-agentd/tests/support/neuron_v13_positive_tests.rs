//! A separately selected real-model qualification; never an ignored-as-pass lane.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_hepta_agent_protocol::GenerationControlRequestV1 as Request;
use codex_hepta_agent_protocol::GenerationControlResponseV1 as Response;
use codex_hepta_agent_protocol::GenerationDispositionV1;
use codex_hepta_agent_protocol::GenerationReceiptV1;
use codex_hepta_agent_protocol::GenerationStepV1;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::neuron_generation_process_identity_digest_v1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use tokio::time::sleep;
use tokio::time::timeout;

use super::Fixture;
use super::cost;
use super::positive_input;
use super::status;

fn save(path: &Path, value: &Value) -> Result<()> {
    let mut raw = serde_json::to_vec_pretty(value)?;
    raw.push(b'\n');
    save_bytes(path, &raw)
}

fn save_bytes(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

async fn settle(client: &AgentdClient, mut response: Response) -> Result<GenerationReceiptV1> {
    timeout(Duration::from_secs(125), async {
        loop {
            match response {
                Response::Receipt(receipt) => return Ok(receipt),
                Response::Pending(pending) => {
                    sleep(Duration::from_millis(10)).await;
                    response = client
                        .generation(Request::Reconcile {
                            request_digest: pending.request_digest,
                        })
                        .await?;
                }
                other => bail!("unexpected real MiniLM settlement: {other:?}"),
            }
        }
    })
    .await?
}

#[tokio::test]
#[ignore = "requires explicit pinned historical assets, interpreter, and fresh evidence directory"]
async fn ordinary_cli_runs_real_minilm_and_cold_receipt_recovery() -> Result<()> {
    let (input, digest, output) = positive_input::load()?;
    let started = Instant::now();
    save(
        &output.join("START.json"),
        &json!({
            "schema": "hepta.v13.ordinary-qualification-start.v1", "authority": "DENY_ALL",
            "input_sha256": digest.to_string(), "historical_parent_fixture_only": true,
            "task": input.task, "expected_skill": input.expected_skill, "expected_value": input.expected_value,
            "live_adoption": false, "statistical_quality_claim": false,
        }),
    )?;
    let result = execute(&input, &output).await;
    let elapsed = u64::try_from(started.elapsed().as_micros())?;
    match result {
        Ok(mut value) => {
            value["input_sha256"] = json!(digest.to_string());
            value["qualification_wall_micros"] = json!(elapsed);
            save(&output.join("RESULT.json"), &value)?;
            File::open(&output)?.sync_all()?;
            Ok(())
        }
        Err(error) => {
            save(
                &output.join("FAILURE.json"),
                &json!({
                    "schema": "hepta.v13.ordinary-qualification-failure.v1", "authority": "DENY_ALL",
                    "input_sha256": digest.to_string(), "error": format!("{error:#}"),
                    "qualification_wall_micros": elapsed, "live_adoption": false,
                }),
            )?;
            Err(error)
        }
    }
}

async fn execute(input: &positive_input::Input, output: &Path) -> Result<Value> {
    let mut fixture = Fixture::with_descriptor(|root, identity| input.descriptor(root, identity))?;
    save(&output.join("CREATE-BOOTSTRAP.json"), &fixture.descriptor)?;
    let result = exercise(&mut fixture, input, output).await;
    // Preserve actual owner bytes before the temporary Fleet harness is dropped.
    for name in ["cell.journal", "independent.witness", "control.journal"] {
        let path = fixture.root.join(name);
        if path.exists() {
            save_bytes(&output.join(name), &fs::read(path)?)?;
        }
    }
    result
}

async fn exercise(f: &mut Fixture, input: &positive_input::Input, output: &Path) -> Result<Value> {
    let config: CellGenerationConfigV2 = serde_json::from_value(f.descriptor["config"].clone())?;
    let client = f.start().await?;
    let before = status(&client).await?;
    ensure!(
        before.snapshot_digest == config.initial.digest()?,
        "ordinary genesis differs"
    );
    let request = GenerationStepV1 {
        client_operation_id: "real-minilm-fixed-new-task".into(),
        expected_snapshot_digest: before.snapshot_digest,
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        input: input.task.encode()?,
        deadline_micros: before
            .observed_at_micros
            .checked_add(120_000_000)
            .ok_or_else(|| anyhow::anyhow!("deadline overflow"))?,
    };
    let receipt = settle(
        &client,
        client
            .generation(Request::Step {
                request: Box::new(request.clone()),
            })
            .await?,
    )
    .await?;
    save(
        &output.join("FIRST-RECEIPT.json"),
        &json!({"request": request, "receipt": receipt, "cost": cost(&client).await?}),
    )?;
    ensure!(
        receipt.disposition == GenerationDispositionV1::Advanced,
        "real MiniLM did not advance: {:?}",
        receipt.disposition
    );
    let delivery = status(&client)
        .await?
        .output
        .ok_or_else(|| anyhow::anyhow!("advanced task has no durable output"))?;
    ensure!(
        delivery.request_digest == receipt.request_digest && delivery.prefix_offset == 0,
        "output is not this original task"
    );
    let Response::Output {
        delivery: actual,
        offset,
        bytes,
        complete,
    } = client
        .generation(Request::Output {
            expected_chunk_digest: delivery.chunk_digest,
            offset: 0,
            limit: 8192,
        })
        .await?
    else {
        bail!("missing actual output page")
    };
    ensure!(
        actual == delivery && offset == 0 && complete && bytes.len() == delivery.bytes as usize,
        "incomplete fixed-task output"
    );
    let observed: Value = serde_json::from_slice(&bytes)?;
    save(&output.join("OBSERVED-OUTPUT.json"), &observed)?;
    ensure!(
        observed["schema"] == "hepta.v13.task-output.v1"
            && observed["request_digest"]
                == Digest32::from_array(receipt.request_digest).to_string()
            && observed["skill"] == input.expected_skill
            && observed["value"] == input.expected_value,
        "fixed new task did not produce its preregistered result"
    );
    ensure!(
        client.generation(Request::Drain {}).await? == Response::Drain { complete: false },
        "unacknowledged output did not block drain"
    );
    ensure!(
        status(&client).await?.output == Some(delivery.clone()),
        "reading output acknowledged it"
    );
    save_bytes(&output.join("DELIVERED.jsonl"), &bytes)?;
    File::open(output)?.sync_all()?;
    let acknowledgement = Digest32::of_parts(&[
        b"hepta.v13.ordinary-file-delivery.v1\0",
        &delivery.chunk_digest,
        &bytes,
    ])
    .into_array();
    let ack = Request::Acknowledge {
        delivery,
        acknowledgement,
    };
    ensure!(
        client.generation(ack.clone()).await? == Response::Acknowledged {},
        "delivery was not acknowledged"
    );
    let acknowledged_cost = cost(&client).await?;
    ensure!(
        client.generation(ack).await? == Response::Acknowledged {}
            && cost(&client).await? == acknowledged_cost,
        "exact acknowledgement retry changed cost"
    );
    ensure!(
        client.generation(Request::Drain {}).await? == Response::Drain { complete: true },
        "acknowledged owner failed to drain"
    );
    let retained = status(&client).await?;
    let measured = cost(&client).await?;
    ensure!(
        retained.pending.is_none()
            && retained.output.is_none()
            && retained.drained
            && retained.state_bytes == 0
            && retained.prefix_bytes == bytes.len() as u32,
        "unexpected frozen state or outbox after acknowledgement"
    );
    ensure!(
        measured.communication_bytes.known_sum > 0
            && measured.cpu_micros.known_sum > 0
            && measured.wall_work_micros.known_sum > 0
            && measured.unsuccessful_entries == 0
            && measured.energy_microjoules.unknown_entries > 0,
        "missing actual worker costs or fabricated complete physical coverage"
    );
    save(
        &output.join("BEFORE-COLD-REOPEN.json"),
        &json!({"status": retained, "cost": measured}),
    )?;
    f.stop().await?;
    let original_journal = fs::read(f.root.join("cell.journal"))?;
    let original_control = fs::read(f.root.join("control.journal"))?;
    let record = f
        .harness
        .registry
        .load()?
        .agent(&f.agent.agent_id)
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("stopped agent missing"))?;
    f.identity.spawn_generation = record
        .lifecycle
        .generation
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("host generation overflow"))?;
    f.descriptor["mode"] = json!("reopen");
    f.descriptor["identity_digest"] =
        json!(neuron_generation_process_identity_digest_v1(&f.identity)?.to_string());
    save(&output.join("REOPEN-BOOTSTRAP.json"), &f.descriptor)?;
    let reopened = f.start().await?;
    ensure!(
        client.generation(Request::Status {}).await.is_err(),
        "old host client was not fenced"
    );
    let mut observed_status = status(&reopened).await?;
    ensure!(
        observed_status.observed_at_micros >= retained.observed_at_micros,
        "cold clock regressed"
    );
    observed_status.observed_at_micros = retained.observed_at_micros;
    ensure!(
        observed_status == retained,
        "cold reopen changed acknowledged state"
    );
    let prepared_journal = fs::read(f.root.join("cell.journal"))?;
    ensure!(
        prepared_journal.starts_with(&original_journal),
        "cold reopen rewrote original history"
    );
    let appended = &prepared_journal[original_journal.len()..];
    ensure!(appended.len() >= 40, "missing actual cold preparation cost");
    let length = u32::from_be_bytes(appended[..4].try_into()?) as usize;
    ensure!(
        appended.len() == length + 36,
        "cold reopen added more than one preparation event"
    );
    let event: Value = serde_json::from_slice(&appended[4..4 + length])?;
    ensure!(
        event["event"] == "cost",
        "cold reopen dispatched model work"
    );
    let preparation: CellCostEntryV2 = serde_json::from_value(event["entry"].clone())?;
    ensure!(
        preparation.identity
            == CellTaskCostIdentityV2 {
                task_digest: config.task_digest,
                source_digest: config.manifest.source_digest
            }
            && preparation.stage == CellCostStageV2::Codec
            && preparation.outcome == CellCostOutcomeV2::Succeeded
            && preparation.accounting == CellCostAccountingV2::Exclusive,
        "cold cost identity or stage differs"
    );
    let wall = preparation
        .metrics
        .wall_micros
        .ok_or_else(|| anyhow::anyhow!("cold preparation was not measured"))?;
    ensure!(
        preparation.metrics
            == CellCostMetricsV2 {
                wall_micros: Some(wall),
                ..CellCostMetricsV2::default()
            },
        "unexpected cold preparation metrics"
    );
    let observed_cost = cost(&reopened).await?;
    let mut expected_cost = measured.clone();
    ensure!(
        observed_cost.ledger_digest != expected_cost.ledger_digest,
        "cold preparation did not enter ledger"
    );
    expected_cost.ledger_digest = observed_cost.ledger_digest;
    expected_cost.wall_work_micros.known_sum += wall;
    expected_cost.exclusive_entries += 1;
    for total in [
        &mut expected_cost.cpu_micros,
        &mut expected_cost.energy_microjoules,
        &mut expected_cost.storage_read_bytes,
        &mut expected_cost.storage_write_bytes,
        &mut expected_cost.storage_byte_micros,
        &mut expected_cost.communication_bytes,
    ] {
        total.unknown_entries += 1;
    }
    ensure!(
        observed_cost == expected_cost,
        "cold costs differ from exactly one actual preparation"
    );
    ensure!(
        reopened
            .generation(Request::Step {
                request: Box::new(request.clone())
            })
            .await?
            == Response::Receipt(receipt.clone()),
        "cold original receipt differs"
    );
    ensure!(
        cost(&reopened).await? == observed_cost
            && fs::read(f.root.join("cell.journal"))? == prepared_journal
            && fs::read(f.root.join("control.journal"))? == original_control,
        "original intent readback dispatched or charged work"
    );
    f.stop().await?;
    Ok(json!({
        "schema": "hepta.v13.ordinary-qualification-result.v1", "authority": "DENY_ALL",
        "request": request, "receipt": receipt, "output": observed,
        "manifest": config.manifest, "status": retained, "cost_before_cold": measured,
        "cost_after_cold": observed_cost, "cold_preparation": preparation,
        "ordinary_cli_process_starts": 2, "original_receipt_survived_cold_restart": true,
        "acknowledged_output_survived_cold_restart": true, "cold_replay_dispatched_new_work": false,
        "actual_worker_inference_succeeded": true, "historical_parent_fixture_only": true,
        "live_adoption": false, "current_source_owner_checked": false, "training_executed": false,
        "statistical_quality_claim": false, "full_physical_cost_claim": false,
        "qualification_wall_is_inclusive_envelope": true,
    }))
}
