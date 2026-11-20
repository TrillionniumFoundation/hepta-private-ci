use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct Clock {
    calls: AtomicUsize,
    expire_on: AtomicUsize,
}
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        Ok(if call >= self.expire_on.load(Ordering::SeqCst) {
            20_000
        } else {
            10_000
        })
    }
}
struct Fixture {
    root: tempfile::TempDir,
    clock: Arc<Clock>,
    registry: AuthorityLeaseRegistry,
    issuer: DeploymentFinalUseIssuer,
    writer: HostAuthorityWriterRegistration,
    binding: FinalUseBinding,
}
impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let clock = Arc::new(Clock {
            calls: AtomicUsize::new(0),
            expire_on: AtomicUsize::new(usize::MAX),
        });
        let path = root.path().join("leases");
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &path,
            "original-lease-owner".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            clock.clone(),
        )
        .unwrap();
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        let binding = FinalUseBinding {
            subject_id: agent.as_str().into(),
            destination_id: "original-effect-owner".into(),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
            request_sha256: [3; 32],
        };
        let writer = HostAuthorityWriterRegistration {
            registered_agent_id: agent,
            spawn_generation: 7,
            owner_epoch: 4,
            local_lease_id: "original-local-writer".into(),
            local_lease_generation: 9,
            authority_lease: AuthorityLease {
                schema_version: 1,
                lease_id: "protected-writer-lease".into(),
                revision: 1,
                authority_epoch: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: binding.subject_id.clone(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: "original-cognitive-owner".into(),
                    scope_sha256: [4; 32],
                    payload_sha256: [5; 32],
                },
                issued_at_unix_ms: 10_000,
                expires_at_unix_ms: 20_000,
            },
        };
        registry
            .put_lease(writer.authority_lease.clone(), 0)
            .unwrap();
        registry
            .put_lease(
                AuthorityLease {
                    lease_id: "protected-effect-lease".into(),
                    binding: AuthorityLeaseBinding {
                        principal_id: binding.subject_id.clone(),
                        operation_class: "runtime.agentd.production_operation".into(),
                        destination_id: binding.destination_id.clone(),
                        scope_sha256: binding.scope_sha256,
                        payload_sha256: binding.payload_sha256,
                    },
                    ..writer.authority_lease
                },
                0,
            )
            .unwrap();
        let mut issuer = DeploymentFinalUseIssuer::create(
            &root.path().join("issuer"),
            "canonical-issuer".into(),
            vec![DeploymentGrantPolicy {
                subject_id: binding.subject_id.clone(),
                destination_id: binding.destination_id.clone(),
                scope_sha256: binding.scope_sha256,
                lifetime_ms: 1_000,
            }],
            clock.clone(),
        )
        .unwrap();
        // Unit fixture only: production construction is RootDirectory guarded.
        issuer.lease = Some(
            ProtectedLease::new(registry.verifier(), "protected-effect-lease".into(), 1).unwrap(),
        );
        Self {
            root,
            clock,
            registry,
            issuer,
            writer,
            binding,
        }
    }
    fn sequence(&self) -> u64 {
        self.issuer.store.load(STATE_OWNER).unwrap().sequence
    }
}

#[test]
fn writer_proof_is_retained_across_reads_reopen_and_shared_original_sequence() {
    let fixture = Fixture::new();
    let proof = fixture
        .issuer
        .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
        .unwrap();
    assert_eq!(proof.claims.sequence, 1);
    assert_eq!(proof.claims.local_lease_generation, 9);
    assert_eq!(proof.claims.authority_lease.revision, 1);
    let grant = fixture.issuer.issue(&fixture.binding).unwrap().unwrap();
    assert_eq!(grant.grant.grant_id, "canonical-issuer:1:2");
    let reopened =
        DeploymentFinalUseIssuer::open(&fixture.root.path().join("issuer"), fixture.clock.clone())
            .unwrap();
    assert_eq!(
        reopened
            .retained_writer_authorization(&fixture.writer)
            .unwrap(),
        proof
    );
    assert_eq!(
        fixture
            .issuer
            .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
            .unwrap(),
        proof
    );
    assert_eq!(fixture.sequence(), 2);
    let mut changed = fixture.writer.clone();
    changed.local_lease_generation += 1;
    assert!(
        fixture
            .issuer
            .register_writer_authorization(&changed, &fixture.registry.verifier())
            .is_err()
    );
    assert_eq!(fixture.sequence(), 2);
}

#[test]
fn writer_proof_expiring_after_durable_sequence_is_discarded_without_refund() {
    let fixture = Fixture::new();
    fixture.clock.calls.store(0, Ordering::SeqCst);
    // Original verify, original dispatch fence, pre-CAS time, post-CAS time.
    fixture.clock.expire_on.store(4, Ordering::SeqCst);
    assert!(
        fixture
            .issuer
            .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
            .is_err()
    );
    assert_eq!(fixture.sequence(), 1);
    assert!(
        fixture
            .issuer
            .store
            .load(STATE_OWNER)
            .unwrap()
            .writer_authorization
            .is_none()
    );
    fixture.clock.expire_on.store(usize::MAX, Ordering::SeqCst);
    assert_eq!(
        fixture
            .issuer
            .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
            .unwrap()
            .claims
            .sequence,
        2
    );
}

#[test]
fn writer_proof_rejects_effect_lease_stale_full_lease_and_revocation() {
    let fixture = Fixture::new();
    let mut wrong = fixture.writer.clone();
    wrong.authority_lease = fixture
        .registry
        .read_lease("protected-effect-lease")
        .unwrap()
        .unwrap()
        .lease;
    assert!(
        fixture
            .issuer
            .register_writer_authorization(&wrong, &fixture.registry.verifier())
            .is_err()
    );
    wrong = fixture.writer.clone();
    wrong.authority_lease.expires_at_unix_ms -= 1;
    assert!(
        fixture
            .issuer
            .register_writer_authorization(&wrong, &fixture.registry.verifier())
            .is_err()
    );
    assert_eq!(fixture.sequence(), 0);
    fixture
        .registry
        .revoke("protected-writer-lease", 1, [8; 32])
        .unwrap();
    assert!(
        fixture
            .issuer
            .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
            .is_err()
    );
    assert_eq!(fixture.sequence(), 0);
}

#[test]
fn writer_proof_unrelated_lease_mutation_advances_metadata_without_changing_proof() {
    let fixture = Fixture::new();
    let proof = fixture
        .issuer
        .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
        .unwrap();
    let before = fixture
        .writer
        .with_live(&fixture.registry.verifier(), Ok)
        .unwrap();
    fixture
        .registry
        .put_lease(
            AuthorityLease {
                lease_id: "unrelated".into(),
                ..fixture.writer.authority_lease.clone()
            },
            0,
        )
        .unwrap();
    let after = fixture
        .writer
        .with_live(&fixture.registry.verifier(), Ok)
        .unwrap();
    assert!(after > before);
    assert_eq!(
        fixture
            .issuer
            .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
            .unwrap(),
        proof
    );
    assert_eq!(fixture.sequence(), 1);
}

#[test]
fn writer_proof_concurrent_registration_returns_one_exact_retained_signature() {
    let fixture = Fixture::new();
    let results = std::thread::scope(|scope| {
        let first = scope.spawn(|| {
            fixture
                .issuer
                .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
        });
        let second = scope.spawn(|| {
            fixture
                .issuer
                .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
        });
        (
            first.join().unwrap().unwrap(),
            second.join().unwrap().unwrap(),
        )
    });
    assert_eq!(results.0, results.1);
    assert_eq!(fixture.sequence(), 1);
}
