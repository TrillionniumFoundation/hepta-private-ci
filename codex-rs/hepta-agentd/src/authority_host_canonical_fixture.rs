//! Fresh canonical Root registration and actual two-generation owned children.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use std::os::fd::OwnedFd;
use std::process::Stdio;

pub(super) struct Generation {
    pub(super) peer: fixture::Peer,
    pub(super) successor: crate::RetainedCheckpointPublisher,
    pub(super) registration: HostAuthorityRegistration,
    pub(super) service: HostAuthorityService,
    _root_peer: OwnedFd,
}

pub(super) struct Fixture {
    _root: tempfile::TempDir,
    _owner: tempfile::TempDir,
    fleet: FleetRegistry,
    pub(super) runtime: tempfile::TempDir,
    pub(super) config: HostAuthorityServiceConfig,
    pub(super) clock: Arc<HostAuthorityClock>,
    pub(super) leases: AuthorityLeaseRegistry,
    pub(super) issuer: Arc<DeploymentFinalUseIssuer>,
    pub(super) first_writer: crate::HostAuthorityWriterRegistration,
    pub(super) first_proof: crate::HostSignedWriterAuthorizationV1,
    pub(super) initial: CognitiveRecoveryAnchor,
    identity: HostAuthorityRegisteredIdentity,
    pub(super) archive: std::path::PathBuf,
}

