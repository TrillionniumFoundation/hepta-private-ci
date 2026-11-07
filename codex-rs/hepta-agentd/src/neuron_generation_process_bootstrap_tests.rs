use std::fs;
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
use pretty_assertions::assert_eq;
use serde_json::Value;
use tokio::time::sleep;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::*;
use crate::AgentdState;
use crate::RuntimeTasks;
use crate::neuron_generation_service::spawn_neuron_generation_service;

use crate::neuron_generation_test_support as fixture;

struct Fixture {
    directory: tempfile::TempDir,
    registry: FleetRegistry,
    identity: AgentdIdentity,
    descriptor: Value,
    path: PathBuf,
    assets: fixture::FixtureAssets,
}

impl Fixture {
    fn new() -> Result<Self> {
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
        let (descriptor, assets) = fixture::descriptor(&root, &identity)?;
        let path = root.join("bootstrap.json");
        Ok(Self {
            directory,
            registry,
            identity,
            descriptor,
            path,
            assets,
        })
    }

    fn load(
        &self,
    ) -> Result<
        (
            NeuronGenerationRuntimeHandleV2,
            NeuronGenerationRuntimeBootstrapV2,
        ),
        AgentdError,
    > {
        let bytes = serde_json::to_vec(&self.descriptor)?;
        fs::write(&self.path, &bytes)?;
        load_neuron_generation_process_bootstrap_v1(
            &self.path,
            Digest32::of_bytes(&bytes),
            &self.identity,
        )
    }

