#![cfg(target_os = "linux")]
//! Real Supervisor -> Agentd CLI -> shared bounded control -> actual V13 Python.
//! Invalid closure assets must fail; this suite makes no positive quality claim.

#[path = "support/neuron_v13_generation.rs"]
mod fixture;
#[path = "support/neuron_v13_positive_input.rs"]
mod positive_input;
#[path = "support/neuron_v13_positive_tests.rs"]
mod real_minilm;
mod support;

use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_hepta_agent_protocol::GenerationControlRequestV1 as Request;
use codex_hepta_agent_protocol::GenerationControlResponseV1 as Response;
use codex_hepta_agent_protocol::GenerationCostSummaryV1;
use codex_hepta_agent_protocol::GenerationDispositionV1;
use codex_hepta_agent_protocol::GenerationReceiptV1;
use codex_hepta_agent_protocol::GenerationStatusV1;
use codex_hepta_agent_protocol::GenerationStepV1;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::load_neuron_generation_process_bootstrap_v1;
use codex_hepta_agentd::neuron_generation_process_identity_digest_v1;
use codex_hepta_neuron::*;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::time::sleep;
use tokio::time::timeout;

use support::fleet::AgentFixture;
use support::fleet::FleetHarness;
use support::fleet::agentd_binary;

struct Fixture {
    _directory: tempfile::TempDir,
    root: PathBuf,
    path: PathBuf,
    descriptor: Value,
    identity: AgentdIdentity,
    harness: FleetHarness,
    agent: AgentFixture,
}

impl Fixture {
    fn new() -> Result<Self> {
        Self::with_descriptor(fixture::descriptor)
    }

    fn with_descriptor(
        descriptor: impl FnOnce(&Path, &AgentdIdentity) -> Result<Value>,
    ) -> Result<Self> {
        let mut harness = FleetHarness::new()?;
        let agent = harness.register("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12", "v13-entry")?;
        let record = harness
            .registry
            .load()?
            .agent(&agent.agent_id)
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("registered agent missing"))?;
        let identity = AgentdIdentity {
            agent_id: agent.agent_id.clone(),
            layout: agent.layout.clone(),
            spawn_generation: 1,
            fleet_root: harness
                .registry
                .layout()
                .fleet_root()
                .as_path()
                .to_path_buf(),
            workspace: agent.workspace.clone(),
            resources: record.manifest.resources,
            home_root: agent.layout.home_root().into(),
            run_root: agent.layout.run_root().into(),
            control_socket: agent.layout.agentd_control_socket().into(),
            app_server_socket: agent.layout.app_server_socket().into(),
        };
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let descriptor = descriptor(&root, &identity)?;
        Ok(Self {
            _directory: directory,
            path: root.join("bootstrap.json"),
            root,
            descriptor,
            identity,
            harness,
            agent,
        })
    }

    async fn start(&mut self) -> Result<AgentdClient> {
        let bytes = serde_json::to_vec(&self.descriptor)?;
        fs::write(&self.path, &bytes)?;
        self.harness.start_command(
            &self.agent,
            AgentCommand::new(
                agentd_binary()?,
                vec![
                    "--neuron-generation-bootstrap-descriptor".into(),
                    self.path.as_os_str().to_owned(),
                    "--neuron-generation-bootstrap-descriptor-digest".into(),
                    Digest32::of_bytes(&bytes).to_string().into(),
                ],
            )?,
        )?;
        let (client, health) = self
            .harness
            .wait_ready(&self.agent, self.identity.spawn_generation)
            .await?;
        assert!(health.ready && !health.fenced);
        Ok(client)
    }

    async fn stop(&mut self) -> Result<()> {
        self.harness
            .supervisor
            .stop(&self.agent.agent_id, Instant::now())?;
        timeout(Duration::from_secs(15), async {
            loop {
                let report = self.harness.supervisor.tick(Instant::now());
                ensure!(
                    report.faults.is_empty(),
                    "shutdown faults: {:?}",
                    report.faults
                );
                if self
                    .harness
                    .supervisor
                    .snapshot(&self.agent.agent_id)
                    .is_some_and(|s| !s.active)
                {
                    return Ok::<_, anyhow::Error>(());
                }
                sleep(Duration::from_millis(25)).await;
            }
        })
        .await??;
        Ok(())
    }
}

