//! Real fleet, SQLite, artifact owner and control sockets. App Server readiness
//! and the one-operation resolver are explicit integration seams.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
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
use codex_hepta_memory::FederationCapability;
use codex_hepta_memory::FederationCapabilityId;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_memory::MemoryCellRecordV1;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde_json::json;
use tempfile::TempDir;
use tokio::sync::Notify;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use crate::AgentdClient;
use crate::AgentdControlServer;
use crate::AgentdIdentity;
use crate::AgentdMemoryCellRuntimeV1;
use crate::AgentdState;
use crate::MemoryCellAddressResolverV1;
use crate::MemoryCellResolvedAddressV1;
use crate::MemoryFederationScopeKind;
use crate::memory_cell_release::test_support::ReleaseFixture;

use super::MemoryCellDeploymentV1;
use super::MemoryCellNodeBindingV1;
use super::MemoryCellVersionPinV1;

#[derive(Default)]
pub(super) struct GateResolver {
    block: AtomicBool,
    pub entered: Notify,
    pub release: Notify,
}

impl GateResolver {
    pub fn block_once(&self) { self.block.store(true, Ordering::SeqCst); }
}

impl MemoryCellAddressResolverV1 for GateResolver {
    fn model_digest(&self) -> ContractDigestV1 {
        ContractDigestV1::from_digest(Digest32::of_bytes(b"network-test-resolver-no-language-claim")).expect("digest")
    }
    fn resolve<'a>(&'a self, request: &'a MemoryRequestV1, snapshot: &'a MemoryCellOwnerSnapshotV1)
        -> Pin<Box<dyn Future<Output = Result<Option<MemoryCellResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move {
            if self.block.swap(false, Ordering::SeqCst) {
                self.entered.notify_one();
                self.release.notified().await;
            }
            Ok(Some(MemoryCellResolvedAddressV1 { request: request.clone(), operation: MemoryOperationV1::Apply,
                owner_cut_digest: snapshot.owner_cut_digest(), model_digest: self.model_digest() }))
        })
    }
}

pub(super) struct Node {
    pub state: Arc<AgentdState>,
    pub store: Arc<DurableCognitiveStore>,
    pub client: AgentdClient,
    pub release: Option<ReleaseFixture>,
    pub grant: Option<FederationCapability>,
    pub gate: Arc<GateResolver>,
    pub label: StableId,
    cancellation: CancellationToken,
    control: Option<JoinHandle<Result<(), crate::AgentdError>>>,
}

