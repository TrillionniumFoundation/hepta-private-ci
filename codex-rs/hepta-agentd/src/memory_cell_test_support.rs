//! Real control socket and canonical SQLite owner; App Server readiness is an
//! explicit test seam. Learned release admission is supplied by release tests.

use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::MemoryCellRecordV1;
use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::Value;
use serde_json::json;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use crate::AgentdClient;
use crate::AgentdControlServer;
use crate::AgentdIdentity;
use crate::AgentdState;

pub(crate) struct ControlFixture {
    _root: tempfile::TempDir,
    pub(crate) store: Arc<DurableCognitiveStore>,
    pub(crate) state: Arc<AgentdState>,
    pub(crate) registry: FleetRegistry,
    pub(crate) client: AgentdClient,
    cancellation: CancellationToken,
    control: Option<JoinHandle<Result<(), crate::AgentdError>>>,
}

impl ControlFixture {
    pub(crate) async fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let fleet_path = root.path().join("fleet");
        let fleet = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
        let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
        let workspace = root.path().join("workspace");
        std::fs::create_dir(&workspace).unwrap();
        let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c81").unwrap();
        let registered = registry
            .register(
                AgentManifest::new(
                    owner.clone(),
                    WorkspaceBinding::new(&workspace, &fleet).unwrap(),
                    ResourceBudget::local_default(),
                )
                .unwrap(),
            )
            .unwrap();
        registry
            .compare_and_transition(
                &owner,
                /*expected_generation*/ 0,
                AgentLifecycle::Starting,
            )
            .unwrap();
        let identity = AgentdIdentity {
            agent_id: owner.clone(),
            layout: registered.layout.clone(),
            spawn_generation: 1,
            fleet_root: fleet_path,
            workspace,
            resources: registered.manifest.resources,
            home_root: registered.layout.home_root().to_path_buf(),
            run_root: registered.layout.run_root().to_path_buf(),
            control_socket: registered.layout.agentd_control_socket().to_path_buf(),
            app_server_socket: registered.layout.app_server_socket().to_path_buf(),
        };
        let state = Arc::new(
            AgentdState::new(
                identity.clone(),
                registry.clone(),
                /*event_capacity*/ 16,
            )
            .unwrap(),
        );
        let store = Arc::new(
            DurableCognitiveStore::open(&registered.layout)
                .await
                .unwrap(),
        );
        for record in [
            record(MemoryCellKindV1::Event, /*effective_at*/ 10, json!(4)),
            record(MemoryCellKindV1::Event, /*effective_at*/ 20, json!(9)),
            record(
                MemoryCellKindV1::Semantic,
                /*effective_at*/ 20,
                json!({"factor": 3, "label": "owner semantic"}),
            ),
            record(
                MemoryCellKindV1::Procedure,
                /*effective_at*/ 20,
                json!({"opcode": "affine", "bias": 2, "limit": 1000}),
            ),
        ] {
            store
                .write_memory_cell(
                    &CognitiveAccess::agent_private(owner.clone()),
                    &CognitiveScope::AgentPrivate,
                    &record,
                    MemoryCellWriteModeV1::Create,
                )
                .await
                .unwrap();
        }
        state.attach_cognitive_store(Arc::clone(&store)).unwrap();
        registry
            .compare_and_transition(
                &owner,
                /*expected_generation*/ 1,
                AgentLifecycle::Running,
            )
            .unwrap();
        state.refresh_generation().unwrap();
        let cancellation = CancellationToken::new();
        let server = AgentdControlServer::bind(
            identity.control_socket.clone(),
            Arc::clone(&state),
            cancellation.clone(),
        )
        .await
        .unwrap();
        let control = Some(tokio::spawn(server.run()));
        let client =
            AgentdClient::new(identity.control_socket, owner, /*spawn_generation*/ 1).unwrap();
        Self {
            _root: root,
            store,
            state,
            registry,
            client,
            cancellation,
            control,
        }
    }

    pub(crate) fn ready(&self) {
        self.state.mark_runtime_prerequisites_ready().unwrap();
        self.state.mark_app_server_ready().unwrap();
    }

    pub(crate) fn access(&self) -> CognitiveAccess {
        CognitiveAccess::agent_private(self.state.identity().agent_id.clone())
    }

    pub(crate) async fn snapshot(&self) -> codex_hepta_cognitive_store::MemoryCellOwnerSnapshotV1 {
        self.store
            .memory_cell_snapshot(
                &self.access(),
                &CognitiveScope::AgentPrivate,
                crate::memory_cell_runtime::now_unix_seconds().unwrap(),
            )
            .await
            .unwrap()
    }

    pub(crate) async fn finish(mut self) {
        self.cancellation.cancel();
        self.control.take().unwrap().await.unwrap().unwrap();
    }
}

impl Drop for ControlFixture {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

pub(crate) fn record(
    kind: MemoryCellKindV1,
    effective_at: u64,
    value: Value,
) -> MemoryCellRecordV1 {
    MemoryCellRecordV1 {
        schema: "hepta.memory.cell-record.v1".to_string(),
        entity: ContractIdV1::new("meter:agentd-cell").unwrap(),
        kind,
        effective_at,
        value,
    }
}

pub(crate) fn request(scope: ContractIdV1) -> MemoryRequestV1 {
    MemoryRequestV1 {
        schema: "hepta.memory.request.v1".to_string(),
        query_id: ContractIdV1::new("query:agentd-cell").unwrap(),
        scope,
        entity: ContractIdV1::new("meter:agentd-cell").unwrap(),
        text: "Explicit trusted resolver integration test".to_string(),
        at: 15,
        since: 10,
        max_hops: 3,
        max_cells: 3,
    }
}
