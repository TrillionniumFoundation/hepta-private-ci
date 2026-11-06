#![cfg(target_os = "linux")]
//! Real Supervisor -> Agentd main -> ordinary runtime -> private control socket
//! -> Joint process. Artificial legal weights qualify wiring, not trained quality.

mod support;

use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_hepta_agent_protocol::AGENTD_GENERATION_CONTROL_CAPABILITY;
use codex_hepta_agent_protocol::GenerationControlRequestV1 as Request;
use codex_hepta_agent_protocol::GenerationControlResponseV1 as Response;
use codex_hepta_agent_protocol::GenerationDispositionV1;
use codex_hepta_agent_protocol::GenerationReceiptV1;
use codex_hepta_agent_protocol::GenerationStatusV1;
use codex_hepta_agent_protocol::GenerationStepV1;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::neuron_generation_process_identity_digest_v1;
use codex_hepta_neuron::*;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use tokio::time::sleep;
use tokio::time::timeout;

use support::fleet::FleetHarness;
use support::fleet::agentd_binary;

#[path = "support/neuron_generation.rs"]
mod fixture;

async fn status(client: &AgentdClient) -> Result<GenerationStatusV1> {
    match client.generation(Request::Status).await? {
        Response::Status(value) => Ok(*value),
        other => bail!("expected generation status, got {other:?}"),
    }
}

async fn compute(
    client: &AgentdClient,
    config: &CellGenerationConfigV2,
    public_digest: [u8; 32],
    id: &str,
    command: JointGenerationCommandV1,
) -> Result<(GenerationStepV1, GenerationReceiptV1)> {
    let before = status(client).await?;
    let request = GenerationStepV1 {
        client_operation_id: id.into(),
        expected_snapshot_digest: before.snapshot_digest,
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        input: serde_json::to_vec(&JointGenerationInputV1 {
            public_digest,
            command,
        })?,
        deadline_micros: before.observed_at_micros + 30_000_000,
    };
    let first = client
        .generation(Request::Step {
            request: Box::new(request.clone()),
        })
        .await?;
    let receipt = timeout(Duration::from_secs(30), async {
        let mut response = first;
        loop {
            match response {
                Response::Receipt(value) => return Ok(value),
                Response::Pending(pending) => {
                    sleep(Duration::from_millis(5)).await;
                    response = client
                        .generation(Request::Reconcile {
                            request_digest: pending.request_digest,
                        })
                        .await?;
                }
                other => bail!("unexpected computation response: {other:?}"),
            }
        }
    })
    .await??;
    assert_eq!(
        client
            .generation(Request::Step {
                request: Box::new(request.clone())
            })
            .await?,
        Response::Receipt(receipt.clone())
    );
    Ok((request, receipt))
}

async fn deliver(client: &AgentdClient, destination: &Path) -> Result<()> {
    let delivery = status(client)
        .await?
        .output
        .ok_or_else(|| anyhow::anyhow!("missing durable outbox"))?;
    let mut observed = Vec::new();
    while observed.len() < delivery.bytes as usize {
        let offset = observed.len() as u32;
        let page = Request::Output {
            expected_chunk_digest: delivery.chunk_digest,
            offset,
            limit: 1024,
        };
        let response = client.generation(page.clone()).await?;
        assert_eq!(client.generation(page).await?, response);
        match response {
            Response::Output {
                delivery: original,
                offset: actual,
                bytes,
                complete,
            } => {
                assert_eq!(original, delivery);
                assert_eq!(actual, offset);
                ensure!(
                    !bytes.is_empty() && bytes.len() <= 1024,
                    "unbounded or stalled page"
                );
                observed.extend(bytes);
                assert_eq!(complete, observed.len() == delivery.bytes as usize);
            }
            other => bail!("unexpected output page: {other:?}"),
        }
    }
    // Reading all pages did not acknowledge anything. The receiver writes and
    // syncs the actual bytes before sending the exact whole-chunk receipt.
    assert_eq!(status(client).await?.output, Some(delivery.clone()));
    let mut sink = OpenOptions::new()
        .create(true)
        .append(true)
        .open(destination)?;
    assert_eq!(sink.metadata()?.len(), delivery.prefix_offset);
    sink.write_all(&observed)?;
    sink.sync_all()?;
    let acknowledgement = Digest32::of_parts(&[
        b"synthetic-file-delivery.v1\0",
        &delivery.chunk_digest,
        &fs::read(destination)?,
    ])
    .into_array();
    let ack = Request::Acknowledge {
        delivery,
        acknowledgement,
    };
    assert_eq!(
        client.generation(ack.clone()).await?,
        Response::Acknowledged
    );
    assert_eq!(client.generation(ack).await?, Response::Acknowledged);
    assert_eq!(status(client).await?.output, None);
    Ok(())
}

