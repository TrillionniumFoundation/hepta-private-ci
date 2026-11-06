//! Real Fleet/journal/witness lifetimes with a file-backed control fixture.
//! The fixture tests ownership and recovery, not model adoption or model quality.

use std::fs;
use std::fs::OpenOptions;
use std::future::Future;
use std::io::Write;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Waker;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_neuron::*;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use crate::AgentdIdentity;
use crate::AgentdState;
use crate::RuntimeTasks;

pub(super) fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("generation service fixture: {error:?}"),
    }
}

pub(super) fn poll_pending<F: Future>(future: Pin<&mut F>) {
    let mut context = Context::from_waker(Waker::noop());
    assert!(future.poll(&mut context).is_pending());
}

pub(super) fn host() -> (RuntimeTasks, CancellationToken) {
    let cancellation = CancellationToken::new();
    (
        checked(RuntimeTasks::new(
            cancellation.clone(),
            Duration::from_millis(80),
        )),
        cancellation,
    )
}

pub(super) fn generation(value: u64) -> Generation {
    checked(Generation::new(value))
}

#[derive(Default)]
pub(super) struct Signals {
    pub calls: AtomicUsize,
    pub reads: AtomicUsize,
    pub cancellations: AtomicUsize,
    pub lose_response: AtomicBool,
    pub readable: AtomicBool,
    pub panic_on_read: AtomicBool,
}

#[derive(Clone)]
pub(super) struct Control {
    directory: PathBuf,
    pub signals: Arc<Signals>,
}

impl Control {
    fn result_path(&self, request: &CellGenerationRequestV2) -> PathBuf {
        self.directory
            .join(Digest32::of_bytes(&checked(request.digest())).to_string())
    }
}

impl CellGenerationControlPortV2 for Control {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        self.signals.calls.fetch_add(1, Ordering::SeqCst);
        let mut cost = cost();
        checked(cost.record(CellCostEntryV2 {
            event_id: request.digest()?,
            identity: cost.identity(),
            stage: CellCostStageV2::Inference,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                cpu_micros: Some(7),
                ..CellCostMetricsV2::default()
            },
        }));
        let proposal = CellGenerationProposalV2 {
            request_digest: request.digest()?,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: request.input.clone(),
            output_delta: format!("observed:{}\n", request.operation_id).into_bytes(),
            disposition: CellGenerationDispositionV2::Advanced,
            cost,
        };
        let mut file = checked(
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(self.result_path(request)),
        );
        checked(file.write_all(&checked(serde_json::to_vec(&proposal))));
        checked(file.sync_all());
        if self.signals.lose_response.load(Ordering::SeqCst) {
            Err(CellGenerationErrorV2::Unavailable)
        } else {
            Ok(proposal)
        }
    }

    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        self.signals.reads.fetch_add(1, Ordering::SeqCst);
        assert!(!self.signals.panic_on_read.load(Ordering::SeqCst));
        if !self.signals.readable.load(Ordering::SeqCst) {
            return Ok(None);
        }
        let path = self.result_path(request);
        if !path.exists() {
            return Ok(None);
        }
        let proposal: CellGenerationProposalV2 =
            checked(serde_json::from_slice(&checked(fs::read(path))));
        assert_eq!(proposal.request_digest, request.digest()?);
        Ok(Some(proposal))
    }

    fn cancel_generation(
        &mut self,
        _request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        self.signals.cancellations.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

pub(super) fn cost() -> CellTaskCostV2 {
    checked(CellTaskCostV2::new(CellTaskCostIdentityV2 {
        task_digest: [17; 32],
        source_digest: [1; 32],
    }))
}

pub(super) fn request(
    operation_id: &str,
    predecessor: CellRuntimeSnapshotV2,
) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: operation_id.into(),
        task_digest: [17; 32],
        source_frontier: [16; 32],
        predecessor,
        input: vec![1, 2, 3],
        admitted_at_micros: 10,
        deadline_micros: 10_000,
    }
}

pub(super) struct Fixture {
    pub directory: tempfile::TempDir,
    pub identity: AgentdIdentity,
    pub registry: FleetRegistry,
    state: Option<Arc<AgentdState>>,
    pub control: Control,
    pub config: CellGenerationConfigV2,
    pub ticks: Arc<AtomicU64>,
}

