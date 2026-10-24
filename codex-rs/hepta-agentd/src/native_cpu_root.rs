//! Root owns installation, original Supervisor lifecycle and service capture.
use super::*;
use crate::authority_host_config::HostAuthorityBindIdentity;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_config::HostAuthoritySocketPaths;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::Hos2DeliveryId;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_supervisor::KernelInitialProcessDriver;
use codex_hepta_supervisor::KernelInitialRole;
use codex_hepta_supervisor::KernelSuccessorImage;
use codex_hepta_supervisor::KernelSuccessorRole;
use codex_hepta_supervisor::RootKernelLauncher;
use codex_hepta_supervisor::SpawnSpec;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use sha2::Digest;
use sha2::Sha256;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::sync::Mutex;

#[path = "native_cpu_cold_open.rs"]
mod cold_open;
#[path = "native_cpu_continuity.rs"]
mod continuity;

#[path = "native_cpu_successor.rs"]
mod successor;
use successor::OwnerImage;
#[path = "native_cpu_lost_copyout.rs"]
mod lost_copyout;
#[path = "native_cpu_recovery.rs"]
mod recovery;

struct Installation {
    fleet: FleetRegistry,
    config: HostAuthorityServiceConfig,
    clock: Arc<HostAuthorityClock>,
    leases: Arc<AuthorityLeaseRegistry>,
    issuer: Arc<crate::DeploymentFinalUseIssuer>,
    initial: CognitiveRecoveryAnchor,
    archive: PathBuf,
    checkpoint: PathBuf,
    scopes: [[u8; 32]; 2],
    recovery: Option<recovery::PreparedRecovery>,
    launcher: Arc<RootKernelLauncher>,
    launch_observations: Arc<RootAuthorityDirectory>,
}
pub(super) struct Active {
    pub(super) service: Arc<crate::HostAuthorityService>,
    pub(super) registration: HostAuthorityRegistration,
    pub(super) bundle: crate::HostAuthorityPublicBootstrapV1,
    pub(super) rpc: commands::Rpc,
    release: commands::Rpc,
    pub(super) archive: PathBuf,
    pub(super) retained: crate::RetainedCheckpointPublisher,
    server: Option<std::thread::JoinHandle<io::Result<()>>>,
    adopted: Option<codex_hepta_memory::CognitiveCheckpointReceipt>,
    image: OwnerImage,
    root_lease: AuthorityLease,
}

impl Active {
    fn join_retired_lanes(&mut self) -> io::Result<()> {
        // A lane error is accepted for teardown only after independent actual
        // publisher retirement. It is never proof of earlier service health.
        crate::RetiredCheckpointPublisher::observe(self.retained.lifetime().clone())
            .map_err(error)?;
        if let Some(server) = self.server.take() {
            let result = server
                .join()
                .map_err(|_| invalid("original Root lane panicked"))?;
            if let Err(failure) = result {
                let diagnostic = failure.to_string().chars().take(512).collect::<String>();
                eprintln!(
                    "hepta-native: lane termination after observed publisher exit, pid {}: {diagnostic}",
                    self.registration.peer_pid
                );
            }
        }
        Ok(())
    }
}

