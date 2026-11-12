//! Prepare only original inputs. The two production executables must perform
//! enrollment, Initial publication, Objective admission and the real A task.

use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::AgentId;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde_json::json;

use super::super::artifacts;
use super::super::fixture::assign_component_artifacts;
use super::super::material;
use super::super::observer_config;
use super::super::owned_mode;
use super::super::private_file;
use super::deployment::OriginalAFilePaths;
use super::inputs::ObjectiveInputs;
use super::root::OriginalRootInputs;
use super::root::write_bytes;
use super::root::write_json;

pub(super) struct OrdinaryAPlan {
    pub(super) protected: tempfile::TempDir,
    pub(super) runtime: tempfile::TempDir,
    pub(super) registered: crate::HostAuthorityRegisteredIdentity,
    pub(super) identity: crate::AgentdIdentity,
    pub(super) root: OriginalRootInputs,
    pub(super) deployment: crate::HostGenerationInitialDeploymentV1,
    pub(super) sealed: File,
    pub(super) objective: ObjectiveInputs,
    pub(super) files: OriginalAFilePaths,
    pub(super) target_journal: PathBuf,
    pub(super) target_witness: PathBuf,
    pub(super) objective_trust: PathBuf,
    pub(super) objective_profile: PathBuf,
    pub(super) replay_checkpoint: PathBuf,
    pub(super) observer_payload: PathBuf,
    pub(super) observer_key: PathBuf,
    // The baseline Artifact writer stays with its original administrator. A
    // receives only the authenticated Root Initial read view of these files.
    _artifact_owner: Arc<Mutex<LearningArtifactOwnerService>>,
}

