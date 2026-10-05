#![cfg(unix)]

use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agentd::AgentContextAttachment;
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunSnapshot;
use codex_hepta_agentd::AgentdPayload;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_agentd::AgentdResponse;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;

mod support;

use support::fleet::FleetHarness;

// Real Agentd and App Server processes, real fleet/SQLite owners and public
// control ingress. These compatibility lifecycle receipts do not establish
// physical Codex turn execution or authenticated cross-restart recovery.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn real_app_server_drain_cannot_hide_unresolved_agentd_runs() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12", "run-drain")?;
    fleet.start(&agent)?;
    let (client, _health) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    let generation = fleet
        .registry
        .load()?
        .agent(&agent.agent_id)
        .context("registered Agent disappeared")?
        .lifecycle
        .generation;
    let mut fence = b"hepta:agentd:objective-fence:v1\0".to_vec();
    fence.extend_from_slice(agent.agent_id.as_str().as_bytes());
    fence.extend_from_slice(&1u64.to_be_bytes());
    fence.extend_from_slice(&generation.to_be_bytes());
    for run_id in ["run.drain.first", "run.drain.second"] {
        let snapshot = AgentRunSnapshot {
            run_id: run_id.to_string(),
            request_digest: "1".repeat(64),
            objective_digest: "2".repeat(64),
            body_digest: "3".repeat(64),
            artifact_set_digest: "4".repeat(64),
            authority_epoch: 7,
            generation,
            fence_digest: Sha256Digest::for_bytes(&fence).as_str().to_string(),
            deadline_ms: u64::MAX - 1,
        };
        let admitted = client.run_start(snapshot.clone()).await?;
        let attached = client
            .run_attach_context(
                admitted.revision,
                AgentContextAttachment {
                    run_id: snapshot.run_id.clone(),
                    request_digest: snapshot.request_digest,
                    objective_digest: snapshot.objective_digest,
                    body_digest: snapshot.body_digest,
                    artifact_set_digest: snapshot.artifact_set_digest,
                    authority_epoch: snapshot.authority_epoch,
                    generation: snapshot.generation,
                    fence_digest: snapshot.fence_digest,
                    deadline_ms: snapshot.deadline_ms,
                    context_digest: "5".repeat(64),
                    compilation_receipt_digest: "6".repeat(64),
                },
            )
            .await?;
        client
            .run_mark_dispatched(snapshot.run_id, attached.revision)
            .await?;
    }
    // Do not tick Supervisor: its normal timeout deliberately force-stops an
    // unresolved owner. Observe this daemon's own drain acknowledgement instead.
    fleet
        .registry
        .compare_and_transition(&agent.agent_id, generation, AgentLifecycle::Draining)?;
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let drain = request_drain(agent.layout.agentd_control_socket(), &agent.agent_id).await?;
        ensure!(drain.admission_closed && !drain.fenced);
        ensure!(
            !drain.drained,
            "unresolved Agentd runs were certified drained"
        );
        let first = client
            .run_status("run.drain.first".to_string())
            .await?
            .context("admitted run disappeared")?;
        let second = client
            .run_status("run.drain.second".to_string())
            .await?
            .context("admitted run disappeared")?;
        if first.phase == AgentRunPhase::Indeterminate
            && second.phase == AgentRunPhase::Indeterminate
        {
            ensure!(
                client
                    .run_mark_dispatched(first.run_id.clone(), first.revision)
                    .await
                    .is_err(),
                "drain reopened an indeterminate dispatch"
            );
            assert_eq!(client.run_status(first.run_id.clone()).await?, Some(first));
            break;
        }
        ensure!(
            Instant::now() < deadline,
            "cancellation acknowledgement never expired"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    for (index, run_id) in ["run.drain.first", "run.drain.second"]
        .into_iter()
        .enumerate()
    {
        let run = client
            .run_status(run_id.to_string())
            .await?
            .context("admitted run disappeared")?;
        client
            .run_observe_terminal(
                run_id.to_string(),
                run.revision,
                AgentRunPhase::Cancelled,
                /*terminal_observed*/ true,
            )
            .await?;
        if index == 0 {
            ensure!(
                !request_drain(agent.layout.agentd_control_socket(), &agent.agent_id)
                    .await?
                    .drained,
                "a second unresolved run was lost"
            );
        }
    }
    // The positive result requires the actual App Server's joined drain; no
    // test setter or fabricated acknowledgement is used.
    let deadline = Instant::now() + Duration::from_secs(10);
    while !request_drain(agent.layout.agentd_control_socket(), &agent.agent_id)
        .await?
        .drained
    {
        ensure!(Instant::now() < deadline, "real App Server failed to drain");
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    Ok(())
}

async fn request_drain(socket: &Path, agent_id: &AgentId) -> Result<DrainSnapshot> {
    tokio::time::timeout(Duration::from_secs(2), async {
        let mut stream = UnixStream::connect(socket).await?;
        let mut request = AgentdRequest::drain(/*request_id*/ 91, /*spawn_generation*/ 1);
        request.target_agent_id = Some(agent_id.clone());
        let mut frame = serde_json::to_vec(&request)?;
        frame.push(b'\n');
        stream.write_all(&frame).await?;
        let mut response = Vec::new();
        BufReader::new(stream)
            .read_until(b'\n', &mut response)
            .await?;
        let response: AgentdResponse = serde_json::from_slice(&response)?;
        ensure!(response.agent_id == *agent_id && response.spawn_generation == 1);
        let AgentdPayload::Drain(snapshot) = response.payload else {
            anyhow::bail!("expected drain acknowledgement: {:?}", response.payload);
        };
        Ok(snapshot)
    })
    .await?
}
