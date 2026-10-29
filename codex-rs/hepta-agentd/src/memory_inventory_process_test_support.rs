//! Separate OS owner processes for the explicitly enabled native actual case.

use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::{AgentLifecycle, AgentManifest, FleetRegistry, ResourceBudget, WorkspaceBinding};
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};

use crate::AgentdClient;
use crate::MemoryCellMigrationPinV9;
use crate::memory_inventory_release_test_support::InventoryReleaseCheckpoint;
use crate::memory_inventory_withdrawal_test_support::InventoryWithdrawalCheckpoint;

#[path = "memory_inventory_owner_test_child.rs"]
mod child;
pub(super) use child::child_main;

const CHILD_TEST: &str = "memory_inventory_actual_tests::memory_inventory_owner_child";
const SPEC_ENV: &str = "HEPTA_MEMORY_INVENTORY_CHILD_SPEC";
const PREFIX: &str = "HEPTA_MEMORY_INVENTORY_FRAME:";
const LIMIT: usize = 65_536;
const DEADLINE: Duration = Duration::from_secs(30);

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WorkerSpec {
    pub python: PathBuf,
    pub research: PathBuf,
    pub model: PathBuf,
    pub encoder: PathBuf,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RecoverySpec {
    pub pin: MemoryCellMigrationPinV9,
    pub unavailable_source: PathBuf,
    pub withdrawal: Option<InventoryWithdrawalCheckpoint>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Spec {
    fleet_root: PathBuf,
    owner: AgentId,
    spawn_generation: u64,
    artifact_root: PathBuf,
    records: Option<PathBuf>,
    resume: Option<InventoryReleaseCheckpoint>,
    worker: Option<WorkerSpec>,
    recovery: Option<RecoverySpec>,
}

pub(super) struct NativeOwner {
    child: Option<Child>,
    input: Option<ChildStdin>,
    output: BufReader<ChildStdout>,
    pub client: AgentdClient,
    pub ready: Value,
    pub frames_tx_bytes: u64,
    pub frames_rx_bytes: u64,
}

pub(super) fn fleet(root: &Path) -> (FleetRegistry, AgentId) {
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("fleet registry");
    let owner = AgentId::parse("00000000-0000-4000-9000-000000000010").expect("owner ID");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    registry.register(AgentManifest::new(owner.clone(), WorkspaceBinding::new(workspace, &fleet).expect("workspace binding"), ResourceBudget::local_default()).expect("manifest"))
        .expect("registered owner");
    (registry, owner)
}

impl NativeOwner {
    pub async fn spawn(
        root: &Path,
        registry: &FleetRegistry,
        owner: AgentId,
        records: Option<PathBuf>,
        resume: Option<InventoryReleaseCheckpoint>,
        worker: Option<WorkerSpec>,
        recovery: Option<RecoverySpec>,
    ) -> Self {
        let record = registry.load_agent(&owner).expect("registered owner");
        let lifecycle = registry.compare_and_transition(&owner, record.lifecycle.generation, AgentLifecycle::Starting).expect("starting transition");
        let spec = Spec {
            fleet_root: registry.layout().fleet_root().as_path().to_path_buf(), owner: owner.clone(),
            spawn_generation: lifecycle.generation, artifact_root: root.join("artifacts"), records, resume, worker, recovery,
        };
        let path = root.join(format!("child-{}.json", lifecycle.generation));
        let bytes = serde_json::to_vec(&spec).expect("child spec");
        assert!(bytes.len() < LIMIT);
        let mut file = std::fs::File::create_new(&path).expect("new spec");
        file.write_all(&bytes).expect("spec bytes");
        file.sync_all().expect("durable spec");
        let mut child = Command::new(std::env::current_exe().expect("test executable"))
            .args(["--ignored", "--exact", CHILD_TEST, "--nocapture", "--test-threads=1"])
            .env(SPEC_ENV, path).env("TMPDIR", root)
            .current_dir(record.manifest.workspace.as_path())
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit()).kill_on_drop(true)
            .spawn().expect("separate native owner process");
        let pid = child.id().expect("child PID");
        let input = child.stdin.take().expect("child input");
        let mut output = BufReader::new(child.stdout.take().expect("child output"));
        let (ready, rx) = read_frame(&mut output).await;
        assert_eq!(ready["pid"].as_u64(), Some(u64::from(pid)));
        assert_ne!(pid, std::process::id());
        if ready["refused"] == json!(true) {
            assert!(spec.recovery.as_ref().is_some_and(|recovery| recovery.withdrawal.is_some()), "only the explicit negative frontier recovery may refuse startup");
            let status = tokio::time::timeout(DEADLINE, child.wait()).await.expect("refused child deadline").expect("reap refused child");
            assert!(status.success(), "refusal must be an explicit receipt, not a panic");
            let mut trailer = Vec::new();
            tokio::time::timeout(DEADLINE, (&mut output).take((LIMIT + 1) as u64).read_to_end(&mut trailer)).await.expect("refused child EOF deadline").expect("refused child EOF");
            assert!(trailer.len() <= LIMIT);
            registry.compare_and_transition(&owner, lifecycle.generation, AgentLifecycle::Failed).expect("supervisor observes refused startup");
            let client = AgentdClient::new(record.layout.agentd_control_socket().to_path_buf(), owner, lifecycle.generation).expect("refused owner client");
            return Self { child:None, input:None, output, client, ready, frames_tx_bytes:0, frames_rx_bytes:rx + trailer.len() as u64 };
        }
        registry.compare_and_transition(&owner, lifecycle.generation, AgentLifecycle::Running).expect("running transition");
        let client = AgentdClient::new(record.layout.agentd_control_socket().to_path_buf(), owner, lifecycle.generation).expect("real control client");
        let mut process = Self { child: Some(child), input: Some(input), output, client, ready, frames_tx_bytes: 0, frames_rx_bytes: rx };
        assert_eq!(process.command(json!({"op":"activate"})).await, json!({"ready":true}));
        assert!(process.client.health().await.expect("owner readiness").ready);
        process
    }

    pub async fn command(&mut self, command: Value) -> Value {
        let mut bytes = serde_json::to_vec(&command).expect("test command");
        bytes.push(b'\n');
        assert!(bytes.len() <= LIMIT);
        self.input.as_mut().expect("owner input").write_all(&bytes).await.expect("command write");
        self.frames_tx_bytes += bytes.len() as u64;
        let (frame, bytes) = read_frame(&mut self.output).await;
        self.frames_rx_bytes += bytes;
        frame
    }

    pub async fn stop(&mut self, registry: &FleetRegistry, owner: &AgentId) -> Value {
        let record = registry.load_agent(owner).expect("live owner");
        if record.lifecycle.lifecycle == AgentLifecycle::Running {
            registry.compare_and_transition(owner, record.lifecycle.generation, AgentLifecycle::Draining).expect("draining transition");
        }
        let stopped = self.command(json!({"op":"stop"})).await;
        self.input.take();
        let status = tokio::time::timeout(DEADLINE, self.child.as_mut().expect("owner child").wait()).await.expect("owner exit deadline").expect("reap owner");
        assert!(status.success());
        self.child.take();
        let mut trailer = Vec::new();
        tokio::time::timeout(DEADLINE, (&mut self.output).take((LIMIT + 1) as u64).read_to_end(&mut trailer)).await.expect("owner EOF deadline").expect("owner EOF");
        assert!(trailer.len() <= LIMIT);
        self.frames_rx_bytes += trailer.len() as u64;
        let record = registry.load_agent(owner).expect("draining owner");
        registry.compare_and_transition(owner, record.lifecycle.generation, AgentLifecycle::Stopped).expect("stopped transition");
        json!({"process":self.ready,"ack":stopped,"exit_status":status.to_string(),"control":self.client.traffic_snapshot(),
            "frames_tx_bytes":self.frames_tx_bytes,"frames_rx_bytes":self.frames_rx_bytes,"reaped":true})
    }
}

async fn read_frame(output: &mut BufReader<ChildStdout>) -> (Value, u64) {
    tokio::time::timeout(DEADLINE, async {
        let mut total = 0_u64;
        loop {
            let mut line = Vec::new();
            (&mut *output).take((LIMIT + 1) as u64).read_until(b'\n', &mut line).await.expect("child frame");
            total += line.len() as u64;
            assert!(!line.is_empty() && line.len() <= LIMIT && total <= (LIMIT * 2) as u64);
            if let Some(offset) = line.windows(PREFIX.len()).position(|window| window == PREFIX.as_bytes()) {
                let value = serde_json::from_slice(&line[offset + PREFIX.len()..]).expect("typed child frame");
                return (value, total);
            }
        }
    }).await.expect("child frame deadline")
}

fn emit(value: Value) {
    let line = format!("{PREFIX}{}\n", serde_json::to_string(&value).expect("child frame"));
    assert!(line.len() < LIMIT);
    let mut output = std::io::stdout().lock();
    output.write_all(line.as_bytes()).expect("frame write");
    output.flush().expect("frame flush");
}