impl Fixture {
    pub(super) async fn new() -> Self {
        let directory = checked(tempfile::tempdir());
        let root = checked(directory.path().canonicalize());
        let fleet_path = root.join("fleet");
        let fleet_root = checked(HeptaFleetRoot::parse(fleet_path.clone()));
        let registry = checked(FleetRegistry::initialize(fleet_root.clone()));
        let workspace = root.join("workspace");
        checked(fs::create_dir(&workspace));
        let agent_id = checked(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"));
        let binding = checked(WorkspaceBinding::new(&workspace, &fleet_root));
        let manifest = checked(AgentManifest::new(
            agent_id.clone(),
            binding,
            ResourceBudget::local_default(),
        ));
        let record = checked(registry.register(manifest));
        checked(registry.compare_and_transition(
            &agent_id,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        ));
        let identity = AgentdIdentity {
            agent_id,
            layout: record.layout.clone(),
            spawn_generation: 1,
            fleet_root: fleet_path,
            workspace,
            resources: record.manifest.resources,
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            app_server_socket: record.layout.app_server_socket().to_path_buf(),
        };
        let state = Arc::new(checked(AgentdState::new(
            identity.clone(),
            registry.clone(),
            /*event_capacity*/ 128,
        )));
        let results = root.join("control-results");
        checked(fs::create_dir(&results));
        let control = Control {
            directory: results,
            signals: Arc::new(Signals::default()),
        };
        let config = journal_config(identity.agent_id.as_str());
        let fixture = Self {
            directory,
            identity,
            registry,
            state: Some(state),
            control,
            config,
            ticks: Arc::new(AtomicU64::new(20)),
        };
        fixture.attach_prerequisites().await;
        checked(fixture.registry.compare_and_transition(
            &fixture.identity.agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        ));
        checked(fixture.state().refresh_generation());
        checked(fixture.state().mark_app_server_ready());
        fixture
    }

    pub(super) fn state(&self) -> &Arc<AgentdState> {
        self.state
            .as_ref()
            .unwrap_or_else(|| panic!("live fixture state"))
    }

    async fn attach_prerequisites(&self) {
        let store = checked(
            codex_hepta_cognitive_store::DurableCognitiveStore::open(&self.identity.layout).await,
        );
        checked(self.state().attach_cognitive_store(Arc::new(store)));
        checked(self.state().mark_runtime_prerequisites_ready());
    }

    pub(super) async fn reopen_state(&mut self) {
        drop(self.state.take());
        self.state = Some(Arc::new(checked(AgentdState::new(
            self.identity.clone(),
            self.registry.clone(),
            /*event_capacity*/ 128,
        ))));
        self.attach_prerequisites().await;
        checked(self.state().refresh_generation());
        checked(self.state().mark_app_server_ready());
    }

    pub(super) fn begin_drain(&self) {
        checked(self.registry.compare_and_transition(
            &self.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        ));
        checked(self.state().refresh_generation());
        checked(self.state().mark_draining());
    }

    pub(super) fn journal(&self) -> CellGenerationJournalV2<FileAnchorWitnessStore> {
        let open = |name: &str| {
            checked(
                OpenOptions::new()
                    .create(true)
                    .truncate(false)
                    .read(true)
                    .write(true)
                    .open(self.directory.path().join(name)),
            )
        };
        let witness = checked(FileAnchorWitnessStore::open(
            open("generation-witness"),
            JournalScope {
                scope_digest: Digest32::of_bytes(b"generation-service"),
                objective_digest: Digest32::of_bytes(b"generation-task"),
            },
            generation(1),
            /*max_records*/ 256,
        ));
        checked(CellGenerationJournalV2::open(
            open("generation-journal"),
            witness,
            self.config.clone(),
            /*max_records*/ 256,
        ))
    }

    pub(super) fn clock(&self) -> impl FnMut() -> u64 + Send + 'static {
        let ticks = Arc::clone(&self.ticks);
        move || ticks.fetch_add(1, Ordering::SeqCst)
    }
}

fn journal_config(agent_id: &str) -> CellGenerationConfigV2 {
    let manifest = CellBackendManifestV2 {
        profile: "generation-service-test".into(),
        source_digest: [1; 32],
        bundle_digest: [2; 32],
        encoder: Some([3; 32]),
        head: None,
        memory: None,
        world_model: None,
        decoder: Some([4; 32]),
        runtime_digest: [5; 32],
        device_digest: [6; 32],
        input_schema: [7; 32],
        state_schema: [8; 32],
        output_schema: [9; 32],
        learning: CellLearningBindingV2::Frozen { weights: [10; 32] },
        evolution: CellEvolutionBindingV2 {
            structure: [11; 32],
            lineage: [12; 32],
            source_dependencies: [13; 32],
            adoption_receipt: [14; 32],
        },
        max_input_bytes: 64,
        max_state_bytes: 64,
        max_delta_bytes: 128,
        max_prefix_bytes: 1024,
        max_step_cost_entries: 32,
        max_ack_cost_entries: 16,
    };
    CellGenerationConfigV2 {
        initial: CellRuntimeSnapshotV2 {
            scope: CellGenerationScopeV2 {
                principal_digest: [15; 32],
                agent_id: agent_id.into(),
                cell_id: "cell".into(),
                run_id: "generation-task".into(),
            },
            manifest_digest: checked(manifest.digest()),
            generation: 41,
            writer_epoch: 7,
            revision: 0,
            state: vec![0],
            prefix: Vec::new(),
            stopped: false,
        },
        manifest,
        source_frontier: [16; 32],
        task_digest: [17; 32],
    }
}
