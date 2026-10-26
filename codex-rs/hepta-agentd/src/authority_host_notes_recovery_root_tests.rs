//! Real original issuer/Registry/clock/Current component fixture. Dedicated
//! controlled children stand in for publishers; no production Session, Agentd turn,
//! deployment profile, persistent signer input or physical device is qualified.
use super::*;
use crate::DeploymentFinalUseIssuer;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityService;
use crate::HostConsumerFrontier;
use crate::HostNotesRecoveryPredecessor;
use crate::authority_host_config::*;
use crate::authority_host_service::RetainedNotesRecovery;
use crate::root_writer_proof::VerifiedRootWriterProof;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_memory::NotesTargetIdentity;
use pretty_assertions::assert_eq;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

#[path = "root_notes_recovery_session_tests.rs"]
mod staged_session;

enum FixtureLayout {
    Component,
    OriginalHostBind(HostAuthorityBindIdentity),
}

enum FixturePredecessor {
    Retired,
    Retained {
        publisher: Publisher,
        target: NotesTargetIdentity,
    },
}

struct OriginalFixture {
    _root: tempfile::TempDir,
    _old: Publisher,
    _new: Publisher,
    config: HostAuthorityServiceConfig,
    registration: HostAuthorityRegistration,
    clock: Arc<HostAuthorityClock>,
    registry: Arc<AuthorityLeaseRegistry>,
    issuer: Arc<DeploymentFinalUseIssuer>,
    old_writer: crate::HostAuthorityWriterRegistration,
    old_proof: crate::HostSignedWriterAuthorizationV1,
    previous: CognitiveCheckpointReceipt,
    old_target: NotesTargetIdentity,
    new_target: NotesTargetIdentity,
    lease_owner: &'static str,
}

fn private(path: &Path) {
    std::fs::create_dir(path).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
}

impl OriginalFixture {
    async fn new() -> Self {
        Self::with_layout(FixtureLayout::Component).await
    }

    async fn with_layout(fixture_layout: FixtureLayout) -> Self {
        Self::with_predecessor(fixture_layout, FixturePredecessor::Retired).await
    }