    async fn state(&self) -> Result<Arc<AgentdState>> {
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

#[test]
fn identity_assets_clock_and_descriptor_are_checked_before_any_owner_creation() -> Result<()> {
    let f = Fixture::new()?;
    let digest = fixture::write_descriptor(&f.path, &f.descriptor)?;
    assert!(
        load_neuron_generation_process_bootstrap_v1(&f.path, Digest32::ZERO, &f.identity).is_err()
    );
    for changed in [0, 1, 2, 3] {
        let mut identity = f.identity.clone();
        match changed {
            0 => identity.workspace = f.directory.path().join("other-workspace"),
            1 => identity.resources.memory_limit_mib += 1,
            2 => identity.control_socket = f.directory.path().join("other.ctl"),
            3 => identity.spawn_generation += 1,
            _ => unreachable!(),
        }
        assert!(load_neuron_generation_process_bootstrap_v1(&f.path, digest, &identity).is_err());
    }
    let mut zero_generation = f.identity.clone();
    zero_generation.spawn_generation = 0;
    let mut zero_descriptor = f.descriptor.clone();
    zero_descriptor["identity_digest"] =
        Value::String(neuron_generation_process_identity_digest_v1(&zero_generation)?.to_string());
    let pinned = fixture::write_descriptor(&f.path, &zero_descriptor)?;
    assert!(
        load_neuron_generation_process_bootstrap_v1(&f.path, pinned, &zero_generation).is_err()
    );
    for (field, value) in [
        (
            "boot_id",
            Value::String("00000000-0000-0000-0000-000000000000".into()),
        ),
        ("mode", Value::String("auto".into())),
        ("worker_generation", Value::from(8)),
    ] {
        let mut altered = f.descriptor.clone();
        altered[field] = value;
        let pinned = fixture::write_descriptor(&f.path, &altered)?;
        assert!(load_neuron_generation_process_bootstrap_v1(&f.path, pinned, &f.identity).is_err());
    }
    let mut altered = f.descriptor.clone();
    altered["weights"]["digest"] = Value::String("f".repeat(64));
    let pinned = fixture::write_descriptor(&f.path, &altered)?;
    assert!(load_neuron_generation_process_bootstrap_v1(&f.path, pinned, &f.identity).is_err());
    for name in ["cell.journal", "independent.witness", "control.journal"] {
        assert!(!f.directory.path().join(name).exists());
    }
    Ok(())
}

#[test]
fn paths_reject_aliases_and_reopen_never_falls_back_to_creation() -> Result<()> {
    let mut f = Fixture::new()?;
    f.descriptor["mode"] = Value::String("reopen".into());
    assert!(f.load().is_err());
    assert!(!f.directory.path().join("cell.journal").exists());
    f.descriptor["mode"] = Value::String("create".into());
    let original = f.descriptor.clone();
    f.descriptor["witness_path"] = f.descriptor["journal_path"].clone();
    assert!(f.load().is_err());
    f.descriptor = original.clone();
    let link = f.directory.path().join("alias-public");
    fs::hard_link(f.directory.path().join("synthetic-weights.hps"), &link)?;
    f.descriptor["public"]["path"] = serde_json::to_value(link)?;
    assert!(f.load().is_err());
    f.descriptor = original;
    let link = f.directory.path().join("linked-owner");
    std::os::unix::fs::symlink(f.directory.path().join("synthetic-public.hps"), &link)?;
    f.descriptor["journal_path"] = serde_json::to_value(link)?;
    assert!(f.load().is_err());
    assert!(!f.directory.path().join("cell.journal").exists());
    Ok(())
}

#[test]
fn actual_opened_files_reject_raced_aliases_and_non_regular_assets() -> Result<()> {
    use std::os::unix::ffi::OsStrExt;

    let mut f = Fixture::new()?;
    f.descriptor["mode"] = Value::String("reopen".into());
    for name in ["cell.journal", "independent.witness", "control.journal"] {
        fs::write(f.directory.path().join(name), b"existing owner bytes")?;
    }
    fixture::write_descriptor(&f.path, &f.descriptor)?;
    let descriptor: linux::Descriptor = serde_json::from_value(f.descriptor.clone())?;
    files::validate_paths(&f.path, &descriptor)?;
    let (_, descriptor_file) = files::read_bounded(&f.path, 262_144)?;
    let assets = files::open_assets(&descriptor)?;
    let public_before = fs::read(&descriptor.public.path)?;
    fs::remove_file(&descriptor.control_path)?;
    fs::hard_link(&descriptor.public.path, &descriptor.control_path)?;
    assert!(matches!(
        files::open_owners(&descriptor, &[
            &descriptor_file, &assets.executable, &assets.weights, &assets.public,
        ]),
        Err(AgentdError::Invalid(message)) if message.contains("alias the same inode")
    ));
    assert_eq!(fs::read(&descriptor.public.path)?, public_before);
    assert_eq!(fs::read(&descriptor.journal_path)?, b"existing owner bytes");
    assert_eq!(fs::read(&descriptor.witness_path)?, b"existing owner bytes");

    fs::remove_file(&descriptor.control_path)?;
    fs::write(&descriptor.control_path, b"existing owner bytes")?;
    files::validate_paths(&f.path, &descriptor)?;
    fs::remove_file(&descriptor.weights.path)?;
    let fifo = std::ffi::CString::new(descriptor.weights.path.as_os_str().as_bytes())?;
    // SAFETY: fifo owns a NUL-terminated path for the entire call; the mode has
    // only permission bits. The temporary path belongs to this fixture.
    if unsafe { libc::mkfifo(fifo.as_ptr(), 0o600) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // A regular-file precheck happened before replacement. O_NONBLOCK on the
    // actual open prevents this FIFO from waiting for a writer, then fstat rejects it.
    assert!(matches!(
        files::open_assets(&descriptor),
        Err(AgentdError::Invalid(message)) if message.contains("regular file")
    ));
    assert_eq!(fs::read(&descriptor.journal_path)?, b"existing owner bytes");
    Ok(())
}

async fn compute(
    handle: &NeuronGenerationRuntimeHandleV2,
    config: &CellGenerationConfigV2,
    public_digest: [u8; 32],
    id: &str,
    command: JointGenerationCommandV1,
) -> Result<(CellGenerationRequestV2, CellGenerationReceiptV2)> {
    let now = linux::boottime_micros()?;
    let request = CellGenerationRequestV2 {
        operation_id: id.into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: handle.snapshot().await?,
        input: serde_json::to_vec(&JointGenerationInputV1 {
            public_digest,
            command,
        })?,
        admitted_at_micros: now,
        deadline_micros: now + 30_000_000,
    };
    let first = handle.step(request.clone()).await;
    let receipt = timeout(Duration::from_secs(30), async {
        let mut observed = first;
        loop {
            match observed {
                Ok(receipt) => return Ok(receipt),
                Err(CellGenerationErrorV2::Pending) => sleep(Duration::from_millis(2)).await,
                Err(error) => return Err(error),
            }
            observed = handle.reconcile(request.digest()?).await;
        }
    })
    .await??;
    Ok((request, receipt))
}

#[tokio::test]
async fn actual_joint_reopens_the_same_clock_journal_prefix_and_original_result() -> Result<()> {
    let mut f = Fixture::new()?;
    let config: CellGenerationConfigV2 = serde_json::from_value(f.descriptor["config"].clone())?;
    let public_digest = f.descriptor["public"]["digest"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("public digest"))?
        .parse::<Digest32>()?
        .into_array();
    let (handle, bootstrap) = f.load()?;
    assert!(f.load().is_err()); // Explicit create cannot reuse existing stores.
    f.registry.compare_and_transition(
        &f.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    let state = f.state().await?;
    let cancellation = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(2))?;
    spawn_neuron_generation_service(&mut tasks, bootstrap, state.clone(), cancellation)?;
    let (_, initialized) = compute(
        &handle,
        &config,
        public_digest,
        "init",
        JointGenerationCommandV1::Init {
            seed: 17,
            sampler: JointGenerationSamplerV1::Mean,
        },
    )
    .await?;
    assert_eq!(
        initialized.disposition,
        CellGenerationDispositionV2::Advanced
    );
    // These fixed synthetic weights prohibit initial STOP. Exercise one real
    // continuation before stopping, without changing the model's legal actions.
    let (_, advanced) = compute(
        &handle,
        &config,
        public_digest,
        "shared",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Shared,
        },
    )
    .await?;
    assert_eq!(advanced.disposition, CellGenerationDispositionV2::Advanced);
    let (stop, receipt) = compute(
        &handle,
        &config,
        public_digest,
        "stop",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Stop,
        },
    )
    .await?;
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Stopped);
    let snapshot = handle.snapshot().await?;
    fixture::verify_stopped(&snapshot.state, &snapshot.prefix, &f.assets)?;
    let output = handle.pending_output().await?;
    assert!(output.is_some());
    let cost = handle.task_cost().await?;
    assert!(!handle.drain().await?);
    tasks.shutdown().await;
    assert!(tasks.failures().is_empty());
    drop(handle);
    drop(state);
    f.descriptor["mode"] = Value::String("reopen".into());
    let before_clock = linux::boottime_micros()?;
    let (handle, bootstrap) = timeout(Duration::from_secs(5), async {
        loop {
            match f.load() {
                Ok(value) => return Ok(value),
                Err(AgentdError::Invalid(message)) if message.contains("WriterUnavailable") => {
                    sleep(Duration::from_millis(2)).await
                }
                Err(error) => return Err(error),
            }
        }
    })
    .await??;
    assert!(linux::boottime_micros()? >= before_clock);
    let before_control = fs::read(f.directory.path().join("control.journal"))?;
    let cancellation = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(2))?;
    spawn_neuron_generation_service(&mut tasks, bootstrap, f.state().await?, cancellation)?;
    assert_eq!(handle.snapshot().await?, snapshot);
    assert_eq!(handle.pending_output().await?, output);
    assert_eq!(handle.task_cost().await?, cost);
    assert_eq!(handle.step(stop).await?, receipt);
    assert_eq!(
        fs::read(f.directory.path().join("control.journal"))?,
        before_control
    );
    tasks.shutdown().await;
    drop(handle);
    let witness = f.directory.path().join("independent.witness");
    fs::write(&witness, [])?;
    assert!(f.load().is_err());
    assert_eq!(fs::metadata(witness)?.len(), 0);
    Ok(())
}