impl OrdinaryAPlan {
    pub(super) fn prepare(runtime: &tokio::runtime::Runtime) -> anyhow::Result<Self> {
        // SAFETY: reads actual kernel credentials; never changes the test host.
        anyhow::ensure!(
            unsafe { (libc::getuid(), libc::geteuid()) } == (0, 0),
            "actual ordinary fixture requires UID0 administrator"
        );
        let parent = PathBuf::from(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT")
                .ok_or_else(|| anyhow::anyhow!("original protected bind required"))?,
        );
        let source_path = PathBuf::from(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE")
                .ok_or_else(|| anyhow::anyhow!("original protected bind source required"))?,
        );
        let metadata = std::fs::metadata(&parent)?;
        let required_bind = crate::HostAuthorityBindIdentity {
            mountpoint: parent.clone(),
            source_path,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        required_bind.verify()?;
        let protected = tempfile::Builder::new()
            .prefix("ordinary-q24-")
            .tempdir_in(&parent)?;
        owned_mode(protected.path(), 0, 0, 0o700)?;
        let run_directory = tempfile::Builder::new().prefix("oq-").tempdir_in("/run")?;
        owned_mode(run_directory.path(), 0, 60001, 0o2710)?;
        let workspace = run_directory.path().join("workspace");
        directory(&workspace, 0, 60001, 0o710)?;
        let fleet = HeptaFleetRoot::parse(run_directory.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
        owned_mode(fleet.as_path(), 0, 60001, 0o710)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(&workspace, &fleet)?,
            ResourceBudget::local_default(),
        )?)?;
        let starting = registry.compare_and_transition(&agent, 0, AgentLifecycle::Starting)?;
        let registered = crate::HostAuthorityRegisteredIdentity {
            agent_id: agent,
            spawn_generation: starting.generation,
            fleet_root: fleet.as_path().to_path_buf(),
            workspace,
            resources: ResourceBudget::local_default(),
        };
        let identity = registered.identity()?;
        drop(registry);
        let model_directory = run_directory.path().join("model");
        directory(&model_directory, 0, 0, 0o700)?;
        let (model, bundle, mut definition) = material::model(&model_directory)?;
        assign_component_artifacts(&model_directory)?;
        let now = crate::authbus_ingress::now_ms()?;
        let objective = ObjectiveInputs::new(&identity, &bundle, now)?;
        let objective_trust = identity.home_root.join("ordinary-objective-trust.json");
        let objective_profile = identity.home_root.join("ordinary-objective-profile.json");
        write_json(&objective_trust, &objective.trust)?;
        write_json(&objective_profile, &objective.profile)?;
        let replay_directory = run_directory.path().join("replay");
        directory(&replay_directory, 60001, 60001, 0o700)?;
        let replay_checkpoint = replay_directory.join("original.json");
        let frontier = runtime.block_on(original_replay_frontier(&identity))?;
        write_json(
            &replay_checkpoint,
            &json!({
                "schema_version":1, "agent_id":identity.agent_id.as_str(),
                "generation":1, "digest":frontier.to_string()
            }),
        )?;
        owned_mode(&replay_checkpoint, 60001, 60001, 0o600)?;
        let run_start_directory = identity.home_root.join("objective-run-start-v1");
        directory(&run_start_directory, 0, 0, 0o700)?;
        drop(private_file(&run_start_directory.join("journal.bin"))?);
        let data_directory = run_directory.path().join("data");
        let witnesses = run_directory.path().join("witnesses");
        directory(&data_directory, 60001, 60001, 0o700)?;
        directory(&witnesses, 60001, 60001, 0o700)?;
        let files = OriginalAFilePaths::new(&data_directory, &witnesses);
        for path in files.business_files() {
            if path == files.generator_key {
                write_bytes(&path, &[72; 32])?;
            } else {
                drop(private_file(&path)?);
            }
            owned_mode(&path, 60001, 60001, 0o600)?;
        }
        let mut original_source = material::source(identity.agent_id.as_str())?;
        original_source.scope.run_id = StableId::new(super::inputs::RUN)?;
        original_source.source_frontier = frontier;
        original_source.objective_digest = objective.objective;
        original_source.monotonic_micros = monotonic_micros()?;
        original_source.deadline_micros = original_source
            .monotonic_micros
            .checked_add(120_000_000)
            .ok_or_else(|| anyhow::anyhow!("Source deadline overflow"))?;
        original_source.lease_duration_ms = 120_000;
        definition.max_queue_age_micros = 120_000_000;
        let target = observer_config(material::configuration(
            &model,
            &bundle,
            &definition,
            &original_source,
            1,
        )?)?;
        let deployment = crate::HostGenerationInitialDeploymentV1::new(
            "ordinary-original-a-initial".into(),
            &target,
        )?;
        let target_journal = data_directory.join("initial.journal");
        let target_witness = witnesses.join("initial.witness");
        drop(private_file(&target_journal)?);
        drop(FileAnchorWitnessStore::open(
            private_file(&target_witness)?,
            target.witness_scope,
            target.witness_generation,
            target.witness_records,
        )?);
        for path in [&target_journal, &target_witness] {
            owned_mode(path, 60001, 60001, 0o600)?;
        }
        let artifacts_path = run_directory.path().join("artifacts");
        let artifacts =
            artifacts::Artifacts::new(&artifacts_path, &target.generation.manifest, now)?;
        assign_component_artifacts(&artifacts_path)?;
        let selected = artifacts.selection(now)?;
        let (_, description) =
            crate::neuron_generation_current::initial_root::original_initial_description(
                deployment.operation.clone(),
                deployment.target.clone(),
                &selected,
            )?;
        let root = OriginalRootInputs::initialize(
            protected.path(),
            run_directory.path(),
            required_bind,
            &registered,
            description.final_use_binding(),
            now,
        )?;
        let learning_trust = protected.path().join("learning-trust.json");
        let ledger_deployment = protected.path().join("ledger.json");
        let payload = super::inputs::original_learning_payload(objective.objective, now / 1_000)?;
        let observer_payload = protected.path().join("observer-public-trust.json");
        let observer_key = protected.path().join("original-observer.key");
        write_json(&observer_payload, &payload)?;
        write_bytes(&observer_key, &[73; 32])?;
        let root_key = protected.path().join("learning-root.json");
        let distribution = protected.path().join("signed-learning-distribution.json");
        write_json(&root_key, &payload.root)?;
        write_json(&distribution, &payload.distribution)?;
        let source_data =
            files.source_data(&identity, &definition, &original_source, &ledger_deployment)?;
        write_json(&root.source, &source_data)?;
        write_json(
            &learning_trust,
            &json!({
                "schema":1, "mode":"pinned_genesis_v1", "deployment":deployment,
                "learning_scope":payload.distribution.scope_digest, "objective":objective.objective.into_array(),
                "root_key":root_key, "distribution":distribution, "source_deployment":root.source,
                "generator":payload.generator, "observer":payload.observer
            }),
        )?;
        let ledger = super::inputs::ledger_data(&files, now / 1_000)?;
        write_json(
            &ledger_deployment,
            &json!({
                "schema":1, "purpose":"runtime.circuit.original-ledger-deployment.v1",
                "initial":deployment, "ledger":ledger, "learning_trust_deployment":learning_trust
            }),
        )?;
        write_json(
            &root.run_start,
            &json!({
                "schema_version":1, "purpose":"runtime.objective.original-run-start-deployment.v1",
                "journal":run_start_directory.join("journal.bin"),
                "objective_profile":objective_profile, "authbus_trust":objective_trust
            }),
        )?;
        let artifact_inputs = artifacts.inputs(now)?;
        let artifact_owner = artifacts.retain_original_writer();
        let transfer = serde_json::to_value(artifacts.into_transfer(now)?)?;
        let initial = root.initial_data(
            &identity,
            &deployment,
            &target,
            [&target_journal, &target_witness],
            &transfer,
            &artifact_inputs,
            &data_directory,
            &learning_trust,
        )?;
        let launch = json!({
            "schema":"hepta.agentd.original_initial_q24_launch.v1",
            "identity_digest":crate::neuron_generation_process_identity_digest_v1(&identity)?.to_string(),
            "clock":"linux_clock_monotonic_micros_v1", "initial":initial,
            "source":source_data, "ledger":ledger,
            "model":{"base":model_directory.join("base"),"encoder":model_directory.join("encoder"),
                "heads":model_directory.join("heads"),"organ_adapter":null,"cell_adapter":null},
            "bundle":{"artifact_id":bundle.artifact_id.as_str(),"generation":bundle.generation.get(),
                "training_lineage":null,"rollback_predecessor":null},
            "cell":files.cell_data(objective.objective), "inference_control":files.inference,
            "inference_capacity":32, "worker_generation":1, "maximum_cell_records":4, "queue_capacity":4
        });
        let sealed =
            crate::authority_host_bootstrap_seal::seal_bytes(&serde_json::to_vec(&launch)?)?;
        Ok(Self {
            protected,
            runtime: run_directory,
            registered,
            identity,
            root,
            deployment,
            sealed,
            objective,
            files,
            target_journal,
            target_witness,
            objective_trust,
            objective_profile,
            replay_checkpoint,
            observer_payload,
            observer_key,
            _artifact_owner: artifact_owner,
        })
    }
}