#[test]
fn ordinary_v13_loader_refuses_incompatible_pins_and_owners_before_creation() -> Result<()> {
    let f = Fixture::new()?;
    let bytes = serde_json::to_vec(&f.descriptor)?;
    fs::write(&f.path, &bytes)?;
    for digest in [Digest32::ZERO, Digest32::of_bytes(b"another descriptor")] {
        assert!(load_neuron_generation_process_bootstrap_v1(&f.path, digest, &f.identity).is_err());
    }
    for (pointer, value) in [
        (
            "/schema",
            json!("hepta.agentd.neuron-v13-generation-bootstrap.v2"),
        ),
        ("/config/manifest/profile", json!("unknown-v13-profile")),
        ("/config/manifest/runtime_digest", json!(vec![99; 32])),
        ("/config/source_frontier", json!(vec![99; 32])),
        ("/config/initial/state", json!([1])),
        ("/identity_digest", json!("f".repeat(64))),
        ("/boot_id", json!("00000000-0000-0000-0000-000000000000")),
        ("/max_records", json!(7)),
        ("/queue_capacity", json!(0)),
        ("/worker/digest", json!("f".repeat(64))),
        ("/interpreter/digest", json!("f".repeat(64))),
        ("/assets/0/digest", json!("f".repeat(64))),
        ("/assets/0/name", json!("unrecognized-asset")),
        ("/assets/0/path", f.descriptor["assets"][1]["path"].clone()),
        ("/closure/checkpoint_digest", json!(vec![99; 32])),
        ("/journal_path", f.descriptor["worker"]["path"].clone()),
        ("/mode", json!("reopen")),
        ("/assets", json!([])),
    ] {
        let mut altered = f.descriptor.clone();
        *altered
            .pointer_mut(pointer)
            .ok_or_else(|| anyhow::anyhow!("missing {pointer}"))? = value;
        let bytes = serde_json::to_vec(&altered)?;
        fs::write(&f.path, &bytes)?;
        assert!(
            load_neuron_generation_process_bootstrap_v1(
                &f.path,
                Digest32::of_bytes(&bytes),
                &f.identity
            )
            .is_err(),
            "{pointer}"
        );
        for name in ["cell.journal", "independent.witness", "control.journal"] {
            assert!(!f.root.join(name).exists(), "{pointer} created {name}");
        }
    }
    // A correct pin must cover the original bytes, including unknown fields.
    let mut extra = f.descriptor.clone();
    extra["automatic_fallback"] = json!(true);
    let extra = serde_json::to_vec(&extra)?;
    fs::write(&f.path, &extra)?;
    assert!(
        load_neuron_generation_process_bootstrap_v1(
            &f.path,
            Digest32::of_bytes(&extra),
            &f.identity
        )
        .is_err()
    );
    fs::write(&f.path, &bytes)?;
    fs::write(
        f.root.join("invalid-asset-0"),
        b"changed after descriptor pin",
    )?;
    assert!(
        load_neuron_generation_process_bootstrap_v1(
            &f.path,
            Digest32::of_bytes(&bytes),
            &f.identity
        )
        .is_err()
    );
    for name in ["cell.journal", "independent.witness", "control.journal"] {
        assert!(!f.root.join(name).exists());
    }
    Ok(())
}

async fn status(client: &AgentdClient) -> Result<GenerationStatusV1> {
    match client.generation(Request::Status {}).await? {
        Response::Status(value) => Ok(*value),
        other => bail!("expected status, got {other:?}"),
    }
}

async fn cost(client: &AgentdClient) -> Result<GenerationCostSummaryV1> {
    match client.generation(Request::Cost {}).await? {
        Response::Cost(value) => Ok(*value),
        other => bail!("expected cost, got {other:?}"),
    }
}

async fn settle(client: &AgentdClient, mut response: Response) -> Result<GenerationReceiptV1> {
    timeout(Duration::from_secs(20), async {
        loop {
            match response {
                Response::Receipt(receipt) => return Ok(receipt),
                Response::Pending(pending) => {
                    sleep(Duration::from_millis(5)).await;
                    response = client
                        .generation(Request::Reconcile {
                            request_digest: pending.request_digest,
                        })
                        .await?;
                }
                other => bail!("unexpected settlement {other:?}"),
            }
        }
    })
    .await?
}

