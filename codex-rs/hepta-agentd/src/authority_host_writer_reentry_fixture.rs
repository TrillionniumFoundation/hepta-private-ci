//! Actual isolated Root stores, signed proofs, physical SQLite image and peers.
//! This is owner API qualification, not a native kernel role or daemon claim.

use super::*;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_memory::CognitiveCheckpointCommand;
use codex_hepta_memory::CognitiveCheckpointRequest;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointStatus;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::RootCognitiveMaterialRegistration;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

pub(super) struct Publisher {
    pub(super) child: Child,
    pub(super) retained: crate::RetainedCheckpointPublisher,
}

impl Publisher {
    pub(super) fn spawn() -> Self {
        let mut child = Command::new("/usr/bin/setpriv")
            .args([
                "--reuid=60001",
                "--regid=60001",
                "--clear-groups",
                "--bounding-set=-all",
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--no-new-privs",
                "/usr/bin/sleep",
                "120",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let end = Instant::now() + Duration::from_secs(5);
        loop {
            assert!(child.try_wait().unwrap().is_none());
            let stat = std::fs::read_to_string(format!("/proc/{}/stat", child.id())).unwrap();
            let start = stat
                .rsplit_once(") ")
                .unwrap()
                .1
                .split_whitespace()
                .nth(19)
                .unwrap()
                .parse()
                .unwrap();
            let lifetime = codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                uid: 60001,
                pid: child.id(),
                process_start_ticks: start,
                boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
                    .unwrap()
                    .trim()
                    .into(),
            };
            if let Ok(retained) = crate::RetainedCheckpointPublisher::capture(lifetime) {
                return Self { child, retained };
            }
            assert!(
                Instant::now() < end,
                "actual publisher did not drop credentials"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    pub(super) fn stop(&mut self) {
        if self.child.try_wait().unwrap().is_none() {
            self.child.kill().unwrap();
        }
        assert!(!self.child.wait().unwrap().success());
    }
    pub(super) fn retired(&self) -> crate::RetiredCheckpointPublisher {
        crate::RetiredCheckpointPublisher::observe(self.retained.lifetime().clone()).unwrap()
    }
}
impl Drop for Publisher {
    fn drop(&mut self) {
        if self.child.try_wait().unwrap().is_none() {
            self.child.kill().unwrap();
            self.child.wait().unwrap();
        }
    }
}

pub(super) struct Fixture {
    pub(super) _temp: tempfile::TempDir,
    pub(super) directory: Arc<RootAuthorityDirectory>,
    pub(super) clock: Arc<HostAuthorityClock>,
    pub(super) registry: AuthorityLeaseRegistry,
    pub(super) issuer: DeploymentFinalUseIssuer,
    pub(super) previous: CognitiveCheckpointReceipt,
    pub(super) old: Publisher,
    pub(super) failed: Publisher,
    pub(super) successor: Publisher,
    pub(super) failed_writer: HostAuthorityWriterRegistration,
    pub(super) failed_proof: HostSignedWriterAuthorizationV1,
    pub(super) replacement: HostAuthorityWriterRegistration,
    pub(super) material: VerifiedCognitiveMaterial,
}

fn private(path: &std::path::Path) {
    std::fs::create_dir_all(path).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
}

pub(super) fn checkpoint_registration(
    issuer: &DeploymentFinalUseIssuer,
    registry: &AuthorityLeaseRegistry,
    writer: &HostAuthorityWriterRegistration,
    proof: &HostSignedWriterAuthorizationV1,
    epoch: u64,
    publisher: &Publisher,
) -> crate::HostCognitiveCheckpointRegistration {
    // Use the original registered-writer binding compiler and signature
    // verification. No local grant/fence digest is invented by this fixture.
    RegisteredWriter {
        registration: writer.clone(),
        leases: registry.verifier(),
        proof: proof.clone(),
    }
    .checkpoint_registration(issuer, epoch, publisher.retained.lifetime().clone())
    .unwrap()
}

pub(super) fn current(
    backend: &crate::HostCognitiveCheckpoint,
    epoch: u64,
) -> CognitiveCheckpointReceipt {
    let request = CognitiveCheckpointRequest {
        schema_version: 1,
        operation: "runtime.cognitive.checkpoint.v1".into(),
        request_id: format!("{epoch:016x}{:016x}", 1),
        command: CognitiveCheckpointCommand::ReadHead,
        expected: None,
        proposal: None,
    };
    let response: CognitiveCheckpointResponse = serde_json::from_slice(
        &backend
            .exchange(&serde_json::to_vec(&request).unwrap())
            .unwrap(),
    )
    .unwrap();
    assert_eq!(response.status, CognitiveCheckpointStatus::Ack);
    CognitiveCheckpointReceipt {
        token: response.token.unwrap(),
        head: response.head.unwrap(),
    }
}

impl Fixture {
    pub(super) async fn new() -> Self {
        assert_eq!(
            unsafe { libc::geteuid() },
            0,
            "actual Root qualification required"
        );
        let root = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
            .expect("explicit isolated Root qualification directory required");
        let temp = tempfile::tempdir_in(root).unwrap();
        private(temp.path());
        let owner =
            codex_hepta_contracts::AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
        let layout = HeptaFleetRoot::parse(temp.path().join("fleet"))
            .unwrap()
            .layout()
            .agent(&owner);
        let store = CognitiveStore::open(&layout).await.unwrap();
        let cut = store.recovery_anchor().await.unwrap();
        store.close().await;
        for entry in std::fs::read_dir(layout.cognitive_root()).unwrap() {
            let path = entry.unwrap().path();
            if path.is_file() {
                std::os::unix::fs::chown(&path, Some(60001), Some(60001)).unwrap();
            }
        }
        std::os::unix::fs::chown(layout.cognitive_root(), Some(60001), Some(60001)).unwrap();
        let image = HeptaFleetRoot::parse(temp.path().join("retained-image"))
            .unwrap()
            .layout()
            .agent(&owner);
        private(image.cognitive_root());
        RootCognitiveMaterialRegistration::bind_registered_layout(&layout, 60001)
            .unwrap()
            .materialize_private_candidate(&image)
            .unwrap();
        let material = CognitiveStore::verify_root_material_candidate(&image, &cut)
            .await
            .unwrap();

        let authority = temp.path().join("authority");
        private(&authority);
        let directory = RootAuthorityDirectory::open(&authority).unwrap();
        let clock = Arc::new(
            HostAuthorityClock::initialize(directory.clone(), "reentry-clock".into()).unwrap(),
        );
        let frontier = Arc::new(
            HostAuthorityFrontierStore::initialize(
                directory,
                "reentry-leases".into(),
                AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            )
            .unwrap(),
        );
        let leases = authority.join("leases");
        private(&leases);
        let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
            &leases,
            "reentry-leases".into(),
            clock.clone(),
            frontier,
        )
        .unwrap();
        let now = clock.now_unix_ms().unwrap();
        let root_lease = AuthorityLease {
            schema_version: 1,
            lease_id: "reentry-root-lease".into(),
            authority_epoch: 1,
            revision: 1,
            binding: AuthorityLeaseBinding {
                principal_id: owner.to_string(),
                operation_class: "runtime.agentd.production_operation".into(),
                destination_id: codex_hepta_memory::HOS2_DESTINATION_V1.into(),
                scope_sha256: [1; 32],
                payload_sha256: [2; 32],
            },
            issued_at_unix_ms: now,
            expires_at_unix_ms: now + 90_000,
        };
        registry
            .put_lease(root_lease.clone(), /*expected_revision*/ 0)
            .unwrap();
        let issuer = DeploymentFinalUseIssuer::create_protected(
            &authority.join("issuer"),
            "reentry-issuer".into(),
            vec![crate::DeploymentGrantPolicy {
                subject_id: owner.to_string(),
                destination_id: codex_hepta_memory::HOS2_DESTINATION_V1.into(),
                scope_sha256: [1; 32],
                lifetime_ms: 5_000,
            }],
            clock.clone(),
            registry.verifier(),
            root_lease.lease_id.clone(),
            /*lease_revision*/ 1,
        )
        .unwrap();
        let mut lease = root_lease;
        lease.lease_id = "reentry-writer-original".into();
        lease.binding.operation_class = "runtime.agentd.production_writer".into();
        lease.binding.destination_id = format!("cognitive.owner:{owner}");
        let original = HostAuthorityWriterRegistration {
            registered_agent_id: owner,
            spawn_generation: 1,
            owner_epoch: 1,
            local_lease_id: "reentry-local".into(),
            local_lease_generation: 1,
            authority_lease: lease,
        };
        registry
            .put_lease(
                original.authority_lease.clone(),
                /*expected_revision*/ 0,
            )
            .unwrap();
        let original_proof = issuer
            .register_writer_authorization(&original, &registry.verifier())
            .unwrap();
        let mut old = Publisher::spawn();
        let failed = Publisher::spawn();
        let successor = Publisher::spawn();
        let registration =
            checkpoint_registration(&issuer, &registry, &original, &original_proof, 1, &old);
        let checkpoint = temp.path().join("checkpoint");
        private(&checkpoint);
        let directory = RootAuthorityDirectory::open(&checkpoint).unwrap();
        let backend = crate::HostCognitiveCheckpoint::initialize_fresh(
            directory.clone(),
            registration,
            cut,
            clock.clone(),
        )
        .unwrap();
        let previous = current(&backend, 1);
        old.stop();
        registry
            .revoke(&original.authority_lease.lease_id, 1, [7; 32])
            .unwrap();
        let mut failed_writer = original.clone();
        failed_writer.spawn_generation = 3;
        failed_writer.owner_epoch = 2;
        failed_writer.local_lease_generation = 2;
        failed_writer.authority_lease.lease_id = "reentry-writer-failed".into();
        failed_writer.authority_lease.binding.payload_sha256 = [8; 32];
        registry
            .put_lease(
                failed_writer.authority_lease.clone(),
                /*expected_revision*/ 0,
            )
            .unwrap();
        let failed_proof = issuer
            .rotate_writer_authorization(&original, &original_proof, &failed_writer)
            .unwrap();
        let mut replacement = failed_writer.clone();
        replacement.spawn_generation = 5;
        replacement.owner_epoch = 3;
        replacement.authority_lease.lease_id = "reentry-writer-replacement".into();
        replacement.authority_lease.binding.payload_sha256 = [9; 32];
        replacement.authority_lease.issued_at_unix_ms = clock.now_unix_ms().unwrap();
        replacement.authority_lease.expires_at_unix_ms =
            replacement.authority_lease.issued_at_unix_ms + 90_000;
        registry
            .put_lease(
                replacement.authority_lease.clone(),
                /*expected_revision*/ 0,
            )
            .unwrap();
        Self {
            _temp: temp,
            directory,
            clock,
            registry,
            issuer,
            previous,
            old,
            failed,
            successor,
            failed_writer,
            failed_proof,
            replacement,
            material,
        }
    }

    pub(super) fn retire_failed_authority(&mut self) {
        self.failed.stop();
        self.registry
            .revoke(&self.failed_writer.authority_lease.lease_id, 1, [10; 32])
            .unwrap();
    }
    pub(super) fn replace(&self) -> io::Result<HostSignedWriterAuthorizationV1> {
        self.issuer.replace_unactivated_writer_authorization(
            &self.failed_writer,
            &self.failed_proof,
            &self.replacement,
            self.directory.clone(),
            &self.previous,
            &self.old.retired(),
            &self.failed.retired(),
            &self.successor.retained,
            &self.material,
        )
    }
    pub(super) fn actual_head(&self) -> codex_hepta_memory::CognitiveCheckpointHead {
        HostAuthorityFrontierStore::<codex_hepta_memory::CognitiveCheckpointHead>::open(
            self.directory.clone(),
            "root-cognitive-checkpoint-v1".into(),
        )
        .unwrap()
        .load("root-cognitive-checkpoint-v1")
        .unwrap()
    }
}