impl Node {
    async fn start(registry: &FleetRegistry, owner: AgentId, source: bool, label: &str) -> Self {
        let registered = registry.load_agent(&owner).expect("registered node");
        registry.compare_and_transition(&owner, /*expected_generation*/ 0, AgentLifecycle::Starting).expect("starting");
        let identity = AgentdIdentity {
            agent_id: owner.clone(), layout: registered.layout.clone(), spawn_generation: 1,
            fleet_root: registered.layout.agent_root().parent().expect("agents").parent().expect("fleet").to_path_buf(),
            workspace: registered.manifest.workspace.as_path().to_path_buf(), resources: registered.manifest.resources,
            home_root: registered.layout.home_root().to_path_buf(), run_root: registered.layout.run_root().to_path_buf(),
            control_socket: registered.layout.agentd_control_socket().to_path_buf(), app_server_socket: registered.layout.app_server_socket().to_path_buf(),
        };
        let state = Arc::new(AgentdState::new(identity.clone(), registry.clone(), /*event_capacity*/ 16).expect("state"));
        let store = Arc::new(DurableCognitiveStore::open(&registered.layout).await.expect("owner store"));
        let gate = Arc::new(GateResolver::default());
        let mut release = None;
        if source {
            for (kind, value) in [(MemoryCellKindV1::Event, json!(9)),
                (MemoryCellKindV1::Semantic, json!({"factor":3,"label":"network semantic"})),
                (MemoryCellKindV1::Procedure, json!({"opcode":"affine","bias":2,"limit":1000}))] {
                let record = MemoryCellRecordV1 { schema:"hepta.memory.cell-record.v1".to_string(), entity: ContractIdV1::new("meter:network").expect("entity"),
                    kind, effective_at: 20, value };
                store.write_memory_cell(&CognitiveAccess::agent_private(owner.clone()), &CognitiveScope::AgentPrivate, &record, MemoryCellWriteModeV1::Create).await.expect("typed source");
            }
            let snapshot = store.memory_cell_snapshot(&CognitiveAccess::agent_private(owner.clone()), &CognitiveScope::AgentPrivate, super::unix_seconds().expect("time")).await.expect("source snapshot");
            let selected = ReleaseFixture::new(&snapshot);
            let resolver: Arc<dyn MemoryCellAddressResolverV1> = gate.clone();
            state.attach_memory_cells(Arc::new(AgentdMemoryCellRuntimeV1::new(owner.clone(), /*spawn_generation*/ 1,
                CognitiveScope::AgentPrivate, Arc::clone(&selected.host), resolver).expect("memory runtime"))).expect("runtime attachment");
            release = Some(selected);
        }
        state.attach_cognitive_store(Arc::clone(&store)).expect("owner attachment");
        registry.compare_and_transition(&owner, /*expected_generation*/ 1, AgentLifecycle::Running).expect("running");
        state.refresh_generation().expect("live generation");
        state.mark_runtime_prerequisites_ready().expect("stores and ports ready");
        state.mark_app_server_ready().expect("explicit test app-server readiness");
        let cancellation = CancellationToken::new();
        let server = AgentdControlServer::bind(identity.control_socket.clone(), Arc::clone(&state), cancellation.clone()).await.expect("real socket");
        let control = Some(tokio::spawn(server.run()));
        let client = AgentdClient::new(identity.control_socket, owner, /*spawn_generation*/ 1).expect("real client");
        Self { state, store, client, release, grant: None, gate, label: StableId::new(label).expect("node label"), cancellation, control }
    }

    pub fn binding(&self) -> MemoryCellNodeBindingV1 {
        let bundle = self.release.as_ref().expect("source release").host.load_current().expect("selected bundle");
        let pin = MemoryCellVersionPinV1 { scope: bundle.scope().clone(), owner_cut_digest: bundle.owner_cut_digest(),
            generation: bundle.generation(), bundle_digest: bundle.bundle_digest() };
        self.binding_with_pin(pin)
    }

    pub fn binding_with_pin(&self, pin: MemoryCellVersionPinV1) -> MemoryCellNodeBindingV1 {
        MemoryCellNodeBindingV1::new(self.label.clone(), self.grant.clone().expect("real grant"),
            self.state.identity().spawn_generation, pin.clone(), request(pin.scope)).expect("node binding")
    }

    pub async fn snapshot(&self) -> MemoryCellOwnerSnapshotV1 {
        self.store.memory_cell_snapshot(&CognitiveAccess::agent_private(self.state.identity().agent_id.clone()), &CognitiveScope::AgentPrivate,
            super::unix_seconds().expect("time")).await.expect("real owner snapshot")
    }

    pub async fn grant_to(&mut self, consumer: &AgentId) {
        let issued = self.client.memory_federation_grant(consumer.clone(), MemoryFederationScopeKind::AgentPrivate, /*lifetime_seconds*/ 3_600).await.expect("actual owner control grant");
        let id = FederationCapabilityId::parse(issued.capability_id.as_str().to_string()).expect("capability id");
        self.grant = Some(self.store.federation_capability_status(&id).await.expect("owner grant state").expect("issued grant").capability);
    }

    pub async fn stop(&mut self) {
        self.cancellation.cancel();
        if let Some(control) = self.control.take() { control.await.expect("control join").expect("control stop"); }
    }

    pub async fn restart_socket(&mut self) {
        assert!(self.control.is_none());
        self.cancellation = CancellationToken::new();
        let server = AgentdControlServer::bind(self.state.identity().control_socket.clone(), Arc::clone(&self.state), self.cancellation.clone()).await.expect("restored real socket");
        self.control = Some(tokio::spawn(server.run()));
    }

