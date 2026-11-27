// Private Unix child implementation for the catalog-contained paired process fixture.

use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentLifecycleState;
use codex_hepta_matrix_protocol::MATRIXD_CONTROL_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixdHealth;
use codex_hepta_matrix_protocol::MatrixdLifecycle;
use codex_hepta_matrix_protocol::MatrixdPayload;
use codex_hepta_matrix_protocol::MatrixdRequest;
use codex_hepta_matrix_protocol::MatrixdResponse;
use codex_hepta_paths::HeptaFleetRoot;

#[path = "paired_process_fixture_wire.rs"]
mod wire;

use wire::AgentdMethod;
use wire::AgentdPayload;
use wire::AgentdRequest;
use wire::AgentdResponse;

pub(super) fn run() {
    let result = if std::env::var_os("HEPTA_MATRIXD_CONTROL_SOCKET").is_some() {
        run_matrix_child()
    } else {
        run_agent_child()
    };
    if let Err(error) = result {
        panic!("paired child failed: {error:#}");
    }
}

fn run_agent_child() -> Result<()> {
    let fleet_root = HeptaFleetRoot::from_env()?;
    let agent_id = AgentId::parse(std::env::var("HEPTA_AGENT_ID")?)?;
    let spawn_generation = std::env::var("HEPTA_AGENT_GENERATION")?.parse::<u64>()?;
    let layout = fleet_root.layout().agent(&agent_id);
    let socket = layout.agentd_control_socket().to_path_buf();
    prepare_fixture_socket(&socket)?;
    let listener = UnixListener::bind(&socket)?;
    for stream in listener.incoming() {
        let mut reader = BufReader::new(stream?);
        let mut bytes = Vec::new();
        reader.read_until(b'\n', &mut bytes)?;
        let request: AgentdRequest = serde_json::from_slice(&bytes)?;
        let run_root = PathBuf::from(
            std::env::var_os("HEPTA_AGENT_RUN_ROOT").context("HEPTA_AGENT_RUN_ROOT")?,
        );
        let home_root =
            PathBuf::from(std::env::var_os("HEPTA_AGENT_HOME").context("HEPTA_AGENT_HOME")?);
        let workspace = std::env::current_dir()?;
        let lifecycle = latest_lifecycle(&run_root)?;
        let running = lifecycle.lifecycle == AgentLifecycle::Running;
        let payload = match request.method {
            AgentdMethod::Health {} => AgentdPayload::Health(HealthSnapshot {
                promotion_ready: true,
                ready: running,
                fenced: false,
                lifecycle: lifecycle.lifecycle,
                process_id: std::process::id(),
                workspace,
                home_root,
                run_root,
            }),
            AgentdMethod::Drain {} => {
                // This process fixture owns no assistant turns. Acknowledge
                // drain only after the registry has closed its admission.
                let draining = lifecycle.lifecycle == AgentLifecycle::Draining;
                AgentdPayload::Drain(DrainSnapshot {
                    admission_closed: draining,
                    running_turns: 0,
                    drained: draining,
                    lifecycle: lifecycle.lifecycle,
                    fenced: false,
                })
            }
        };
        let response = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            agent_id: agent_id.clone(),
            spawn_generation,
            current_generation: lifecycle.generation,
            payload,
        };
        let mut stream = reader.into_inner();
        serde_json::to_writer(&mut stream, &response)?;
        stream.write_all(b"\n")?;
    }
    Ok(())
}

fn latest_lifecycle(run_root: &Path) -> Result<AgentLifecycleState> {
    let mut latest: Option<(u64, PathBuf)> = None;
    for entry in std::fs::read_dir(run_root)? {
        let entry = entry?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        let Some(value) = name
            .strip_prefix("lifecycle-")
            .and_then(|value| value.strip_suffix(".json"))
        else {
            continue;
        };
        let Ok(generation) = value.parse::<u64>() else {
            continue;
        };
        if latest
            .as_ref()
            .is_none_or(|(current, _)| generation > *current)
        {
            latest = Some((generation, entry.path()));
        }
    }
    let (_, path) = latest.context("fixture lifecycle state")?;
    Ok(serde_json::from_slice(&std::fs::read(path)?)?)
}

fn run_matrix_child() -> Result<()> {
    let agent_id = AgentId::parse(std::env::var("HEPTA_AGENT_ID")?)?;
    let agent_generation = std::env::var("HEPTA_AGENT_GENERATION")?.parse::<u64>()?;
    let binding_revision = std::env::var("HEPTA_MATRIX_BINDING_REVISION")?.parse::<u64>()?;
    let binding_digest = Sha256Digest::parse(std::env::var("HEPTA_MATRIX_BINDING_DIGEST")?)
        .map_err(anyhow::Error::msg)?;
    let release_id = std::env::var("HEPTA_MATRIX_RELEASE_ID")?;
    let process_incarnation = std::env::var("HEPTA_MATRIX_PROCESS_INCARNATION")?;
    let plane_epoch = std::env::var("HEPTA_MATRIX_PLANE_EPOCH")?.parse::<u64>()?;
    let socket = PathBuf::from(
        std::env::var_os("HEPTA_MATRIXD_CONTROL_SOCKET").context("HEPTA_MATRIXD_CONTROL_SOCKET")?,
    );
    prepare_fixture_socket(&socket)?;
    let listener = UnixListener::bind(&socket)?;
    for stream in listener.incoming() {
        let mut reader = BufReader::new(stream?);
        let mut bytes = Vec::new();
        reader.read_until(b'\n', &mut bytes)?;
        let request: MatrixdRequest = serde_json::from_slice(&bytes)?;
        let response = MatrixdResponse {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            agent_id: agent_id.clone(),
            release_id: release_id.clone(),
            binding_revision,
            binding_digest: binding_digest.clone(),
            attached_agent_generation: agent_generation,
            process_incarnation: process_incarnation.clone(),
            plane_epoch,
            payload: MatrixdPayload::Health(MatrixdHealth {
                lifecycle: MatrixdLifecycle::Ready,
                process_id: std::process::id(),
                agentd_connected: true,
                matrix_sync_connected: true,
                fenced: false,
            }),
        };
        let mut stream = reader.into_inner();
        serde_json::to_writer(&mut stream, &response)?;
        stream.write_all(b"\n")?;
    }
    Ok(())
}

fn prepare_fixture_socket(path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if let Err(error) = std::fs::remove_file(path)
        && error.kind() != std::io::ErrorKind::NotFound
    {
        return Err(error.into());
    }
    Ok(())
}