impl Fixture {
    pub(super) fn new() -> Self {
        // SAFETY: geteuid only reads the actual caller.
        assert_eq!(unsafe { libc::geteuid() }, 0);
        let parent = std::path::PathBuf::from(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT").unwrap(),
        );
        let source = std::path::PathBuf::from(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE").unwrap(),
        );
        let root = tempfile::Builder::new()
            .prefix("root-canonical-lifecycle-")
            .tempdir_in(&parent)
            .unwrap();
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let owner_parent = std::env::var_os("HEPTA_TEST_ROOT_OWNER_INSTALL_DESTINATION")
            .expect("independent Root0/0711 durable owner-traversable namespace");
        let owner_root = tempfile::Builder::new()
            .prefix("root-canonical-owner-")
            .tempdir_in(owner_parent)
            .unwrap();
        std::fs::set_permissions(owner_root.path(), std::fs::Permissions::from_mode(0o711))
            .unwrap();
        let workspace = owner_root.path().join("workspace");
        std::fs::create_dir(&workspace).unwrap();
        let fleet_root = HeptaFleetRoot::parse(owner_root.path().join("fleet")).unwrap();
        let fleet = FleetRegistry::initialize(fleet_root.clone()).unwrap();
        let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").unwrap();
        fleet
            .register(
                AgentManifest::new(
                    owner.clone(),
                    WorkspaceBinding::new(workspace.clone(), &fleet_root).unwrap(),
                    ResourceBudget::local_default(),
                )
                .unwrap(),
            )
            .unwrap();
        let spawn = fleet
            .compare_and_transition(
                &owner,
                /*expected_generation*/ 0,
                AgentLifecycle::Starting,
            )
            .unwrap();
        let identity = HostAuthorityRegisteredIdentity {
            agent_id: owner.clone(),
            spawn_generation: spawn.generation,
            fleet_root: fleet_root.as_path().to_path_buf(),
            workspace,
            resources: ResourceBudget::local_default(),
        };
        let layout = crate::authority_host_config::registered_identity(&identity)
            .unwrap()
            .layout;
        let initial = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(async {
                let store = CognitiveStore::open(&layout).await.unwrap();
                let cut = store.recovery_anchor().await.unwrap();
                store.close().await;
                cut
            });
        for path in layout
            .cognitive_root()
            .ancestors()
            .take_while(|path| path.starts_with(owner_root.path()))
        {
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o711)).unwrap();
        }
        for path in [
            layout.cognitive_root(),
            layout.home_root(),
            layout.run_root(),
        ] {
            std::fs::create_dir_all(path).unwrap();
            std::os::unix::fs::chown(path, Some(60001), Some(60001)).unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        for entry in std::fs::read_dir(layout.cognitive_root()).unwrap() {
            let path = entry.unwrap().path();
            if path.is_file() {
                std::os::unix::fs::chown(&path, Some(60001), Some(60001)).unwrap();
                std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).unwrap();
            }
        }
        // The owner lives under a distinct durable searchable namespace.
        // Protected authority and images retain their Root0700 ancestor chain.
        let runtime = tempfile::Builder::new()
            .prefix("hepta-canonical-lifecycle-")
            .tempdir_in("/run")
            .unwrap();
        std::os::unix::fs::chown(runtime.path(), Some(0), Some(60001)).unwrap();
        std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o2710)).unwrap();
        consumer_fixture::create_local(runtime.path());
        let state = root.path().join("authority");
        let metadata = std::fs::metadata(&parent).unwrap();
        let required_bind = HostAuthorityBindIdentity {
            mountpoint: parent,
            source_path: source,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        let b = binding(owner.as_str());
        let bootstrap = root.path().join("bootstrap.json");
        write_json(
            &bootstrap,
            &serde_json::json!({"schema_version":1,"required_bind":required_bind,
            "signer_id":"root-canonical-lifecycle","policies":[DeploymentGrantPolicy { subject_id:owner.to_string(),
                destination_id:b.destination_id.clone(), scope_sha256:b.scope_sha256, lifetime_ms:30000 }],
            "lease_id":"root-canonical-unused-effect", "lease_binding":AuthorityLeaseBinding { principal_id:b.subject_id,
                operation_class:"runtime.agentd.production_operation".into(), destination_id:b.destination_id,
                scope_sha256:b.scope_sha256, payload_sha256:b.payload_sha256 }, "lease_lifetime_ms":60000}),
        );
        let initialized = initialize_host_authority(&state, &bootstrap).unwrap();
        let mut config = HostAuthorityServiceConfig {
            schema_version: 1,
            state_dir: state,
            required_bind,
            signer_id: initialized.signer_id,
            expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id,
            lease_revision: 1,
            writer: None,
            checkpoint_state_dir: None,
            consumers: None,
            sockets: HostAuthoritySocketPaths {
                observation: runtime.path().join("observation.sock"),
                issuer: runtime.path().join("issuer.sock"),
                checkpoint: runtime.path().join("checkpoint.sock"),
                device_frontier: None,
                notes_frontier: None,
            },
            peer_uid: 60001,
            peer_gid: 60001,
            timeout_ms: 10000,
            lifetime_ms: 20000,
        };
        let (clock, leases, issuer) = open_registered_issuer(&config).unwrap();
        let now = clock.now_unix_ms().unwrap();
        let first_writer = crate::HostAuthorityWriterRegistration {
            registered_agent_id: owner.clone(),
            spawn_generation: 1,
            owner_epoch: 1,
            local_lease_id: "root-canonical-local-writer".into(),
            local_lease_generation: 1,
            authority_lease: AuthorityLease {
                schema_version: 1,
                lease_id: "root-canonical-writer-1".into(),
                revision: 1,
                authority_epoch: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: owner.to_string(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: format!("cognitive.owner:{owner}"),
                    scope_sha256: Sha256::digest(
                        serde_json::to_vec(&(owner.clone(), layout.cognitive_root())).unwrap(),
                    )
                    .into(),
                    payload_sha256: Sha256::digest(serde_json::to_vec(&initial).unwrap()).into(),
                },
                issued_at_unix_ms: now,
                expires_at_unix_ms: now + 60000,
            },
        };
        first_writer.authority_lease.validate().unwrap();
        leases
            .put_lease(
                first_writer.authority_lease.clone(),
                /*expected_revision*/ 0,
            )
            .unwrap();
        let first_proof = issuer
            .register_writer_authorization(&first_writer, &leases.verifier())
            .unwrap();
        assert_eq!(first_proof.claims.sequence, 1);
        config.writer = Some(first_writer.clone());
        consumer_fixture::initialize(&mut config);
        let checkpoint = config.state_dir.join("checkpoint");
        let archive = config.state_dir.join("material");
        for path in [&checkpoint, &archive] {
            std::fs::DirBuilder::new().mode(0o700).create(path).unwrap();
        }
        std::fs::File::open(&config.state_dir)
            .unwrap()
            .sync_all()
            .unwrap();
        config.checkpoint_state_dir = Some(checkpoint);
        Self {
            _root: root,
            _owner: owner_root,
            fleet,
            runtime,
            config,
            clock,
            leases,
            issuer,
            first_writer,
            first_proof,
            initial,
            identity,
            archive,
        }
    }

    fn child(&self, identity: &HostAuthorityRegisteredIdentity) -> (fixture::Peer, OwnedFd) {
        let mut command = fixture::dedicated();
        command
            .arg(
                std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_LIBTEST_BIN")
                    .map(std::path::PathBuf::from)
                    .unwrap_or_else(|| std::env::current_exe().unwrap()),
            )
            .args(["--exact", CANONICAL_CLIENT, "--ignored", "--nocapture"])
            .stdin(Stdio::piped())
            .current_dir(
                crate::authority_host_config::registered_identity(&identity)
                    .unwrap()
                    .layout
                    .home_root(),
            )
            .env("HEPTA_SERVICE_STATE", &self.config.state_dir)
            .env("HEPTA_SERVICE_RUNTIME", self.runtime.path())
            .env("HEPTA_SERVICE_PID", std::process::id().to_string())
            .env(
                "TMPDIR",
                crate::authority_host_config::registered_identity(&identity)
                    .unwrap()
                    .layout
                    .home_root(),
            );
        let root_peer = consumer_fixture::root_peer_fd(&mut command);
        (fixture::Peer::spawn(&mut command), root_peer)
    }

    fn assemble(
        &self,
        service: HostAuthorityService,
        peer: &fixture::Peer,
    ) -> HostAuthorityService {
        let paths = &self.config.sockets;
        service
            .with_registered_consumers(
                &self.config.state_dir,
                self.config.consumers.as_ref().unwrap(),
            )
            .unwrap()
            .with_required_material_startup(&self.archive)
            .unwrap()
            .with_bootstrap_registration(
                crate::HostAuthorityBootstrapLocations {
                    sockets: crate::HostAuthorityFiveLanePathsV1 {
                        observation: paths.observation.clone(),
                        issuer: paths.issuer.clone(),
                        checkpoint: paths.checkpoint.clone(),
                        device_frontier: paths.device_frontier.clone().unwrap(),
                        notes_frontier: paths.notes_frontier.clone().unwrap(),
                    },
                    device_local_state_dir: self.runtime.path().join("consumer-local/device"),
                    notes_local_state_dir: self.runtime.path().join("consumer-local/notes"),
                    lifetime: Duration::from_millis(self.config.lifetime_ms),
                },
                peer.pidfd.try_clone().unwrap(),
            )
            .unwrap()
    }

    pub(super) fn first(&self) -> Generation {
        let (peer, root_peer) = self.child(&self.identity);
        let successor = crate::RetainedCheckpointPublisher::capture(peer.lifetime.clone()).unwrap();
        let service = HostAuthorityService::from_registered_owner(
            self.issuer.clone(),
            self.clock.clone(),
            crate::authority_host_config::registered_identity(&self.identity).unwrap(),
        )
        .unwrap()
        .with_registered_writer(self.first_writer.clone(), self.leases.verifier())
        .unwrap();
        let registration = service
            .writer
            .as_ref()
            .unwrap()
            .checkpoint_registration(
                &self.issuer,
                /*publisher_epoch*/ 1,
                peer.lifetime.clone(),
            )
            .unwrap();
        crate::HostCognitiveCheckpoint::initialize_fresh(
            RootAuthorityDirectory::open(self.config.checkpoint_state_dir.as_ref().unwrap())
                .unwrap(),
            registration,
            self.initial.clone(),
            self.clock.clone(),
        )
        .unwrap();
        let service = service
            .with_registered_checkpoint(
                RootAuthorityDirectory::open(self.config.checkpoint_state_dir.as_ref().unwrap())
                    .unwrap(),
                /*publisher_epoch*/ 1,
                peer.lifetime.clone(),
            )
            .unwrap();
        let registration = HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: peer.child.id(),
            boot_id: peer.lifetime.boot_id.clone(),
            process_start_ticks: peer.lifetime.process_start_ticks,
            registered_identity: self.identity.clone(),
            checkpoint_owner_agent_id: self.identity.agent_id.clone(),
            publisher_epoch: 1,
        };
        Generation {
            service: self.assemble(service, &peer),
            peer,
            successor,
            registration,
            _root_peer: root_peer,
        }
    }

    pub(super) fn retained(&self, cut: &CognitiveRecoveryAnchor) -> VerifiedCognitiveMaterial {
        let digest =
            codex_hepta_contracts::Sha256Digest::for_bytes(&serde_json::to_vec(cut).unwrap());
        let layout = HeptaFleetRoot::parse(self.archive.join(digest.as_str()))
            .unwrap()
            .layout()
            .agent(&cut.owner_agent_id);
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(CognitiveStore::verify_retained_root_material(&layout, cut))
            .unwrap()
    }

    pub(super) fn next(
        &mut self,
        previous: &CognitiveCheckpointReceipt,
        retired: &crate::RetiredCheckpointPublisher,
        material: &VerifiedCognitiveMaterial,
    ) -> Generation {
        self.leases
            .revoke(
                &self.first_writer.authority_lease.lease_id,
                /*expected_revision*/ 1,
                Sha256::digest(b"actual retired canonical first owner").into(),
            )
            .unwrap();
        self.fleet
            .compare_and_transition(
                &self.identity.agent_id,
                /*expected_generation*/ 1,
                AgentLifecycle::Failed,
            )
            .unwrap();
        let spawn = self
            .fleet
            .compare_and_transition(
                &self.identity.agent_id,
                /*expected_generation*/ 2,
                AgentLifecycle::Starting,
            )
            .unwrap();
        assert_eq!(spawn.generation, 3);
        let identity = HostAuthorityRegisteredIdentity {
            spawn_generation: spawn.generation,
            ..self.identity.clone()
        };
        let mut writer = self.first_writer.clone();
        writer.spawn_generation = spawn.generation;
        writer.owner_epoch += 1;
        writer.local_lease_generation += 1;
        writer.authority_lease.lease_id = "root-canonical-writer-2".into();
        writer.authority_lease.issued_at_unix_ms = self.clock.now_unix_ms().unwrap();
        writer.authority_lease.binding.payload_sha256 = Sha256::digest(
            serde_json::to_vec(&(
                &previous.head.last_current,
                writer.spawn_generation,
                writer.local_lease_generation,
            ))
            .unwrap(),
        )
        .into();
        self.leases
            .put_lease(writer.authority_lease.clone(), /*expected_revision*/ 0)
            .unwrap();
        let proof = self
            .issuer
            .rotate_writer_authorization(&self.first_writer, &self.first_proof, &writer)
            .unwrap();
        assert_eq!(proof.claims.sequence, 2);
        self.config.writer = Some(writer.clone());
        let (peer, root_peer) = self.child(&identity);
        let successor = crate::RetainedCheckpointPublisher::capture(peer.lifetime.clone()).unwrap();
        let service = HostAuthorityService::from_registered_owner(
            self.issuer.clone(),
            self.clock.clone(),
            crate::authority_host_config::registered_identity(&identity).unwrap(),
        )
        .unwrap()
        .with_registered_writer(writer, self.leases.verifier())
        .unwrap()
        .with_recovered_checkpoint(
            RootAuthorityDirectory::open(self.config.checkpoint_state_dir.as_ref().unwrap())
                .unwrap(),
            previous,
            retired,
            &successor,
            /*publisher_epoch*/ 2,
            material,
        )
        .unwrap();
        let registration = HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: peer.child.id(),
            boot_id: peer.lifetime.boot_id.clone(),
            process_start_ticks: peer.lifetime.process_start_ticks,
            registered_identity: identity,
            checkpoint_owner_agent_id: self.identity.agent_id.clone(),
            publisher_epoch: 2,
        };
        Generation {
            service: self.assemble(service, &peer),
            peer,
            successor,
            registration,
            _root_peer: root_peer,
        }
    }
}