fn write_json(path: &Path, value: &impl serde::Serialize) -> io::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    file.write_all(&serde_json::to_vec(value).map_err(error)?)?;
    file.sync_all()?;
    File::open(path.parent().ok_or_else(|| invalid("JSON parent"))?)?.sync_all()
}
fn listener(path: &Path, gid: u32) -> io::Result<UnixListener> {
    let listener = UnixListener::bind(path)?;
    std::os::unix::fs::chown(path, Some(0), Some(gid))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))?;
    listener.set_nonblocking(true)?;
    Ok(listener)
}
fn accept(listener: &UnixListener, deadline: u64) -> io::Result<std::os::unix::net::UnixStream> {
    loop {
        remaining(deadline)?;
        match listener.accept() {
            Ok((stream, _)) => return Ok(stream),
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(5))
            }
            Err(e) => return Err(e),
        }
    }
}
fn scope(boot: &NativeBootstrap, offset: usize) -> io::Result<[u8; 32]> {
    let request = Hos2InstallBudgetV1 {
        schema_version: 1,
        delivery: Hos2DeliveryId::new(boot.id(96), boot.id(offset), 1).map_err(error)?,
        manage_slot: 2,
        manage_generation: 1,
        expected_revision: 1,
        period_ns: 100_000_000,
        cap_ns: 50_000_000,
    };
    Ok(request.scope_digest().into_array())
}
impl Installation {
    fn fresh(boot: &NativeBootstrap) -> io::Result<Self> {
        let owner = AgentId::parse(AGENT).map_err(error)?;
        let workspace = Path::new(STATE).join("workspace");
        platform::private_dir(&workspace, 60001, 60001, 0o700)?;
        let fleet_root = HeptaFleetRoot::parse(Path::new(STATE).join("fleet")).map_err(error)?;
        let fleet = FleetRegistry::initialize(fleet_root.clone()).map_err(error)?;
        let record = fleet
            .register(
                AgentManifest::new(
                    owner.clone(),
                    WorkspaceBinding::new(workspace, &fleet_root).map_err(error)?,
                    ResourceBudget::local_default(),
                )
                .map_err(error)?,
            )
            .map_err(error)?;
        let layout = record.layout;
        // Fresh SQLite administration precedes any writer. Its actual complete
        // cut enters the original protected checkpoint, never a guessed hash.
        let initial = runtime()?.block_on(async {
            let store = CognitiveStore::open(&layout).await.map_err(error)?;
            let cut = store.recovery_anchor().await.map_err(error)?;
            store.close().await;
            Ok::<_, io::Error>(cut)
        })?;
        permissions::handoff_fresh(fleet.layout(), &layout)?;
        let protected = Path::new(STATE).join("protected");
        let metadata = std::fs::metadata(&protected)?;
        let required_bind = HostAuthorityBindIdentity {
            mountpoint: protected.clone(),
            source_path: Path::new(STATE).join("protected-source"),
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        let scopes = [scope(boot, 112)?, scope(boot, 128)?];
        let policies = scopes
            .iter()
            .map(|scope| crate::DeploymentGrantPolicy {
                subject_id: owner.to_string(),
                destination_id: codex_hepta_memory::HOS2_DESTINATION_V1.into(),
                scope_sha256: *scope,
                lifetime_ms: 5_000,
            })
            .collect::<Vec<_>>();
        let bootstrap = protected.join("bootstrap.json");
        write_json(
            &bootstrap,
            &serde_json::json!({"schema_version":1,"required_bind":required_bind,
            "signer_id":"native-cpu-original-root","policies":policies,"lease_id":"native-cpu-root-installation",
            "lease_binding":AuthorityLeaseBinding {principal_id:owner.to_string(),operation_class:"runtime.agentd.production_operation".into(),
                destination_id:codex_hepta_memory::HOS2_DESTINATION_V1.into(),scope_sha256:scopes[0],payload_sha256:Sha256::digest(b"native-root-installation-observation-only").into()},
            "lease_lifetime_ms":120_000}),
        )?;
        let state = protected.join("authority");
        let initialized = crate::initialize_host_authority(&state, &bootstrap)?;
        let runtime_dir = Path::new(RUNTIME).join("owner");
        platform::private_dir(&runtime_dir, 0, 60001, 0o2710)?;
        platform::private_dir(
            &Path::new(STATE).join("consumer-local"),
            60001,
            60001,
            0o700,
        )?;
        platform::mount_consumer_state()?;
        let config = HostAuthorityServiceConfig {
            schema_version: 1,
            state_dir: state.clone(),
            required_bind,
            signer_id: initialized.signer_id,
            expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id,
            lease_revision: 1,
            writer: None,
            checkpoint_state_dir: None,
            consumers: None,
            sockets: HostAuthoritySocketPaths {
                observation: runtime_dir.join("observation.sock"),
                issuer: runtime_dir.join("issuer.sock"),
                checkpoint: runtime_dir.join("checkpoint.sock"),
                device_frontier: Some(runtime_dir.join("device-frontier.sock")),
                notes_frontier: Some(runtime_dir.join("notes-frontier.sock")),
            },
            peer_uid: 60001,
            peer_gid: 60001,
            timeout_ms: 5_000,
            lifetime_ms: LIFETIME.as_millis() as u64,
        };
        let (clock, leases, issuer) =
            crate::authority_host_runtime::open_registered_issuer(&config)?;
        let archive = state.join("material");
        let checkpoint = state.join("checkpoint");
        for path in [&archive, &checkpoint] {
            platform::private_dir(path, 0, 0, 0o700)?;
        }
        let launch_observations = state.join("native-launch-observations");
        platform::private_dir(&launch_observations, 0, 0, 0o700)?;
        let launch_observations =
            RootAuthorityDirectory::open(&launch_observations).map_err(error)?;
        let launcher = Arc::new(RootKernelLauncher::open(&boot.bytes)?);
        let mut installation = Self {
            fleet,
            config,
            clock,
            leases: Arc::new(leases),
            issuer,
            initial,
            archive,
            checkpoint,
            scopes,
            recovery: None,
            launcher,
            launch_observations,
        };
        let head = installation.issuer.revocations()?;
        let consumer = |name: &str| -> io::Result<crate::HostAuthorityConsumerConfig> {
            let state_dir = state.join(name);
            platform::private_dir(&state_dir, 0, 0, 0o700)?;
            crate::HostConsumerFrontier::initialize_fresh(
                RootAuthorityDirectory::open(&state_dir).map_err(error)?,
                installation.config.signer_id.clone(),
                &head,
                installation.clock.clone(),
                installation.clock.now_unix_ms().map_err(error)? + 60_000,
            )
            .map_err(error)?;
            Ok(crate::HostAuthorityConsumerConfig {
                state_dir,
                owner_id: installation.config.signer_id.clone(),
            })
        };
        installation.config.consumers = Some(crate::HostAuthorityConsumersConfig {
            device: consumer("device-consumer")?,
            notes: consumer("notes-consumer")?,
        });
        installation.config.checkpoint_state_dir = Some(installation.checkpoint.clone());
        // The independently installed public-key pin survives process/boot
        // loss. A cold opener never learns trust by reading the issuer's key.
        cold_open::InstalledPin::save(&installation.config, boot)?;
        write_json(
            &Path::new(RUNTIME).join("owner-installed"),
            &serde_json::json!({"agent":owner}),
        )?;
        Ok(installation)
    }

    fn activate(
        &mut self,
        spec: &SpawnSpec,
        role: KernelInitialRole,
        owner: OwnedFd,
        deadline: u64,
    ) -> io::Result<Active> {
        let image = OwnerImage::initial(role);
        self.activate_image(spec, image, owner, deadline)
    }

    fn activate_image(
        &mut self,
        spec: &SpawnSpec,
        image: OwnerImage,
        owner: OwnedFd,
        deadline: u64,
    ) -> io::Result<Active> {
        let first = image.kernel.is_none()
            && image.role == 1
            && image.pid == 2
            && self.config.writer.is_none()
            && self.recovery.is_none();
        if !first && self.recovery.is_none() {
            return Err(invalid(
                "independent original predecessor Current and physical material required",
            ));
        }
        if !first {
            self.refresh_canonical_root_lease(spec)?;
        }
        let recovery = self.recovery.as_ref();
        let pid = image.pid;
        let name = image.runtime_name()?;
        let owner_peer = peer(pid, 60001)?;
        let root = peer(1, 0)?;
        let launch_listener = listener(&Path::new(RUNTIME).join(format!("{name}.launch")), 60001)?;
        let rpc_listener = listener(&Path::new(RUNTIME).join(format!("{name}.rpc")), 60001)?;
        let release_listener =
            listener(&Path::new(RUNTIME).join(format!("{name}.release")), 60001)?;
        let launch_stream = accept(&launch_listener, deadline)?;
        let mut launch = crate::RootNotesLaunchChannel::from_peer_stream(
            launch_stream,
            owner_peer.clone(),
            owner.try_clone()?,
            deadline,
        )?;
        let record = self
            .fleet
            .load()
            .map_err(error)?
            .agent(&spec.agent_id)
            .cloned()
            .ok_or_else(|| invalid("original registered owner missing"))?;
        let registered = crate::HostAuthorityRegisteredIdentity {
            agent_id: spec.agent_id.clone(),
            spawn_generation: spec.generation,
            fleet_root: spec.fleet_root.clone(),
            workspace: spec.workspace.clone(),
            resources: record.manifest.resources,
        };
        let identity = crate::authority_host_config::registered_identity(&registered)?;
        let now = self.clock.now_unix_ms().map_err(error)?;
        let writer = if let Some(previous) = recovery {
            self.recovered_writer(spec, previous)?
        } else {
            let writer = crate::HostAuthorityWriterRegistration {
                registered_agent_id: spec.agent_id.clone(),
                spawn_generation: spec.generation,
                owner_epoch: 1,
                local_lease_id: "native-cpu-original-writer".into(),
                local_lease_generation: 1,
                authority_lease: AuthorityLease {
                    schema_version: 1,
                    lease_id: cold_open::lease_id("writer", spec)?,
                    authority_epoch: 1,
                    revision: 1,
                    binding: AuthorityLeaseBinding {
                        principal_id: spec.agent_id.to_string(),
                        operation_class: "runtime.agentd.production_writer".into(),
                        destination_id: format!("cognitive.owner:{}", spec.agent_id),
                        scope_sha256: Sha256::digest(
                            serde_json::to_vec(&(&spec.agent_id, identity.layout.cognitive_root()))
                                .map_err(error)?,
                        )
                        .into(),
                        payload_sha256: Sha256::digest(
                            serde_json::to_vec(&self.initial).map_err(error)?,
                        )
                        .into(),
                    },
                    issued_at_unix_ms: now,
                    expires_at_unix_ms: now + ORIGINAL_WRITER_LIFETIME_MS,
                },
            };
            self.leases
                .put_lease(writer.authority_lease.clone(), 0)
                .map_err(error)?;
            self.issuer
                .register_writer_authorization(&writer, &self.leases.verifier())?;
            writer
        };
        let epoch = recovery.map_or(Ok(1), |previous| {
            previous
                .previous
                .head
                .publisher_epoch
                .checked_add(1)
                .ok_or_else(|| invalid("original publisher epoch overflow"))
        })?;
        let retained =
            crate::RetainedCheckpointPublisher::capture(owner_peer.clone()).map_err(error)?;
        if let Some(kernel) = &image.kernel
            && kernel.role() == KernelSuccessorRole::Manager
        {
            self.scopes =
                self.issuer
                    .replace_native_cpu_namespaces(&writer, kernel, self.scopes)?;
        }
        if image.kernel.is_none()
            && image.role == 1
            && let Some(previous) = recovery
            && previous.previous.head.peer_lifetime.boot_id != root.boot_id
        {
            self.scopes = self.issuer.replace_native_cpu_namespaces_after_boot(
                &writer,
                &self.launcher,
                &previous.previous,
                &previous.retired,
                self.scopes,
            )?;
        }
        let admission = if image.role == 5 {
            crate::deployment_issuer::RootNativeCpuGrantAdmission::from_registered_history(
                &self.issuer,
                self.leases.clone(),
                writer.clone(),
                image
                    .kernel
                    .as_ref()
                    .ok_or_else(|| invalid("history-only original factory witness absent"))?,
            )?
        } else {
            let scope = self.scopes[if image.role == 1 { 0 } else { 1 }];
            crate::deployment_issuer::RootNativeCpuGrantAdmission::from_registered_namespace(
                &self.issuer,
                self.leases.clone(),
                writer.clone(),
                scope,
                5_000,
            )?
        };
        let service = crate::HostAuthorityService::from_registered_owner(
            self.issuer.clone(),
            self.clock.clone(),
            identity,
        )?
        .with_registered_writer(writer.clone(), self.leases.verifier())?;
        let directory = RootAuthorityDirectory::open(&self.checkpoint).map_err(error)?;
        let service = match recovery {
            Some(previous) => service.with_recovered_checkpoint(
                directory,
                &previous.previous,
                &previous.retired,
                &retained,
                epoch,
                &previous.material,
            )?,
            None => service.initialize_native_cpu_checkpoint(
                directory,
                epoch,
                owner_peer.clone(),
                self.initial.clone(),
            )?,
        };
        let service = service
            .with_native_cpu_admission(admission)?
            .with_registered_consumers(
                &self.config.state_dir,
                self.config.consumers.as_ref().unwrap(),
            )?
            .with_required_material_startup(&self.archive)?;
        let paths = &self.config.sockets;
        let service = Arc::new(service.with_bootstrap_registration(
            crate::HostAuthorityBootstrapLocations {
                sockets: crate::HostAuthorityFiveLanePathsV1 {
                    observation: paths.observation.clone(),
                    issuer: paths.issuer.clone(),
                    checkpoint: paths.checkpoint.clone(),
                    device_frontier: paths.device_frontier.clone().unwrap(),
                    notes_frontier: paths.notes_frontier.clone().unwrap(),
                },
                device_local_state_dir: Path::new(RUNTIME).join("owner/consumer-local/device"),
                notes_local_state_dir: Path::new(RUNTIME).join("owner/consumer-local/notes"),
                lifetime: remaining(deadline)?,
            },
            owner.try_clone()?,
        )?);
        let bundle = service.capture_public_bootstrap()?;
        let adopted = if let Some(previous) = self.recovery.take() {
            if [
                bundle.consumers.device.frontier.clone(),
                bundle.consumers.notes.frontier.clone(),
            ] != previous.frontiers
            {
                return Err(invalid(
                    "original consumer handoff differs from the retained terminal frontiers",
                ));
            }
            let receipt = service.native_cpu_current()?;
            if receipt.head != bundle.checkpoint {
                return Err(invalid(
                    "actual original adoption receipt differs from sealed handoff",
                ));
            }
            let installed = service.install_recovered_owner_material(
                previous.material,
                &previous.retired,
                &retained,
            )?;
            installed.verify_unchanged().map_err(error)?;
            if installed.anchor() != &previous.previous.head.last_current {
                return Err(invalid("installed material differs from original Current"));
            }
            // Root releases the actual physical owner lock before sending the
            // sealed bootstrap and allowing the sole Host factory to open it.
            drop(installed);
            Some(receipt)
        } else {
            None
        };
        let registration = HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: owner_peer.pid,
            boot_id: owner_peer.boot_id.clone(),
            process_start_ticks: owner_peer.process_start_ticks,
            registered_identity: registered,
            checkpoint_owner_agent_id: spec.agent_id.clone(),
            publisher_epoch: epoch,
        };
        let mut nonce = [0; 16];
        File::open("/dev/urandom")?.read_exact(&mut nonce)?;
        let nonce = nonce
            .iter()
            .map(|value| format!("{value:02x}"))
            .collect::<String>();
        let sealed = crate::seal_host_authority_bootstrap(&bundle)?;
        launch.send(
            &crate::RootNotesLaunchFrame::OriginalBootstrapV1 {
                schema_version: 1,
                launch_nonce: nonce.clone(),
            },
            &[sealed.into(), pidfd(root.pid)?],
            deadline,
        )?;
        let copied_service = service.clone();
        let config = self.config.clone();
        let registration_copy = registration.clone();
        let server = std::thread::Builder::new()
            .name("native-original-root-lanes".into())
            .spawn(move || {
                crate::authority_host_runtime::listeners::serve_lanes(
                    &copied_service,
                    &config,
                    &registration_copy,
                    &owner,
                )
            })?;
        let (ready, descriptors) = launch.read(deadline)?;
        if !descriptors.is_empty()
            || !matches!(ready,crate::RootNotesLaunchFrame::RecoveredOwnerReadyV1 {schema_version:1,launch_nonce:ref actual} if actual==&nonce)
        {
            return Err(invalid(
                "native owner did not report exact zero-argument readiness",
            ));
        }
        service.confirm_recovered_owner_ready()?;
        launch.send(
            &crate::RootNotesLaunchFrame::RecoveredOwnerRegisteredV1 {
                schema_version: 1,
                launch_nonce: nonce,
            },
            &[],
            deadline,
        )?;
        let rpc = commands::Rpc::new(
            accept(&rpc_listener, deadline)?,
            &bundle.consumer,
            pidfd(bundle.consumer.pid)?,
            deadline,
        )?;
        let release = commands::Rpc::new(
            accept(&release_listener, deadline)?,
            &bundle.consumer,
            pidfd(bundle.consumer.pid)?,
            deadline,
        )?;
        self.config.writer = Some(writer);
        Ok(Active {
            service,
            registration,
            bundle,
            rpc,
            release,
            archive: self.archive.clone(),
            retained,
            server: Some(server),
            adopted,
            image,
            root_lease: self
                .leases
                .read_lease(&self.config.lease_id)
                .map_err(error)?
                .ok_or_else(|| invalid("actual canonical Root lease absent"))?
                .lease,
        })
    }
}

