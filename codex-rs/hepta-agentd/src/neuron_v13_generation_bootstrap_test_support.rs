//! Invalid closure assets exercise the actual Python rejection path. These
//! bytes are neither trained weights nor a successful V13 inference fixture.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_neuron::*;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;

use super::super::*;
use crate::AgentdState;

pub(super) struct Fixture {
    _directory: tempfile::TempDir,
    pub identity: AgentdIdentity,
    pub registry: FleetRegistry,
    pub prepared: AgentdV13GenerationWorkerV1,
    pub config: AgentdV13GenerationBootstrapConfigV1,
    pub paths: [PathBuf; 3],
    pub model_path: PathBuf,
}

impl Fixture {
    pub fn new() -> Result<Self> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet_root.clone())?;
        let workspace = root.join("workspace");
        fs::create_dir(&workspace)?;
        let agent_id =
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").map_err(anyhow::Error::msg)?;
        let record = registry.register(AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(&workspace, &fleet_root)?,
            ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(
            &agent_id,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )?;
        let identity = AgentdIdentity {
            agent_id,
            layout: record.layout.clone(),
            spawn_generation: 1,
            fleet_root: root.join("fleet"),
            workspace,
            resources: record.manifest.resources,
            home_root: record.layout.home_root().into(),
            run_root: record.layout.run_root().into(),
            control_socket: record.layout.agentd_control_socket().into(),
            app_server_socket: record.layout.app_server_socket().into(),
        };
        let script =
            include_bytes!("../../../qualification/neuron-v13-generation/proposal_worker.py");
        let script_path = root.join("proposal_worker.py");
        fs::write(&script_path, script)?;
        let names = [
            "vendor/bounded_npz.py",
            "vendor/closure_common.py",
            "vendor/closure_inputs.py",
            "vendor/closure_io.py",
            "vendor/verify_closure.py",
            "vendor/PROVENANCE.json",
            "vendor/reference/adapter.py.source",
            "vendor/reference/backend.py.source",
            "vendor/reference/download_model.py.source",
            "vendor/reference/lifecycle.py.source",
            "vendor/reference/tasks.py.source",
            "model.npz",
            "sources.json",
            "training.npz",
            "encoder.json",
            "release.json",
            "encoder/onnx/model.onnx",
            "encoder/tokenizer.json",
            "encoder/config.json",
            "encoder/sentence_bert_config.json",
            "encoder/modules.json",
            "encoder/1_Pooling/config.json",
            "encoder/tokenizer_config.json",
            "encoder/special_tokens_map.json",
        ];
        let mut assets = Vec::new();
        for (index, name) in names.into_iter().enumerate() {
            let path = root.join(format!("invalid-asset-{index}"));
            fs::write(&path, b"deliberately-invalid-closure")?;
            assets.push(V13GenerationAssetFileV1 {
                name: name.into(),
                digest: Digest32::of_bytes(b"deliberately-invalid-closure").into_array(),
                file: File::open(path)?,
            });
        }
        let closure = V13LearningClosureV1 {
            checkpoint_digest: Digest32::of_bytes(b"deliberately-invalid-closure").into_array(),
            state_digest: [21; 32],
            encoder_digest: [22; 32],
            source_version: [23; 32],
            data_identity: [24; 32],
            learning: CellLearningBindingV2::Resumable {
                weights: [25; 32],
                optimizer: [26; 32],
                rng: [27; 32],
                sampler: [28; 32],
                training_cursor: [29; 32],
            },
        };
        let interpreter = fs::canonicalize("/usr/bin/python3")?;
        let device_digest = V13GenerationProcessWorkerV1::observed_device_digest()?;
        let source_digest =
            Digest32::of_bytes(b"invalid-closure-agentd-bootstrap-test-v1").into_array();
        let prepared = prepare_agentd_v13_generation_worker_v1(
            V13GenerationProcessConfigV1 {
                interpreter_argv0: interpreter.clone(),
                interpreter_digest: Digest32::of_bytes(&fs::read(&interpreter)?).into_array(),
                worker_digest: Digest32::of_bytes(script).into_array(),
                source_digest,
                device_digest,
                closure: closure.clone(),
                phase_cpu_seconds: 3,
                address_space_bytes: 512 * 1024 * 1024,
                wall_limit: Duration::from_secs(10),
            },
            V13GenerationProcessFilesV1 {
                interpreter: File::open(interpreter)?,
                worker: File::open(script_path)?,
                assets,
            },
        )?;
        let manifest = CellBackendManifestV2 {
            profile: V13GenerationProcessWorkerV1::PROFILE.into(),
            source_digest,
            bundle_digest: prepared.worker().bundle_digest(),
            encoder: Some(closure.encoder_digest),
            head: Some([25; 32]),
            memory: None,
            world_model: None,
            decoder: None,
            runtime_digest: prepared.worker().runtime_digest(),
            device_digest,
            input_schema: V13GenerationProcessWorkerV1::input_schema_digest(),
            state_schema: V13GenerationProcessWorkerV1::state_schema_digest(),
            output_schema: V13GenerationProcessWorkerV1::output_schema_digest(),
            learning: closure.learning,
            evolution: CellEvolutionBindingV2 {
                structure: [11; 32],
                lineage: [12; 32],
                source_dependencies: [13; 32],
                adoption_receipt: [14; 32],
            },
            max_input_bytes: 8192,
            max_state_bytes: 1,
            max_delta_bytes: 8192,
            max_prefix_bytes: 65536,
            max_step_cost_entries: 8,
            max_ack_cost_entries: 1,
        };
        let config = AgentdV13GenerationBootstrapConfigV1 {
            expected_identity_digest: neuron_generation_process_identity_digest_v1(&identity)?,
            expected_boot_id_digest: prepared.boot_id_digest(),
            generation: CellGenerationConfigV2 {
                initial: CellRuntimeSnapshotV2 {
                    scope: CellGenerationScopeV2 {
                        principal_digest: [15; 32],
                        agent_id: identity.agent_id.to_string(),
                        cell_id: "v13-invalid-closure".into(),
                        run_id: "bootstrap-test".into(),
                    },
                    manifest_digest: manifest.digest()?,
                    generation: 41,
                    writer_epoch: 7,
                    revision: 0,
                    state: Vec::new(),
                    prefix: Vec::new(),
                    stopped: false,
                },
                manifest,
                source_frontier: closure.source_version,
                task_digest: [17; 32],
            },
            max_records: 128,
            control_capacity: 16,
            queue_capacity: 4,
            rpc_timeout: Duration::from_secs(1),
        };
        let paths = [
            root.join("cell"),
            root.join("witness"),
            root.join("control"),
        ];
        for path in &paths {
            OpenOptions::new()
                .create_new(true)
                .write(true)
                .mode(0o600)
                .open(path)?;
        }
        Ok(Self {
            _directory: directory,
            identity,
            registry,
            prepared,
            config,
            paths,
            model_path: root.join("invalid-asset-11"),
        })
    }

    pub fn files(&self) -> Result<V13GenerationOwnerFilesV1> {
        let open = |index: usize| {
            OpenOptions::new()
                .read(true)
                .write(true)
                .append(index == 2)
                .open(&self.paths[index])
        };
        Ok(V13GenerationOwnerFilesV1 {
            journal: open(0)?,
            witness: open(1)?,
            control: open(2)?,
        })
    }

    pub fn owner_bytes(&self) -> Result<Vec<Vec<u8>>> {
        self.paths
            .iter()
            .map(|path| fs::read(path).map_err(Into::into))
            .collect()
    }

    pub async fn state(&self) -> Result<Arc<AgentdState>> {
        let state = Arc::new(AgentdState::new(
            self.identity.clone(),
            self.registry.clone(),
            /*event_capacity*/ 128,
        )?);
        let store =
            codex_hepta_cognitive_store::DurableCognitiveStore::open(&self.identity.layout).await?;
        state.attach_cognitive_store(Arc::new(store))?;
        state.mark_runtime_prerequisites_ready()?;
        state.refresh_generation()?;
        state.mark_app_server_ready()?;
        Ok(state)
    }
}