async fn original_replay_frontier(identity: &crate::AgentdIdentity) -> anyhow::Result<Digest32> {
    let store = HeptaEvidenceStore::open(&codex_state::SqliteConfig::from_sqlite_home(
        codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&identity.home_root)?,
    ))
    .await?;
    let result = store.authbus_replay_frontier_digest().await;
    // The administrator releases the actual pool/WAL before Root hands the
    // original directory to the daemon. Drop is not a quiescence substitute.
    store.close().await;
    Ok(result?)
}

fn directory(path: &Path, uid: u32, gid: u32, mode: u32) -> anyhow::Result<()> {
    std::fs::create_dir(path)?;
    owned_mode(path, uid, gid, mode)
}

fn monotonic_micros() -> anyhow::Result<u64> {
    let mut time = std::mem::MaybeUninit::<libc::timespec>::uninit();
    // SAFETY: successful clock_gettime initializes this complete timespec.
    anyhow::ensure!(
        unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, time.as_mut_ptr()) } == 0,
        "{}",
        std::io::Error::last_os_error()
    );
    // SAFETY: the successful actual kernel call above initialized time.
    let time = unsafe { time.assume_init() };
    anyhow::ensure!(
        time.tv_sec >= 0 && (0..1_000_000_000).contains(&time.tv_nsec),
        "original monotonic clock"
    );
    Ok(u64::try_from(time.tv_sec)?
        .checked_mul(1_000_000)
        .and_then(|seconds| seconds.checked_add(time.tv_nsec as u64 / 1_000))
        .ok_or_else(|| anyhow::anyhow!("monotonic clock overflow"))?)
}