pub(super) fn run(boot: NativeBootstrap) -> io::Result<()> {
    let mounted = platform::mount_platform()?;
    let mut evidence = evidence::Evidence::load()?;
    let installation = match mounted {
        platform::StateMount::Fresh => Installation::fresh(&boot)?,
        platform::StateMount::Retained => Installation::cold_open(&boot, end()?)?,
    };
    let installation = Arc::new(Mutex::new(installation));
    let fleet = installation.lock().map_err(error)?.fleet.clone();
    let active = Arc::new(Mutex::new(None));
    let ready = active.clone();
    let owner_install = installation.clone();
    let command = AgentCommand::new("/test/hepta-g2-owner", Vec::new()).map_err(error)?;
    let deadline = if evidence.scenario() == "successor-renewal-v1" {
        now()?
            .checked_add(600_000_000_000)
            .ok_or_else(|| invalid("campaign deadline overflow"))?
    } else {
        end()?
    };
    let driver =
        KernelInitialProcessDriver::new(&boot.bytes, command.clone(), move |spec, role, owner| {
            let generation = owner_install
                .lock()
                .map_err(|e| codex_hepta_supervisor::ProcessDriverError::new(e.to_string()))?
                .activate(
                    spec,
                    role,
                    owner
                        .try_clone_to_owned()
                        .map_err(codex_hepta_supervisor::ProcessDriverError::from)?,
                    end().map_err(codex_hepta_supervisor::ProcessDriverError::from)?,
                )
                .map_err(|e| codex_hepta_supervisor::ProcessDriverError::new(e.to_string()))?;
            *ready
                .lock()
                .map_err(|e| codex_hepta_supervisor::ProcessDriverError::new(e.to_string()))? =
                Some(generation);
            Ok(())
        })
        .map_err(error)?;
    let next_install = installation.clone();
    let next_active = active.clone();
    let (launcher, observations) = {
        let retained = installation.lock().map_err(error)?;
        (
            retained.launcher.clone(),
            retained.launch_observations.clone(),
        )
    };
    let driver = driver
        .with_successors(
            &boot.bytes,
            launcher,
            observations,
            move |spec, image, owner| {
                let generation = next_install
                    .lock()
                    .map_err(|e| codex_hepta_supervisor::ProcessDriverError::new(e.to_string()))?
                    .activate_image(
                        spec,
                        OwnerImage::successor(image.clone()),
                        owner
                            .try_clone_to_owned()
                            .map_err(codex_hepta_supervisor::ProcessDriverError::from)?,
                        end().map_err(codex_hepta_supervisor::ProcessDriverError::from)?,
                    )
                    .map_err(codex_hepta_supervisor::ProcessDriverError::from)?;
                *next_active.lock().map_err(|e| {
                    codex_hepta_supervisor::ProcessDriverError::new(e.to_string())
                })? = Some(generation);
                Ok(())
            },
        )
        .map_err(error)?;
    let (mut supervisor, report) = Supervisor::recover(
        fleet,
        driver,
        SupervisorConfig::local_default(),
        Instant::now(),
    )
    .map_err(error)?;
    if !report.faults.is_empty() {
        return Err(invalid("original Supervisor recovery reported faults"));
    }
    let agent = AgentId::parse(AGENT).map_err(error)?;
    supervisor
        .start(&agent, command, Instant::now())
        .map_err(error)?;
    loop {
        remaining(deadline)?;
        let report = supervisor.tick(Instant::now());
        if !report.faults.is_empty() {
            return Err(invalid("original Supervisor reported a native owner fault"));
        }
        if supervisor
            .snapshot(&agent)
            .is_some_and(|snapshot| snapshot.healthy)
        {
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let mut generation = active
        .lock()
        .map_err(error)?
        .take()
        .ok_or_else(|| invalid("native activation omitted original service"))?;
    evidence.begin(&boot, &mut generation)?;
    match evidence.scenario() {
        "steady-state-v1" => evidence.steady_state(&mut generation)?,
        "manager-exit-after-terminal-v1" => {
            generation = recovery::after_terminal(
                &mut evidence,
                generation,
                &installation,
                &active,
                &mut supervisor,
                &agent,
                deadline,
            )?
        }
        "lost-copyout-live-v1" => lost_copyout::live(&mut evidence, &mut generation)?,
        "manager-exit-before-terminal-v1" => {
            generation = lost_copyout::before_terminal(
                &mut evidence,
                generation,
                &installation,
                &active,
                &mut supervisor,
                &agent,
                deadline,
            )?;
        }
        "successor-renewal-v1" => {
            generation = continuity::renewal(
                &mut evidence,
                generation,
                &installation,
                &active,
                &mut supervisor,
                &agent,
                deadline,
            )?;
        }
        "history-only-after-both-owner-exit-v1" => {
            generation = continuity::history_only(
                &mut evidence,
                generation,
                &installation,
                &active,
                &mut supervisor,
                &agent,
                deadline,
            )?;
        }
        _ => return Err(invalid("unsupported native acceptance scenario")),
    }
    let _final_release = continuity::stop_owner(
        &mut evidence,
        &mut generation,
        &mut supervisor,
        &agent,
        deadline,
        /*publish_evidence*/ false,
    )?;
    drop(supervisor); // The unused initial Recovery child is killed and reaped by its held guard.
    let workload = pidfd(3)?;
    let rc = unsafe {
        libc::syscall(
            libc::SYS_pidfd_send_signal,
            std::os::fd::AsRawFd::as_raw_fd(&workload),
            libc::SIGTERM,
            std::ptr::null::<libc::siginfo_t>(),
            0,
        )
    };
    if rc < 0 {
        return Err(io::Error::last_os_error());
    }
    let mut status = 0;
    if unsafe { libc::waitpid(3, &mut status, 0) } != 3 {
        return Err(io::Error::last_os_error());
    }
    if !libc::WIFSIGNALED(status) || libc::WTERMSIG(status) != libc::SIGTERM {
        return Err(invalid("actual workload shutdown status differs"));
    }
    File::open("/state")?.sync_all()?;
    // The transcript's last operation cut is retained unchanged. Completion
    // additionally requires real owner exit zero and successful workload reap.
    evidence.complete()?;
    unsafe {
        libc::sync();
        libc::reboot(libc::RB_POWER_OFF);
    }
    Err(invalid("native poweroff returned"))
}