    async fn with_predecessor(
        fixture_layout: FixtureLayout,
        predecessor: FixturePredecessor,
    ) -> Self {
        let (parent, clock_owner, lease_owner) = match &fixture_layout {
            FixtureLayout::Component => (
                std::path::PathBuf::from(
                    std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
                        .expect("explicit root-owned data-bind qualification root required"),
                ),
                "fixture-clock",
                "fixture-leases",
            ),
            FixtureLayout::OriginalHostBind(bind) => {
                bind.verify().unwrap();
                (
                    bind.mountpoint.clone(),
                    "root-authority-clock-v1",
                    "root-authority-leases-v1",
                )
            }
        };
        let root = tempfile::tempdir_in(parent).unwrap();
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let state = root.path().join("state");
        private(&state);
        let directory = RootAuthorityDirectory::open(&state).unwrap();
        let clock = Arc::new(
            HostAuthorityClock::initialize(directory.clone(), clock_owner.into()).unwrap(),
        );
        let frontier = Arc::new(
            HostAuthorityFrontierStore::initialize(
                directory,
                lease_owner.into(),
                AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            )
            .unwrap(),
        );
        let lease_path = state.join("leases");
        private(&lease_path);
        let registry = Arc::new(
            AuthorityLeaseRegistry::open_state_dir_with_trust(
                &lease_path,
                lease_owner.into(),
                clock.clone(),
                frontier,
            )
            .unwrap(),
        );
        let agent = AgentId::parse("00000000-0000-4000-8000-00000000c072").unwrap();
        let old_target = match &predecessor {
            FixturePredecessor::Retired => NotesTargetIdentity {
                session_instance: "1".repeat(32),
                task_id: 7,
                incarnation: "2".repeat(32),
            },
            FixturePredecessor::Retained { target, .. } => target.clone(),
        };
        let new_target = NotesTargetIdentity {
            incarnation: "3".repeat(32),
            ..old_target.clone()
        };
        let now = clock.now_unix_ms().unwrap();
        let old_writer = crate::HostAuthorityWriterRegistration {
            registered_agent_id: agent.clone(),
            spawn_generation: 1,
            owner_epoch: 1,
            local_lease_id: "notes-original-local".into(),
            local_lease_generation: 1,
            authority_lease: AuthorityLease {
                schema_version: 1,
                lease_id: "notes-original-old".into(),
                authority_epoch: 1,
                revision: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: agent.as_str().into(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: "fixture-cognitive-owner".into(),
                    scope_sha256: [4; 32],
                    payload_sha256: [5; 32],
                },
                issued_at_unix_ms: now,
                expires_at_unix_ms: now + 10_000,
            },
        };
        let mut writer = old_writer.clone();
        writer.spawn_generation += 1;
        writer.owner_epoch += 1;
        writer.local_lease_generation += 1;
        writer.authority_lease.lease_id = "notes-original-new".into();
        writer.authority_lease.expires_at_unix_ms = now + 120_000;
        registry
            .put_lease(old_writer.authority_lease.clone(), 0)
            .unwrap();
        registry
            .put_lease(writer.authority_lease.clone(), 0)
            .unwrap();
        let binding = FinalUseBinding {
            subject_id: agent.as_str().into(),
            destination_id: old_target.destination_id(),
            scope_sha256: old_target.scope_digest().into_array(),
            payload_sha256: [6; 32],
            request_sha256: [7; 32],
        };
        registry
            .put_lease(
                AuthorityLease {
                    lease_id: "notes-original-issuer".into(),
                    binding: AuthorityLeaseBinding {
                        principal_id: binding.subject_id.clone(),
                        operation_class: "runtime.agentd.production_operation".into(),
                        destination_id: binding.destination_id.clone(),
                        scope_sha256: binding.scope_sha256,
                        payload_sha256: binding.payload_sha256,
                    },
                    ..writer.authority_lease.clone()
                },
                0,
            )
            .unwrap();
        let issuer = Arc::new(
            DeploymentFinalUseIssuer::create_protected(
                &state.join("issuer"),
                "notes-original-fixture".into(),
                vec![DeploymentGrantPolicy {
                    subject_id: agent.as_str().into(),
                    destination_id: binding.destination_id.clone(),
                    scope_sha256: binding.scope_sha256,
                    lifetime_ms: 1_000,
                }],
                clock.clone(),
                registry.verifier(),
                "notes-original-issuer".into(),
                1,
            )
            .unwrap(),
        );
        let old_proof = issuer
            .register_writer_authorization(&old_writer, &registry.verifier())
            .unwrap();
        issuer.issue(&binding).unwrap().unwrap();
        let key = issuer.trust_key().unwrap();
        let verified = VerifiedRootWriterProof::verify(
            old_proof.clone(),
            &crate::AgentdRootWriterTrust {
                issuer_id: key.key_id.clone(),
                verifying_key: key.verifying_key,
                agent_id: agent.clone(),
                spawn_generation: 1,
                owner_epoch: 1,
                local_lease_id: old_writer.local_lease_id.clone(),
                local_lease_generation: 1,
                authority_lease: old_writer.authority_lease.clone(),
            },
        )
        .unwrap();
        let authority = verified.authority();
        let retire = matches!(&predecessor, FixturePredecessor::Retired);
        let mut old = match predecessor {
            FixturePredecessor::Retired => Publisher::spawn(),
            FixturePredecessor::Retained { publisher, .. } => publisher,
        };
        let new = Publisher::spawn();
        let fleet = root.path().join("fleet");
        let workspace = root.path().join("workspace");
        private(&fleet);
        private(&workspace);
        let layout = HeptaFleetRoot::parse(fleet.clone())
            .unwrap()
            .layout()
            .agent(&agent);
        let store = CognitiveStore::open(&layout).await.unwrap();
        let cut = store.recovery_anchor().await.unwrap();
        store.close().await;
        let checkpoint_path = state.join("checkpoint");
        private(&checkpoint_path);
        let checkpoint = HostCognitiveCheckpoint::initialize_fresh(
            RootAuthorityDirectory::open(&checkpoint_path).unwrap(),
            HostCognitiveCheckpointRegistration {
                owner_agent_id: agent.clone(),
                publisher_epoch: 1,
                writer_binding: CognitiveCheckpointWriterBinding {
                    lease_id: old_writer.local_lease_id.clone(),
                    generation: 1,
                    authority_epoch: authority.authority_epoch,
                    owner_epoch: authority.owner_epoch,
                    authority_grant_digest: authority.grant_digest.clone(),
                    fencing_token_digest: authority.fencing_token_digest().unwrap(),
                    expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
                },
                peer_lifetime: old.retained.lifetime.clone(),
            },
            cut,
            clock.clone(),
        )
        .unwrap();
        let head = checkpoint.load().unwrap();
        let previous = CognitiveCheckpointReceipt {
            token: token_for(&head).unwrap(),
            head,
        };
        let consumer = |name: &str| {
            let path = state.join(name);
            private(&path);
            HostConsumerFrontier::initialize_fresh(
                RootAuthorityDirectory::open(&path).unwrap(),
                key.key_id.clone(),
                &issuer.revocations().unwrap(),
                clock.clone(),
                writer.authority_lease.expires_at_unix_ms,
            )
            .unwrap();
            HostAuthorityConsumerConfig {
                state_dir: path,
                owner_id: key.key_id.clone(),
            }
        };
        let consumers = HostAuthorityConsumersConfig {
            device: consumer("device"),
            notes: consumer("notes"),
        };
        let runtime = root.path().join("runtime");
        private(&runtime);
        let runtime_file = std::fs::File::open(&runtime).unwrap();
        // SAFETY: the descriptor pins this test's newly created private directory.
        assert_eq!(
            unsafe { libc::fchown(runtime_file.as_raw_fd(), 0, 60001) },
            0
        );
        std::fs::set_permissions(&runtime, std::fs::Permissions::from_mode(0o2710)).unwrap();
        let metadata = std::fs::metadata(root.path()).unwrap();
        let config = HostAuthorityServiceConfig {
            schema_version: 1,
            state_dir: state,
            required_bind: match fixture_layout {
                // This original component profile does not invoke the mount loader.
                FixtureLayout::Component => HostAuthorityBindIdentity {
                    mountpoint: root.path().into(),
                    source_path: root.path().into(),
                    device: metadata.dev(),
                    inode: metadata.ino(),
                },
                FixtureLayout::OriginalHostBind(bind) => bind,
            },
            signer_id: key.key_id,
            expected_verifying_key: key.verifying_key,
            lease_id: "notes-original-issuer".into(),
            lease_revision: 1,
            writer: Some(writer),
            checkpoint_state_dir: Some(checkpoint_path),
            consumers: Some(consumers),
            sockets: HostAuthoritySocketPaths {
                observation: runtime.join("observe.sock"),
                issuer: runtime.join("issuer.sock"),
                checkpoint: runtime.join("checkpoint.sock"),
                device_frontier: Some(runtime.join("device.sock")),
                notes_frontier: Some(runtime.join("notes.sock")),
            },
            peer_uid: 60001,
            peer_gid: 60001,
            timeout_ms: 1_000,
            lifetime_ms: 30_000,
            issuer_record_profile: HostIssuerRecordProfile::Standard,
        };
        let registration = HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: new.retained.lifetime.pid,
            boot_id: new.retained.lifetime.boot_id.clone(),
            process_start_ticks: new.retained.lifetime.process_start_ticks,
            registered_identity: HostAuthorityRegisteredIdentity {
                agent_id: agent.clone(),
                spawn_generation: 2,
                fleet_root: fleet,
                workspace,
                resources: ResourceBudget::local_default(),
            },
            checkpoint_owner_agent_id: agent,
            publisher_epoch: 2,
        };
        if retire {
            old.stop();
            let deadline = Instant::now() + Duration::from_secs(15);
            while clock.now_unix_ms().unwrap() < old_writer.authority_lease.expires_at_unix_ms {
                assert!(
                    Instant::now() < deadline,
                    "original local and registry leases did not expire"
                );
                std::thread::sleep(Duration::from_millis(10));
            }
        }
        Self {
            _root: root,
            _old: old,
            _new: new,
            config,
            registration,
            clock,
            registry,
            issuer,
            old_writer,
            old_proof,
            previous,
            old_target,
            new_target,
            lease_owner,
        }
    }

    fn recover(&self, target: NotesTargetIdentity, lifetime_ms: u64) -> RetainedNotesRecovery {
        let service = HostAuthorityService::from_registered_owner(
            self.issuer.clone(),
            self.clock.clone(),
            self.registration.registered_identity.identity().unwrap(),
        )
        .unwrap()
        .retain_original_root_registry(self.registry.clone());
        RetainedNotesRecovery::capture(
            service,
            &self.config,
            &self.registration,
            HostNotesRecoveryPredecessor {
                writer: self.old_writer.clone(),
                writer_proof: self.old_proof.clone(),
                checkpoint: self.previous.clone(),
                notes_target: target,
                notes_lifetime_ms: lifetime_ms,
            },
        )
        .unwrap()
    }

    fn snapshot(
        &self,
    ) -> (
        serde_json::Value,
        CognitiveCheckpointHead,
        AuthorityLeaseFrontier,
        Vec<FinalUseFrontier>,
    ) {
        snapshot_original(&self.config, self.lease_owner)
    }
}