fn last_committed_state(path: &Path) -> Result<Vec<u8>> {
    let bytes = fs::read(path)?;
    ensure!(
        bytes.len() >= 40 && bytes.len() <= 2 * 1024 * 1024,
        "fixture journal bound"
    );
    ensure!(&bytes[..8] == b"HPTACG02", "unexpected journal family");
    let mut offset = 40;
    let mut state = None;
    while offset < bytes.len() {
        ensure!(offset + 4 <= bytes.len(), "short journal size");
        let count = u32::from_be_bytes(bytes[offset..offset + 4].try_into()?) as usize;
        let end = offset + count + 36;
        ensure!(count > 0 && end <= bytes.len(), "short journal frame");
        let event: serde_json::Value = serde_json::from_slice(&bytes[offset + 4..end - 32])?;
        if event["event"] == "commit" {
            let proposal: CellGenerationProposalV2 =
                serde_json::from_value(event["proposal"].clone())?;
            state = Some(proposal.successor_state);
        }
        offset = end;
    }
    state.ok_or_else(|| anyhow::anyhow!("missing actual committed proposal"))
}

#[tokio::test]
async fn ordinary_cli_runs_joint_over_bounded_control_and_retains_delivered_state() -> Result<()> {
    let mut harness = FleetHarness::new()?;
    let agent = harness.register("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12", "joint-normal-entry")?;
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
    let (descriptor, assets) = fixture::descriptor(&root, &identity)?;
    let path = root.join("generation-bootstrap.json");
    let digest = fixture::write_descriptor(&path, &descriptor)?;
    let config: CellGenerationConfigV2 = serde_json::from_value(descriptor["config"].clone())?;
    let public_digest = descriptor["public"]["digest"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("public digest"))?
        .parse::<Digest32>()?
        .into_array();
    harness.start_command(
        &agent,
        AgentCommand::new(
            agentd_binary()?,
            vec![
                "--neuron-generation-bootstrap-descriptor".into(),
                path.into_os_string(),
                "--neuron-generation-bootstrap-descriptor-digest".into(),
                digest.to_string().into(),
            ],
        )?,
    )?;
    let (client, health) = harness.wait_ready(&agent, 1).await?;
    assert!(health.ready && !health.fenced);
    let capabilities = client.capabilities().await?;
    assert_eq!(
        capabilities
            .capabilities
            .iter()
            .find(|capability| capability.id == AGENTD_GENERATION_CONTROL_CAPABILITY)
            .map(|capability| (capability.major, capability.minor)),
        Some((1, 0))
    );
    let initial = status(&client).await?;
    assert_eq!(initial.snapshot_digest, config.initial.digest()?);
    compute(
        &client,
        &config,
        public_digest,
        "init",
        JointGenerationCommandV1::Init {
            seed: 17,
            sampler: JointGenerationSamplerV1::Mean,
        },
    )
    .await?;
    compute(
        &client,
        &config,
        public_digest,
        "shared",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Shared,
        },
    )
    .await?;
    compute(
        &client,
        &config,
        public_digest,
        "audio",
        JointGenerationCommandV1::Commit {
            modality: JointGenerationModalityV1::Audio,
            units: 16,
        },
    )
    .await?;
    let destination = root.join("delivered-prefix.bin");
    deliver(&client, &destination).await?;
    let (_, stopped) = compute(
        &client,
        &config,
        public_digest,
        "stop",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Stop,
        },
    )
    .await?;
    assert_eq!(stopped.disposition, GenerationDispositionV1::Stopped);
    let snapshot = status(&client).await?;
    assert!(snapshot.stopped && snapshot.state_bytes > 0 && snapshot.prefix_bytes > 1024);
    assert_eq!(
        client.generation(Request::Drain).await?,
        Response::Drain { complete: false }
    );
    deliver(&client, &destination).await?;
    assert_eq!(
        client.generation(Request::Drain).await?,
        Response::Drain { complete: true }
    );
    match client.generation(Request::Cost).await? {
        Response::Cost(cost) => {
            assert_eq!(cost.task_digest, config.task_digest);
            assert!(cost.wall_work_micros.known_sum > 0);
            assert!(
                cost.cpu_micros.unknown_entries > 0 && cost.energy_microjoules.unknown_entries > 0
            );
        }
        other => bail!("expected actual cost summary: {other:?}"),
    }
    harness.supervisor.stop(&agent.agent_id, Instant::now())?;
    timeout(Duration::from_secs(15), async {
        loop {
            let report = harness.supervisor.tick(Instant::now());
            ensure!(
                report.faults.is_empty(),
                "shutdown faults: {:?}",
                report.faults
            );
            if harness
                .supervisor
                .snapshot(&agent.agent_id)
                .is_some_and(|s| !s.active)
            {
                break;
            }
            sleep(Duration::from_millis(25)).await;
        }
        Ok::<_, anyhow::Error>(())
    })
    .await??;
    let delivered = fs::read(destination)?;
    assert_eq!(delivered.len(), snapshot.prefix_bytes as usize);
    fixture::verify_stopped(
        &last_committed_state(&root.join("cell.journal"))?,
        &delivered,
        &assets,
    )?;
    ensure!(
        fs::metadata(root.join("independent.witness"))?.len() > 0,
        "missing separate witness"
    );
    Ok(())
}
