//! Real OS children hosting SQLite, signed artifacts and Agentd control.
//! App Server readiness and the single-operation resolver are explicit fixture
//! seams. These are separate processes on one host, with no cross-host claim.

use std::collections::BTreeMap;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::FederatedMemoryReader;
use codex_hepta_memory::MemoryCellRecordV1;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use tempfile::TempDir;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::ChildStdout;
use tokio::process::Command;
use tokio_util::sync::CancellationToken;

use crate::AgentdClient;
use crate::AgentdConfig;
use crate::AgentdControlServer;
use crate::AgentdMemoryCellRuntimeV1;
use crate::AgentdState;
use crate::MemoryCellAddressResolverV1;
use crate::MemoryFederationCapabilityId;
use crate::MemoryFederationScopeKind;

use super::MemoryCellDeploymentV1;
use super::MemoryCellNodeBindingV1;
use super::MemoryCellVersionPinV1;
use super::process_release_test_support::ProcessRelease;
use super::process_release_test_support::ReleaseCheckpoint;
use super::test_support::GateResolver;
use super::test_support::request;

const CHILD_TEST: &str = "memory_cell_network::process_tests::memory_cell_network_child";
const SPEC_ENV: &str = "HEPTA_MEMORY_PROCESS_TEST_SPEC";
const PREFIX: &str = "HEPTA_MEMORY_PROCESS_FRAME:";
const LIMIT: usize = 65_536;
const DEADLINE: Duration = Duration::from_secs(15);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
enum Role {
    Source,
    Consumer,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct NodeSpec {
    fleet_root: PathBuf,
    owner: AgentId,
    spawn_generation: u64,
    role: Role,
    resume: Option<ReleaseCheckpoint>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NodeReady {
    pub pid: u32,
    pub owner: AgentId,
    pub spawn_generation: u64,
    pub scope: Option<ContractIdV1>,
    pub cut: Option<ContractDigestV1>,
    pub artifact_generation: Option<ContractGenerationV1>,
    pub bundle: Option<ContractDigestV1>,
    pub release: Option<ReleaseCheckpoint>,
}

pub(super) struct ProcessNode {
    child: Option<Child>,
    input: Option<ChildStdin>,
    output: BufReader<ChildStdout>,
    pub ready: NodeReady,
    pub client: AgentdClient,
    grant: Option<MemoryFederationCapabilityId>,
    pub handshake_received_bytes: u64,
    pub handshake_transmitted_bytes: u64,
    exit_status: Option<String>,
}

impl ProcessNode {
    async fn spawn(
        root: &Path,
        registry: &FleetRegistry,
        owner: AgentId,
        role: Role,
        resume: Option<ReleaseCheckpoint>,
    ) -> Self {
        let record = registry.load_agent(&owner).expect("registered child");
        let lifecycle = registry
            .compare_and_transition(
                &owner,
                record.lifecycle.generation,
                AgentLifecycle::Starting,
            )
            .expect("supervisor starting transition");
        let spec = NodeSpec {
            fleet_root: registry.layout().fleet_root().as_path().to_path_buf(),
            owner: owner.clone(),
            spawn_generation: lifecycle.generation,
            role,
            resume,
        };
        let path = root.join(format!("{}-{}.json", owner.as_str(), lifecycle.generation));
        let bytes = serde_json::to_vec(&spec).expect("child spec");
        assert!(bytes.len() < LIMIT);
        let mut file = std::fs::File::create_new(&path).expect("new immutable child spec");
        file.write_all(&bytes).expect("spec bytes");
        file.sync_all().expect("durable spec");
        let mut child = Command::new(std::env::current_exe().expect("current test executable"))
            .args([
                "--ignored",
                "--exact",
                CHILD_TEST,
                "--nocapture",
                "--test-threads=1",
            ])
            .env(SPEC_ENV, &path)
            .env("TMPDIR", root)
            .current_dir(record.manifest.workspace.as_path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()
            .expect("separate node process");
        let pid = child.id().expect("live child PID");
        let input = child.stdin.take().expect("child input");
        let mut output = BufReader::new(child.stdout.take().expect("child output"));
        let (frame, received) = read_frame(&mut output).await;
        let ready: NodeReady =
            serde_json::from_value(frame["prepared"].clone()).expect("prepared node metadata");
        assert_eq!(
            (ready.pid, &ready.owner, ready.spawn_generation),
            (pid, &owner, lifecycle.generation)
        );
        assert_ne!(pid, std::process::id());
        registry
            .compare_and_transition(&owner, lifecycle.generation, AgentLifecycle::Running)
            .expect("supervisor running transition");
        let client = AgentdClient::new(
            record.layout.agentd_control_socket().to_path_buf(),
            owner,
            lifecycle.generation,
        )
        .expect("child control client");
        let mut node = Self {
            child: Some(child),
            input: Some(input),
            output,
            ready,
            client,
            grant: None,
            handshake_received_bytes: received,
            handshake_transmitted_bytes: 0,
            exit_status: None,
        };
        node.command("activate").await;
        let (frame, received) = read_frame(&mut node.output).await;
        node.handshake_received_bytes += received;
        assert_eq!(frame, json!({"ready":true}));
        assert!(
            node.client
                .health()
                .await
                .expect("actual child readiness")
                .ready
        );
        node
    }

    async fn command(&mut self, value: &str) {
        let command = format!("{value}\n");
        self.input
            .as_mut()
            .expect("child stdin")
            .write_all(command.as_bytes())
            .await
            .expect("child command");
        self.handshake_transmitted_bytes += command.len() as u64;
    }

    pub async fn crash(&mut self) {
        let child = self.child.as_mut().expect("running child");
        child.start_kill().expect("kill test child process");
        let status = tokio::time::timeout(DEADLINE, child.wait())
            .await
            .expect("child exit deadline")
            .expect("reap failed child");
        assert!(!status.success());
        self.exit_status = Some(status.to_string());
        self.child.take();
        self.input.take();
        self.record_exit_output().await;
    }

    async fn stop(&mut self) {
        if self.child.is_none() {
            return;
        }
        self.command("stop").await;
        self.input.take();
        let child = self.child.as_mut().expect("child");
        let status = tokio::time::timeout(DEADLINE, child.wait())
            .await.expect("shutdown deadline").expect("reap stopped child");
        assert!(status.success());
        self.exit_status = Some(status.to_string());
        self.child.take();
        self.record_exit_output().await;
    }

    async fn record_exit_output(&mut self) {
        let mut trailer = Vec::new();
        let mut output = (&mut self.output).take((LIMIT + 1) as u64);
        tokio::time::timeout(DEADLINE, output.read_to_end(&mut trailer)).await
            .expect("bounded child EOF deadline").expect("child exit output");
        assert!(trailer.len() <= LIMIT, "child exit output bound");
        self.handshake_received_bytes += trailer.len() as u64;
    }

    pub async fn binding(
        &self,
        registry: &FleetRegistry,
        consumer: &AgentId,
    ) -> MemoryCellNodeBindingV1 {
        let record = registry
            .load_agent(&self.ready.owner)
            .expect("source owner");
        // This is the existing read-only discovery path. No JSON field or
        // caller-supplied capability is promoted into an authority object.
        let readers = FederatedMemoryReader::discover(
            &record.layout,
            consumer,
            super::unix_seconds().expect("clock"),
        )
        .await
        .expect("read-only current grant discovery");
        let id = self.grant.as_ref().expect("actual control grant");
        let reader = readers
            .iter()
            .find(|reader| reader.capability().id().as_str() == id.as_str())
            .expect("matching owner-issued grant");
        let pin = MemoryCellVersionPinV1 {
            scope: self.ready.scope.clone().expect("scope"),
            owner_cut_digest: self.ready.cut.expect("cut"),
            generation: self
                .ready
                .artifact_generation
                .expect("parameter generation"),
            bundle_digest: self.ready.bundle.expect("parameter bundle"),
        };
        MemoryCellNodeBindingV1::new(
            StableId::new(self.ready.owner.as_str()).expect("node label"),
            reader.capability().clone(),
            self.ready.spawn_generation,
            pin.clone(),
            request(pin.scope),
        )
        .expect("node binding requiring live network validation")
    }
}

pub(super) struct ProcessFleet {
    pub root: PathBuf,
    pub registry: FleetRegistry,
    pub consumer: ProcessNode,
    pub nodes: Vec<ProcessNode>,
    _directory: TempDir,
}

impl ProcessFleet {
    pub async fn new() -> Self {
        let directory = TempDir::new().expect("process fixture root");
        let root = directory
            .path()
            .canonicalize()
            .expect("canonical fixture root");
        let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet.clone()).expect("real fleet registry");
        let mut ids = Vec::new();
        for index in 1..=3 {
            let owner = AgentId::parse(format!("00000000-0000-4000-9000-{index:012x}"))
                .expect("process owner ID");
            let workspace = root.join(format!("workspace-{index}"));
            std::fs::create_dir(&workspace).expect("workspace");
            registry
                .register(
                    AgentManifest::new(
                        owner.clone(),
                        WorkspaceBinding::new(workspace, &fleet).expect("workspace binding"),
                        ResourceBudget::local_default(),
                    )
                    .expect("manifest"),
                )
                .expect("registered child");
            ids.push(owner);
        }
        let consumer =
            ProcessNode::spawn(&root, &registry, ids[2].clone(), Role::Consumer, None).await;
        let mut nodes = Vec::new();
        for owner in &ids[..2] {
            let mut node =
                ProcessNode::spawn(&root, &registry, owner.clone(), Role::Source, None).await;
            let grant = node
                .client
                .memory_federation_grant(
                    ids[2].clone(),
                    MemoryFederationScopeKind::AgentPrivate,
                    /*lifetime_seconds*/ 3_600,
                )
                .await
                .expect("grant through actual owner control");
            node.grant = Some(grant.capability_id);
            nodes.push(node);
        }
        Self {
            _directory: directory,
            root,
            registry,
            consumer,
            nodes,
        }
    }

    pub async fn deployment(&self, generation: u64) -> MemoryCellDeploymentV1 {
        let mut bindings = Vec::new();
        for node in &self.nodes {
            bindings.push(
                node.binding(&self.registry, &self.consumer.ready.owner)
                    .await,
            );
        }
        MemoryCellDeploymentV1::new(
            ContractGenerationV1::new(generation).expect("deployment generation"),
            bindings,
        )
        .expect("complete process vector")
    }

    pub fn requests(&self) -> BTreeMap<StableId, MemoryRequestV1> {
        self.nodes
            .iter()
            .map(|node| {
                (
                    StableId::new(node.ready.owner.as_str()).expect("node label"),
                    request(node.ready.scope.clone().expect("source scope")),
                )
            })
            .collect()
    }

    pub async fn restart(&mut self, index: usize) {
        let old = &self.nodes[index];
        assert!(
            old.child.is_none(),
            "wait for predecessor exit before reopening its writers"
        );
        let record = self
            .registry
            .load_agent(&old.ready.owner)
            .expect("failed predecessor");
        self.registry
            .compare_and_transition(
                &old.ready.owner,
                record.lifecycle.generation,
                AgentLifecycle::Failed,
            )
            .expect("supervisor observes failure");
        let mut successor = ProcessNode::spawn(
            &self.root,
            &self.registry,
            old.ready.owner.clone(),
            Role::Source,
            old.ready.release.clone(),
        )
        .await;
        successor.grant = old.grant.clone();
        self.nodes[index] = successor;
    }

    pub async fn finish(self) {
        self.finish_with_traffic().await;
    }

    pub async fn finish_with_traffic(mut self) -> Value {
        for node in &mut self.nodes {
            node.stop().await;
        }
        self.consumer.stop().await;
        let nodes: Vec<_> = self.nodes.iter().chain(std::iter::once(&self.consumer)).map(|node| {
            json!({"ready":node.ready,"exit_status":node.exit_status,"control":node.client.traffic_snapshot(),
                "handshake_tx_bytes":node.handshake_transmitted_bytes,"handshake_rx_bytes":node.handshake_received_bytes})
        }).collect();
        json!({"nodes":nodes,"all_children_reaped":true})
    }
}

async fn read_frame(output: &mut BufReader<ChildStdout>) -> (Value, u64) {
    tokio::time::timeout(DEADLINE, async {
        let mut line = Vec::new();
        let mut received = 0_u64;
        loop {
            let available = output.fill_buf().await.expect("child output");
            assert!(
                !available.is_empty(),
                "child exited before its protocol acknowledgement"
            );
            let count = available
                .iter()
                .position(|byte| *byte == b'\n')
                .map_or(available.len(), |offset| offset + 1);
            assert!(line.len() + count <= LIMIT, "child output line bound");
            line.extend_from_slice(&available[..count]);
            output.consume(count);
            received += count as u64;
            assert!(
                received <= LIMIT as u64,
                "child acknowledgement output budget"
            );
            if line.last() == Some(&b'\n') {
                let text = std::str::from_utf8(&line).expect("UTF-8 child output");
                if let Some(offset) = text.find(PREFIX) {
                    return (
                        serde_json::from_str(text[offset + PREFIX.len()..].trim())
                            .expect("child frame"),
                        received,
                    );
                }
                line.clear();
            }
        }
    })
    .await
    .expect("child acknowledgement deadline")
}

fn emit(frame: Value) {
    let mut output = std::io::stdout().lock();
    writeln!(output, "{PREFIX}{frame}").expect("parent frame");
    output.flush().expect("parent frame flush");
}

pub(super) async fn child_main() {
    let path = PathBuf::from(
        std::env::var_os(SPEC_ENV).expect("only the parent process launches this ignored helper"),
    );
    assert!(path.is_absolute());
    let bytes = std::fs::read(path).expect("child bootstrap");
    assert!(bytes.len() < LIMIT);
    let spec: NodeSpec = serde_json::from_slice(&bytes).expect("typed child bootstrap");
    let registry = FleetRegistry::open_existing(
        HeptaFleetRoot::parse(spec.fleet_root.clone()).expect("fleet root"),
    )
    .expect("existing fleet");
    let record = registry.load_agent(&spec.owner).expect("registered child");
    let config = AgentdConfig::load(
        spec.fleet_root,
        spec.owner.clone(),
        spec.spawn_generation,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        record.manifest.workspace.as_path().to_path_buf(),
    )
    .expect("real exclusive Agentd writer lock");
    let identity = config.identity().clone();
    let state = Arc::new(
        AgentdState::new(identity.clone(), registry, /*event_capacity*/ 16)
            .expect("real child state"),
    );
    let store = Arc::new(
        DurableCognitiveStore::open(&identity.layout)
            .await
            .expect("actual child SQLite owner"),
    );
    let access = CognitiveAccess::agent_private(spec.owner.clone());
    let mut release = None;
    if spec.role == Role::Source {
        if spec.resume.is_none() {
            for (kind, value) in [
                (MemoryCellKindV1::Event, json!(9)),
                (
                    MemoryCellKindV1::Semantic,
                    json!({"factor":3,"label":"network semantic"}),
                ),
                (
                    MemoryCellKindV1::Procedure,
                    json!({"opcode":"affine","bias":2,"limit":1000}),
                ),
            ] {
                store
                    .write_memory_cell(
                        &access,
                        &CognitiveScope::AgentPrivate,
                        &MemoryCellRecordV1 {
                            schema: "hepta.memory.cell-record.v1".to_string(),
                            entity: ContractIdV1::new("meter:network").expect("entity"),
                            kind,
                            effective_at: 20,
                            value,
                        },
                        MemoryCellWriteModeV1::Create,
                    )
                    .await
                    .expect("new owner source");
            }
        }
        let snapshot = store
            .memory_cell_snapshot(
                &access,
                &CognitiveScope::AgentPrivate,
                super::unix_seconds().expect("clock"),
            )
            .await
            .expect("child source snapshot");
        let selected = match spec.resume {
            Some(checkpoint) => ProcessRelease::reopen(&snapshot, checkpoint),
            None => ProcessRelease::create(&snapshot),
        };
        let resolver: Arc<dyn MemoryCellAddressResolverV1> = Arc::new(GateResolver::default());
        state
            .attach_memory_cells(Arc::new(
                AgentdMemoryCellRuntimeV1::new(
                    spec.owner.clone(),
                    spec.spawn_generation,
                    CognitiveScope::AgentPrivate,
                    Arc::clone(&selected.host),
                    resolver,
                )
                .expect("real child parameter runtime"),
            ))
            .expect("child memory attachment");
        release = Some(selected);
    }
    state
        .attach_cognitive_store(Arc::clone(&store))
        .expect("child owner attachment");
    let bundle = release
        .as_ref()
        .map(|release| release.host.load_current().expect("actual selected bundle"));
    let ready = NodeReady {
        pid: std::process::id(),
        owner: spec.owner,
        spawn_generation: spec.spawn_generation,
        scope: bundle.as_ref().map(|bundle| bundle.scope().clone()),
        cut: bundle.as_ref().map(|bundle| bundle.owner_cut_digest()),
        artifact_generation: bundle.as_ref().map(|bundle| bundle.generation()),
        bundle: bundle.as_ref().map(|bundle| bundle.bundle_digest()),
        release: release.as_ref().map(|release| release.checkpoint.clone()),
    };
    let cancellation = CancellationToken::new();
    let server = AgentdControlServer::bind(
        identity.control_socket,
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await
    .expect("actual child control socket");
    let control = tokio::spawn(server.run());
    emit(json!({"prepared":ready}));
    let mut input = BufReader::new(tokio::io::stdin()).lines();
    assert_eq!(
        input
            .next_line()
            .await
            .expect("activation command")
            .as_deref(),
        Some("activate")
    );
    state
        .refresh_generation()
        .expect("supervisor Running generation");
    state
        .mark_runtime_prerequisites_ready()
        .expect("child stores and sockets ready");
    state
        .mark_app_server_ready()
        .expect("explicit control-only fixture readiness seam");
    emit(json!({"ready":true}));
    assert_eq!(
        input.next_line().await.expect("stop command").as_deref(),
        Some("stop")
    );
    cancellation.cancel();
    control
        .await
        .expect("child server joined")
        .expect("child server stopped");
    drop(bundle);
    drop(state);
    drop(release);
    drop(store);
    drop(config);
}