fn snapshot_original(
    config: &HostAuthorityServiceConfig,
    lease_owner: &str,
) -> (
    serde_json::Value,
    CognitiveCheckpointHead,
    AuthorityLeaseFrontier,
    Vec<FinalUseFrontier>,
) {
    let issuer = HostAuthorityFrontierStore::<serde_json::Value>::open(
        RootAuthorityDirectory::open(&config.state_dir.join("issuer")).unwrap(),
        "local-final-use-issuer".into(),
    )
    .unwrap()
    .load("local-final-use-issuer")
    .unwrap();
    let checkpoint = HostAuthorityFrontierStore::open(
        RootAuthorityDirectory::open(config.checkpoint_state_dir.as_ref().unwrap()).unwrap(),
        STORE_OWNER.into(),
    )
    .unwrap()
    .load(STORE_OWNER)
    .unwrap();
    let consumers = config.consumers.as_ref().unwrap();
    let frontiers = [&consumers.device, &consumers.notes]
        .into_iter()
        .map(|slot| {
            HostAuthorityFrontierStore::open(
                RootAuthorityDirectory::open(&slot.state_dir).unwrap(),
                slot.owner_id.clone(),
            )
            .unwrap()
            .load(&slot.owner_id)
            .unwrap()
        })
        .collect();
    (
        issuer,
        checkpoint,
        HostAuthorityFrontierStore::open(
            RootAuthorityDirectory::open(&config.state_dir).unwrap(),
            lease_owner.into(),
        )
        .unwrap()
        .load(lease_owner)
        .unwrap(),
        frontiers,
    )
}
#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_notes_recovery_original_policy_refusals_preserve_writer_current_and_frontiers() {
    let f = OriginalFixture::new().await;
    let before = f.snapshot();
    let wrong = NotesTargetIdentity {
        incarnation: "4".repeat(32),
        ..f.old_target.clone()
    };
    for (previous_target, previous_lifetime, lifetime) in [
        (f.old_target.clone(), 1_000, u64::MAX),
        (wrong, 1_000, 1_000),
        (f.old_target.clone(), 999, 1_000),
    ] {
        let mut recovery = f.recover(previous_target, previous_lifetime);
        assert!(recovery.advance(&f.new_target, lifetime).is_err());
        assert!(recovery.into_service().is_err());
        assert_eq!(f.snapshot(), before);
    }
    let mut recovery = f.recover(f.old_target.clone(), 1_000);
    recovery.advance(&f.new_target, 1_000).unwrap();
    let after = f.snapshot();
    recovery.advance(&f.new_target, 1_000).unwrap();
    assert_eq!(f.snapshot(), after);
    let changed = NotesTargetIdentity {
        incarnation: "5".repeat(32),
        ..f.new_target.clone()
    };
    assert!(recovery.advance(&changed, 1_000).is_err());
    assert_eq!(f.snapshot(), after);
    recovery.advance(&f.new_target, 1_000).unwrap();
    recovery.into_service().unwrap();
    let proof = f
        .issuer
        .retained_writer_authorization(f.config.writer.as_ref().unwrap())
        .unwrap();
    let mut expected = before.0.clone();
    expected["sequence"] = (before.0["sequence"].as_u64().unwrap() + 1).into();
    expected["writer_authorization"] = serde_json::to_value(proof).unwrap();
    expected["policies"][0] = serde_json::to_value(DeploymentGrantPolicy {
        subject_id: f.old_writer.registered_agent_id.as_str().into(),
        destination_id: f.new_target.destination_id(),
        scope_sha256: f.new_target.scope_digest().into_array(),
        lifetime_ms: 1_000,
    })
    .unwrap();
    assert_eq!(after.0, expected);
    assert_eq!(after.1.last_current, before.1.last_current);
    assert_eq!(after.1.counter, before.1.counter + 1);
    assert_eq!((after.2, after.3), (before.2, before.3));
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_notes_recovery_original_revoked_successor_cannot_rotate_or_adopt() {
    let f = OriginalFixture::new().await;
    let mut recovery = f.recover(f.old_target.clone(), 1_000);
    f.registry
        .revoke(
            &f.config.writer.as_ref().unwrap().authority_lease.lease_id,
            /*expected_revision*/ 1,
            [8; 32],
        )
        .unwrap();
    let before = f.snapshot();
    assert!(recovery.advance(&f.new_target, 1_000).is_err());
    assert!(recovery.into_service().is_err());
    assert_eq!(f.snapshot(), before);
}