#[tokio::test]
async fn ordinary_cli_runs_v13_rejection_cancel_and_cold_intent_recovery() -> Result<()> {
    let mut f = Fixture::new()?;
    let config: CellGenerationConfigV2 = serde_json::from_value(f.descriptor["config"].clone())?;
    let client = f.start().await?;
    let before = status(&client).await?;
    assert_eq!(before.snapshot_digest, config.initial.digest()?);
    let request = GenerationStepV1 {
        client_operation_id: "real-v13-rejection".into(),
        expected_snapshot_digest: before.snapshot_digest,
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        input: V13TaskInputV1 {
            schema: "hepta.v13.task-input.v1".into(),
            text: "Sort these new caller numbers".into(),
            payload: json!([3, 1, 2]),
        }
        .encode()?,
        deadline_micros: before.observed_at_micros + 20_000_000,
    };
    let response = client
        .generation(Request::Step {
            request: Box::new(request.clone()),
        })
        .await?;
    let rejected = settle(&client, response).await?;
    assert_eq!(rejected.disposition, GenerationDispositionV1::Rejected);
    let measured = cost(&client).await?;
    assert!(measured.communication_bytes.known_sum > 0 && measured.unsuccessful_entries > 0);
    assert!(measured.energy_microjoules.unknown_entries > 0);
    assert_eq!(
        client
            .generation(Request::Step {
                request: Box::new(request.clone())
            })
            .await?,
        Response::Receipt(rejected.clone())
    );
    assert_eq!(cost(&client).await?, measured);

    let before_cancel = status(&client).await?;
    let cancelled_request = GenerationStepV1 {
        client_operation_id: "v13-cancel-intent".into(),
        expected_snapshot_digest: before_cancel.snapshot_digest,
        deadline_micros: before_cancel.observed_at_micros + 20_000_000,
        ..request.clone()
    };
    let pending = client
        .generation(Request::Step {
            request: Box::new(cancelled_request.clone()),
        })
        .await?;
    let Response::Pending(pending) = pending else {
        bail!("fresh V13 dispatch did not remain pending")
    };
    assert_eq!(
        client
            .generation(Request::Cancel {
                request_digest: pending.request_digest
            })
            .await?,
        Response::CancelRequested {}
    );
    let cancelled = settle(&client, Response::Pending(pending)).await?;
    // Cancellation is intent, never a rewrite of an already completed rejection.
    assert!(matches!(
        cancelled.disposition,
        GenerationDispositionV1::Cancelled | GenerationDispositionV1::Rejected
    ));
    assert_eq!(
        client.generation(Request::Drain {}).await?,
        Response::Drain { complete: true }
    );
    let retained = status(&client).await?;
    assert_eq!(
        (
            retained.state_bytes,
            retained.prefix_bytes,
            &retained.pending,
            &retained.output
        ),
        (0, 0, &None, &None)
    );
    let measured = cost(&client).await?;
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
    let reopened = f.start().await?;
    assert!(client.generation(Request::Status {}).await.is_err());
    let mut observed = status(&reopened).await?;
    assert!(observed.observed_at_micros >= retained.observed_at_micros);
    observed.observed_at_micros = retained.observed_at_micros;
    assert_eq!(observed, retained);
    let prepared_journal = fs::read(f.root.join("cell.journal"))?;
    ensure!(
        prepared_journal.starts_with(&original_journal),
        "reopen rewrote journal history"
    );
    let appended = &prepared_journal[original_journal.len()..];
    ensure!(appended.len() >= 40, "missing cold preparation cost");
    let length = u32::from_be_bytes(appended[..4].try_into()?) as usize;
    assert_eq!(appended.len(), length + 36);
    let event: Value = serde_json::from_slice(&appended[4..4 + length])?;
    assert_eq!(event["event"], "cost");
    let preparation: CellCostEntryV2 = serde_json::from_value(event["entry"].clone())?;
    assert_eq!(
        preparation.identity,
        CellTaskCostIdentityV2 {
            task_digest: config.task_digest,
            source_digest: config.manifest.source_digest,
        }
    );
    assert_eq!(preparation.stage, CellCostStageV2::Codec);
    assert_eq!(preparation.outcome, CellCostOutcomeV2::Succeeded);
    assert_eq!(preparation.accounting, CellCostAccountingV2::Exclusive);
    let wall = preparation
        .metrics
        .wall_micros
        .ok_or_else(|| anyhow::anyhow!("unmeasured preparation"))?;
    assert_eq!(
        preparation.metrics,
        CellCostMetricsV2 {
            wall_micros: Some(wall),
            ..CellCostMetricsV2::default()
        }
    );
    let observed_cost = cost(&reopened).await?;
    assert_ne!(observed_cost.ledger_digest, measured.ledger_digest);
    let mut expected_cost = measured;
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
    assert_eq!(observed_cost, expected_cost);
    for (request, receipt) in [(request, rejected), (cancelled_request, cancelled)] {
        assert_eq!(
            reopened
                .generation(Request::Step {
                    request: Box::new(request)
                })
                .await?,
            Response::Receipt(receipt)
        );
    }
    assert_eq!(cost(&reopened).await?, observed_cost);
    assert_eq!(fs::read(f.root.join("cell.journal"))?, prepared_journal);
    assert_eq!(fs::read(f.root.join("control.journal"))?, original_control);
    f.stop().await?;
    Ok(())
}
