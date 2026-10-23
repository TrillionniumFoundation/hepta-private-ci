//! Actual Root factory/Registry/key and owned peer lifetimes for wrapper tests.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointStatus;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::RootCognitiveMaterialRegistration;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use codex_hepta_paths::HeptaAgentLayout;
use sha2::Digest;
use sha2::Sha256;
use std::os::fd::OwnedFd;
use std::process::Stdio;

pub(super) struct Peer {
    pub(super) child: std::process::Child,
    pub(super) pidfd: OwnedFd,
    pub(super) lifetime: CognitiveCheckpointPeerLifetime,
}
impl Peer {
    fn spawn(command: &mut Command) -> Self {
        let child = command.spawn().unwrap();
        // SAFETY: the PID belongs to our retained live Child; no borrowed pointers.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, child.id(), 0) };
        assert!(raw >= 0);
        // SAFETY: successful pidfd_open returns this fresh owned descriptor.
        let pidfd = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        let end = Instant::now() + Duration::from_secs(5);
        loop {
            let status = std::fs::read_to_string(format!("/proc/{}/status", child.id())).unwrap();
            if status.contains("Uid:\t60001\t60001\t60001\t60001") && status.contains("NoNewPrivs:\t1") {
                break;
            }
            assert!(Instant::now() < end);
            std::thread::sleep(Duration::from_millis(5));
        }
        let stat = std::fs::read_to_string(format!("/proc/{}/stat", child.id())).unwrap();
        let process_start_ticks = stat.rsplit_once(") ").unwrap().1.split_whitespace().nth(19).unwrap().parse().unwrap();
        let lifetime = CognitiveCheckpointPeerLifetime { uid: 60001, pid: child.id(),
            boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id").unwrap().trim().into(), process_start_ticks };
        Self { child, pidfd, lifetime }
    }
    pub(super) fn stop(&mut self) {
        self.child.kill().unwrap();
        self.child.wait().unwrap();
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn dedicated() -> Command {
    let mut command = Command::new("/usr/bin/setpriv");
    command.args(["--reuid=60001", "--regid=60001", "--clear-groups", "--no-new-privs",
        "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all"]);
    command
}

pub(super) struct Fixture {
    _root: tempfile::TempDir,
    _root_peer_pidfd: OwnedFd,
    _fleet: FleetRegistry,
    pub(super) runtime: tempfile::TempDir,
    pub(super) config: HostAuthorityServiceConfig,
    pub(super) registration: HostAuthorityRegistration,
    pub(super) clock: Arc<HostAuthorityClock>,
    pub(super) leases: AuthorityLeaseRegistry,
    pub(super) issuer: Arc<DeploymentFinalUseIssuer>,
    pub(super) previous: CognitiveCheckpointReceipt,
    pub(super) old_service: HostAuthorityService,
    pub(super) new_peer: Peer,
    pub(super) successor: crate::RetainedCheckpointPublisher,
    pub(super) retired: crate::RetiredCheckpointPublisher,
    pub(super) material: VerifiedCognitiveMaterial,
    image_layout: HeptaAgentLayout,
    pub(super) new_proof: crate::HostSignedWriterAuthorizationV1,
    pub(super) original_cut: CognitiveRecoveryAnchor,
    pub(super) dirty_cut: CognitiveRecoveryAnchor,
}

impl Fixture {
    pub(super) fn new() -> Self {
        // SAFETY: geteuid takes no borrowed pointers.
        assert_eq!(unsafe { libc::geteuid() }, 0);
        let parent = std::path::PathBuf::from(std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT").unwrap());
        let source = std::path::PathBuf::from(std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE").unwrap());
        let root = tempfile::Builder::new().prefix("root-wrapper-recovery-").tempdir_in(&parent).unwrap();
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let workspace = root.path().join("workspace"); std::fs::create_dir(&workspace).unwrap();
        let fleet = HeptaFleetRoot::parse(root.path().join("fleet")).unwrap();
        let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
        let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        registry.register(AgentManifest::new(owner.clone(), WorkspaceBinding::new(workspace.clone(), &fleet).unwrap(),
            ResourceBudget::local_default()).unwrap()).unwrap();
        let starting = registry.compare_and_transition(&owner, /*expected_generation*/ 0, AgentLifecycle::Starting).unwrap();
        assert_eq!(starting.generation, 1);
        let old_identity = HostAuthorityRegisteredIdentity { agent_id: owner.clone(), spawn_generation: starting.generation,
            fleet_root: fleet.as_path().to_path_buf(), workspace, resources: ResourceBudget::local_default() };
        let layout = old_identity.identity().unwrap().layout;
        let executor = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
        let original_cut = executor.block_on(async {
            let store = CognitiveStore::open(&layout).await.unwrap();
            let cut = store.recovery_anchor().await.unwrap(); store.close().await; cut
        });
        // The protected image is genuinely old, before any live source becomes
        // Dirty. Original full-cut/schema/integrity/fsync constructs the opaque value.
        for entry in std::fs::read_dir(layout.cognitive_root()).unwrap() {
            let file = entry.unwrap().path();
            if file.is_file() { std::os::unix::fs::chown(file, Some(60001), Some(60001)).unwrap(); }
        }
        std::os::unix::fs::chown(layout.cognitive_root(), Some(60001), Some(60001)).unwrap();
        let image_layout = HeptaFleetRoot::parse(root.path().join("retained-image")).unwrap().layout().agent(&owner);
        std::fs::create_dir_all(image_layout.cognitive_root()).unwrap();
        std::fs::set_permissions(image_layout.cognitive_root(), std::fs::Permissions::from_mode(0o700)).unwrap();
        RootCognitiveMaterialRegistration::bind_registered_layout(&layout, /*registered_uid*/ 60001).unwrap()
            .materialize_private_candidate(&image_layout).unwrap();
        let material = executor.block_on(CognitiveStore::verify_root_material_candidate(&image_layout, &original_cut)).unwrap();
        let runtime = tempfile::Builder::new().prefix("hepta-wrapper-recovery-").tempdir_in("/run").unwrap();
        std::os::unix::fs::chown(runtime.path(), Some(0), Some(60001)).unwrap();
        std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o2710)).unwrap();
        consumer_fixture::create_local(runtime.path());
        let state = root.path().join("authority");
        let mut old_command = dedicated(); old_command.args(["/usr/bin/sleep", "60"]).stdin(Stdio::null());
        let mut old_peer = Peer::spawn(&mut old_command);
        let old_held = crate::RetainedCheckpointPublisher::capture(old_peer.lifetime.clone()).unwrap();
        let mut new_command = dedicated();
        // A Root-owned single-link executable capsule can supply this same
        // libtest image when the build directory is not traversable by Host.
        // It is not the older thin qualification example with a different CLI.
        new_command.arg(std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_LIBTEST_BIN")
            .map(std::path::PathBuf::from).unwrap_or_else(|| std::env::current_exe().unwrap()))
            .args(["--exact", RECOVERY_CLIENT, "--ignored", "--nocapture"])
            .stdin(Stdio::piped()).env("HEPTA_SERVICE_STATE", &state).env("HEPTA_SERVICE_RUNTIME", runtime.path())
            .env("HEPTA_SERVICE_PID", std::process::id().to_string());
        let root_peer_pidfd = consumer_fixture::root_peer_fd(&mut new_command);
        let new_peer = Peer::spawn(&mut new_command);
        let metadata = std::fs::metadata(&parent).unwrap();
        let required_bind = HostAuthorityBindIdentity { mountpoint: parent, source_path: source,
            device: metadata.dev(), inode: metadata.ino() };
        let b = binding(owner.as_str());
        let bootstrap = root.path().join("bootstrap.json");
        write_json(&bootstrap, &serde_json::json!({"schema_version":1,"required_bind":required_bind,
            "signer_id":"root-wrapper-recovery", "policies":[DeploymentGrantPolicy { subject_id:owner.to_string(),
                destination_id:b.destination_id.clone(), scope_sha256:b.scope_sha256, lifetime_ms:30000 }],
            "lease_id":"root-wrapper-effect", "lease_binding":AuthorityLeaseBinding { principal_id:b.subject_id,
                operation_class:"runtime.agentd.production_operation".into(), destination_id:b.destination_id,
                scope_sha256:b.scope_sha256, payload_sha256:b.payload_sha256 }, "lease_lifetime_ms":60000}));
        let initialized = initialize_host_authority(&state, &bootstrap).unwrap();
        assert!(!initialized.production_ready);
        let mut config = HostAuthorityServiceConfig { schema_version:1, state_dir:state, required_bind,
            signer_id:initialized.signer_id, expected_verifying_key:initialized.verifying_key,
            lease_id:initialized.lease_id, lease_revision:1, writer:None, checkpoint_state_dir:None, consumers:None,
            sockets:HostAuthoritySocketPaths { observation:runtime.path().join("observation.sock"), issuer:runtime.path().join("issuer.sock"),
                checkpoint:runtime.path().join("checkpoint.sock"), device_frontier:None, notes_frontier:None },
            peer_uid:60001, peer_gid:60001, timeout_ms:10000, lifetime_ms:20000 };
        let (clock, leases, issuer) = open_registered_issuer(&config).unwrap();
        let now = clock.now_unix_ms().unwrap();
        let old_writer = crate::HostAuthorityWriterRegistration { registered_agent_id:owner.clone(),
            spawn_generation:starting.generation, owner_epoch:1, local_lease_id:"root-wrapper-local-writer".into(), local_lease_generation:1,
            authority_lease:AuthorityLease { schema_version:1, lease_id:"root-wrapper-writer-1".into(), revision:1, authority_epoch:1,
                binding:AuthorityLeaseBinding { principal_id:owner.to_string(), operation_class:"runtime.agentd.production_writer".into(),
                    destination_id:layout.cognitive_root().display().to_string(),
                    scope_sha256:Sha256::digest(serde_json::to_vec(&(owner.clone(), layout.cognitive_root())).unwrap()).into(),
                    payload_sha256:Sha256::digest(serde_json::to_vec(&original_cut).unwrap()).into() },
                issued_at_unix_ms:now, expires_at_unix_ms:now+60000 } };
        leases.put_lease(old_writer.authority_lease.clone(), /*expected_revision*/ 0).unwrap();
        let old_proof = issuer.register_writer_authorization(&old_writer, &leases.verifier()).unwrap();
        assert_eq!(old_proof.claims.sequence, 1);
        let old_service = HostAuthorityService::from_registered_owner(issuer.clone(), clock.clone(), old_identity.identity().unwrap()).unwrap()
            .with_registered_writer(old_writer.clone(), leases.verifier()).unwrap();
        let checkpoint_dir = config.state_dir.join("checkpoint");
        std::fs::DirBuilder::new().mode(0o700).create(&checkpoint_dir).unwrap();
        std::fs::File::open(&config.state_dir).unwrap().sync_all().unwrap();
        let original_registration = old_service.writer.as_ref().unwrap()
            .checkpoint_registration(&issuer, /*publisher_epoch*/ 1, old_peer.lifetime.clone()).unwrap();
        crate::HostCognitiveCheckpoint::initialize_fresh(RootAuthorityDirectory::open(&checkpoint_dir).unwrap(),
            original_registration, original_cut.clone(), clock.clone()).unwrap();
        let old_service = old_service.with_registered_checkpoint(RootAuthorityDirectory::open(&checkpoint_dir).unwrap(),
            /*publisher_epoch*/ 1, old_peer.lifetime.clone()).unwrap();
        let read = checkpoint_response(&old_service, /*sequence*/ 1, "read_head", serde_json::Value::Null);
        let dirty = checkpoint_response(&old_service, /*sequence*/ 2, "begin_writes", serde_json::to_value(read.token).unwrap());
        assert_eq!(dirty.status, CognitiveCheckpointStatus::Ack);
        let previous = CognitiveCheckpointReceipt { head:dirty.head.unwrap(), token:dirty.token.unwrap() };
        let dirty_cut = executor.block_on(async {
            let store = CognitiveStore::open(&layout).await.unwrap();
            store.append_source(&codex_hepta_memory::CognitiveAccess::agent_private(owner.clone()),
                &codex_hepta_memory::SourceDraft { scope:codex_hepta_memory::CognitiveScope::AgentPrivate,
                    kind:codex_hepta_memory::LedgerSourceKind::ExplicitMemoryDirective, event_key:"unpublished-after-dirty".into(),
                    content:b"controlled unpublished source after retained image".to_vec(), observed_at_unix_seconds:100 }).await.unwrap();
            let cut = store.recovery_anchor().await.unwrap(); store.close().await; cut
        });
        assert_ne!(dirty_cut, original_cut);
        config.writer = Some(old_writer.clone());
        consumer_fixture::initialize(&mut config);
        leases.revoke(&old_writer.authority_lease.lease_id, /*expected_revision*/ 1, Sha256::digest(b"actual old publisher retired").into()).unwrap();
        old_peer.stop();
        drop(old_held);
        let retired = crate::RetiredCheckpointPublisher::observe(old_peer.lifetime.clone()).unwrap();
        registry.compare_and_transition(&owner, starting.generation, AgentLifecycle::Failed).unwrap();
        let next = registry.compare_and_transition(&owner, /*expected_generation*/ 2, AgentLifecycle::Starting).unwrap();
        assert_eq!(next.generation, 3);
        let new_identity = HostAuthorityRegisteredIdentity { spawn_generation:next.generation, ..old_identity };
        let mut new_writer = old_writer.clone();
        new_writer.spawn_generation = new_identity.spawn_generation; new_writer.owner_epoch += 1;
        new_writer.local_lease_generation += 1; new_writer.authority_lease.lease_id = "root-wrapper-writer-2".into();
        new_writer.authority_lease.issued_at_unix_ms = clock.now_unix_ms().unwrap();
        new_writer.authority_lease.binding.payload_sha256 = Sha256::digest(serde_json::to_vec(&(
            &original_cut, new_writer.spawn_generation, new_writer.local_lease_generation)).unwrap()).into();
        leases.put_lease(new_writer.authority_lease.clone(), /*expected_revision*/ 0).unwrap();
        let before_head = issuer.revocations().unwrap(); let before_key = issuer.trust_key().unwrap();
        let new_proof = issuer.rotate_writer_authorization(&old_writer, &old_proof, &new_writer).unwrap();
        assert_eq!(new_proof.claims.sequence, 2);
        assert_eq!(issuer.revocations().unwrap(), before_head);
        assert_eq!(issuer.trust_key().unwrap().verifying_key, before_key.verifying_key);
        assert_eq!(issuer.rotate_writer_authorization(&old_writer, &old_proof, &new_writer).unwrap(), new_proof);
        let registration = HostAuthorityRegistration { schema_version:1, peer_pid:new_peer.child.id(),
            boot_id:new_peer.lifetime.boot_id.clone(), process_start_ticks:new_peer.lifetime.process_start_ticks,
            registered_identity:new_identity, checkpoint_owner_agent_id:owner, publisher_epoch:2 };
        let successor = crate::RetainedCheckpointPublisher::capture(new_peer.lifetime.clone()).unwrap();
        config.writer = Some(new_writer); config.checkpoint_state_dir = Some(checkpoint_dir);
        Self { _root:root, _root_peer_pidfd:root_peer_pidfd, _fleet:registry, runtime, config, registration,
            clock, leases, issuer, previous, old_service, new_peer, successor, retired, material, image_layout, new_proof,
            original_cut, dirty_cut }
    }

    pub(super) fn service(&self) -> HostAuthorityService {
        HostAuthorityService::from_registered_owner(self.issuer.clone(), self.clock.clone(),
            self.registration.registered_identity.identity().unwrap()).unwrap()
            .with_registered_writer(self.config.writer.as_ref().unwrap().clone(), self.leases.verifier()).unwrap()
    }

    pub(super) fn another_material(&self) -> VerifiedCognitiveMaterial {
        tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap()
            .block_on(CognitiveStore::verify_retained_root_material(&self.image_layout, &self.original_cut)).unwrap()
    }
}

fn checkpoint_response(service: &HostAuthorityService, sequence: u64, command: &str,
    expected: serde_json::Value) -> CognitiveCheckpointResponse {
    let request = serde_json::json!({"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1",
        "request_id":format!("0000000000000001{sequence:016x}"),"command":command,"expected":expected,"proposal":null});
    serde_json::from_slice(&service.handle(HostAuthorityLane::Checkpoint, &serde_json::to_vec(&request).unwrap()).unwrap()).unwrap()
}