    pub async fn rotate_spawn(&mut self, registry: &FleetRegistry) {
        self.stop().await;
        let mut identity = self.state.identity().clone();
        let old = registry.load_agent(&identity.agent_id).expect("old lifecycle").lifecycle.generation;
        registry.compare_and_transition(&identity.agent_id, old, AgentLifecycle::Draining).expect("draining");
        registry.compare_and_transition(&identity.agent_id, old + 1, AgentLifecycle::Stopped).expect("stopped");
        registry.compare_and_transition(&identity.agent_id, old + 2, AgentLifecycle::Starting).expect("new starting spawn");
        identity.spawn_generation = old + 3;
        let state = Arc::new(AgentdState::new(identity.clone(), registry.clone(), /*event_capacity*/ 16).expect("successor state"));
        state.attach_cognitive_store(Arc::clone(&self.store)).expect("same durable owner");
        let resolver: Arc<dyn MemoryCellAddressResolverV1> = self.gate.clone();
        state.attach_memory_cells(Arc::new(AgentdMemoryCellRuntimeV1::new(identity.agent_id.clone(), identity.spawn_generation,
            CognitiveScope::AgentPrivate, Arc::clone(&self.release.as_ref().expect("release").host), resolver).expect("successor memory runtime"))).expect("new runtime attachment");
        registry.compare_and_transition(&identity.agent_id, identity.spawn_generation, AgentLifecycle::Running).expect("successor running");
        state.refresh_generation().expect("successor fence");
        state.mark_runtime_prerequisites_ready().expect("successor stores and ports");
        state.mark_app_server_ready().expect("explicit successor test readiness");
        self.client = AgentdClient::new(identity.control_socket, identity.agent_id, identity.spawn_generation).expect("successor client");
        self.state = state;
        self.restart_socket().await;
    }
}

impl Drop for Node { fn drop(&mut self) { self.cancellation.cancel(); } }

pub(super) struct NetworkFixture {
    _directory: TempDir,
    pub registry: FleetRegistry,
    pub consumer: Node,
    pub nodes: Vec<Node>,
}

impl NetworkFixture {
    pub async fn new() -> Self {
        let directory = TempDir::new().expect("network root");
        let fleet = HeptaFleetRoot::parse(directory.path().join("fleet")).expect("fleet path");
        let registry = FleetRegistry::initialize(fleet.clone()).expect("real fleet");
        let mut ids = Vec::new();
        for index in 1..=3 {
            let owner = AgentId::parse(format!("00000000-0000-4000-8000-{index:012x}")).expect("agent id");
            let workspace = directory.path().join(format!("workspace-{index}"));
            std::fs::create_dir(&workspace).expect("workspace");
            registry.register(AgentManifest::new(owner.clone(), WorkspaceBinding::new(workspace, &fleet).expect("workspace binding"),
                ResourceBudget::local_default()).expect("manifest")).expect("register actual agent");
            ids.push(owner);
        }
        let consumer = Node::start(&registry, ids[2].clone(), /*source*/ false, "consumer").await;
        let mut nodes = vec![Node::start(&registry, ids[0].clone(), /*source*/ true, "node:a").await,
            Node::start(&registry, ids[1].clone(), /*source*/ true, "node:b").await];
        for node in &mut nodes { node.grant_to(&ids[2]).await; }
        Self { _directory: directory, registry, consumer, nodes }
    }

    pub fn deployment(&self, generation: u64) -> MemoryCellDeploymentV1 {
        MemoryCellDeploymentV1::new(ContractGenerationV1::new(generation).expect("deployment generation"),
            self.nodes.iter().map(Node::binding).collect()).expect("complete version vector")
    }

    pub fn requests(&self) -> BTreeMap<StableId, MemoryRequestV1> {
        self.nodes.iter().map(|node| { let binding = node.binding(); (node.label.clone(), request(binding.pin().scope.clone())) }).collect()
    }

    pub async fn finish(mut self) {
        for node in &mut self.nodes { node.stop().await; }
        self.consumer.stop().await;
    }
}

pub(super) fn request(scope: ContractIdV1) -> MemoryRequestV1 {
    MemoryRequestV1 { schema: "hepta.memory.request.v1".to_string(), query_id: ContractIdV1::new("query:network").expect("query"),
        scope, entity: ContractIdV1::new("meter:network").expect("entity"), text: "Explicit network integration apply request".to_string(),
        at: 20, since: 10, max_hops: 3, max_cells: 3 }
}
