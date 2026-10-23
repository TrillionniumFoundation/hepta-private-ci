use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;

enum Stage {
    Checking,
    Complete(Box<io::Result<Option<SignedFinalUseGrant>>>),
}
type Barrier = (mpsc::Sender<Stage>, mpsc::Receiver<()>);
struct Clock {
    now: AtomicU64,
    step: AtomicU64,
    barrier: Mutex<Option<Barrier>>,
}
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if let Some((stage, proceed)) = self.barrier.lock().unwrap().take() {
            stage.send(Stage::Checking).unwrap();
            proceed.recv_timeout(Duration::from_secs(10)).unwrap();
        }
        Ok(self
            .now
            .fetch_add(self.step.load(Ordering::SeqCst), Ordering::SeqCst))
    }
}
fn binding() -> FinalUseBinding {
    FinalUseBinding {
        subject_id: "agent.local".into(),
        destination_id: "notes.local".into(),
        scope_sha256: [2; 32],
        request_sha256: [1; 32],
        payload_sha256: [3; 32],
    }
}
fn policy() -> DeploymentGrantPolicy {
    DeploymentGrantPolicy {
        subject_id: binding().subject_id,
        destination_id: binding().destination_id,
        scope_sha256: binding().scope_sha256,
        lifetime_ms: 30_000,
    }
}
fn lease(now: u64, expires: u64) -> AuthorityLease {
    let binding = binding();
    AuthorityLease {
        schema_version: 1,
        lease_id: "pinned-lease".into(),
        authority_epoch: 1,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: binding.subject_id,
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: binding.destination_id,
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
        },
        issued_at_unix_ms: now,
        expires_at_unix_ms: expires,
    }
}
struct Fixture {
    _root: tempfile::TempDir,
    clock: Arc<Clock>,
    registry: Arc<AuthorityLeaseRegistry>,
    issuer: DeploymentFinalUseIssuer,
}
impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let clock = Arc::new(Clock {
            now: AtomicU64::new(10_000),
            step: AtomicU64::new(0),
            barrier: Mutex::new(None),
        });
        let leases = root.path().join("leases");
        std::fs::create_dir(&leases).unwrap();
        std::fs::set_permissions(&leases, std::fs::Permissions::from_mode(0o700)).unwrap();
        let registry = Arc::new(
            AuthorityLeaseRegistry::open_state_dir_with_clock(
                &leases,
                "lease-owner".into(),
                AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
                clock.clone(),
            )
            .unwrap(),
        );
        registry.put_lease(lease(10_000, 20_000), 0).unwrap();
        let issuer = DeploymentFinalUseIssuer::create(
            &root.path().join("issuer"),
            "test-issuer".into(),
            vec![policy()],
            clock.clone(),
        )
        .unwrap();
        Self {
            _root: root,
            clock,
            registry,
            issuer,
        }
    }
}

#[test]
fn deployment_protected_factory_rejects_unprotected_parent_without_creating_key() {
    let fixture = Fixture::new();
    let path = fixture._root.path().join("protected");
    assert!(
        DeploymentFinalUseIssuer::create_protected(
            &path,
            "issuer".into(),
            vec![policy()],
            fixture.clock,
            fixture.registry.verifier(),
            "pinned-lease".into(),
            1
        )
        .is_err()
    );
    assert!(!path.exists());
}

#[test]
fn deployment_protected_final_use_uses_exact_lease_revision_binding_and_expiry() {
    let mut fixture = Fixture::new();
    fixture.issuer.lease =
        Some(ProtectedLease::new(fixture.registry.verifier(), "pinned-lease".into(), 1).unwrap());
    let first = fixture.issuer.issue(&binding()).unwrap().unwrap();
    assert_eq!(first.grant.expires_at_unix_ms, 20_000);
    assert!(
        fixture
            .issuer
            .issue(&FinalUseBinding {
                payload_sha256: [9; 32],
                ..binding()
            })
            .is_err()
    );
    let newer = AuthorityLease {
        revision: 2,
        expires_at_unix_ms: 15_000,
        ..lease(10_000, 20_000)
    };
    fixture.registry.put_lease(newer, 1).unwrap();
    assert!(fixture.issuer.issue(&binding()).is_err());
    fixture.issuer.lease =
        Some(ProtectedLease::new(fixture.registry.verifier(), "pinned-lease".into(), 2).unwrap());
    assert_eq!(
        fixture
            .issuer
            .issue(&binding())
            .unwrap()
            .unwrap()
            .grant
            .expires_at_unix_ms,
        15_000
    );
}

#[test]
fn deployment_protected_concurrent_revision_cannot_sign_with_an_older_expiry() {
    let mut fixture = Fixture::new();
    fixture.issuer.lease =
        Some(ProtectedLease::new(fixture.registry.verifier(), "pinned-lease".into(), 2).unwrap());
    let (stage, observed) = mpsc::channel();
    let (resume, proceed) = mpsc::channel();
    *fixture.clock.barrier.lock().unwrap() = Some((stage.clone(), proceed));
    let issuer = Arc::new(fixture.issuer);
    let worker_issuer = issuer.clone();
    let worker = std::thread::spawn(move || {
        stage
            .send(Stage::Complete(Box::new(worker_issuer.issue(&binding()))))
            .unwrap();
    });
    let initial = observed.recv_timeout(Duration::from_secs(10)).unwrap();
    fixture
        .registry
        .put_lease(
            AuthorityLease {
                revision: 2,
                expires_at_unix_ms: 15_000,
                ..lease(10_000, 20_000)
            },
            1,
        )
        .unwrap();
    let result = match initial {
        Stage::Complete(result) => *result,
        Stage::Checking => {
            resume.send(()).unwrap();
            match observed.recv_timeout(Duration::from_secs(10)).unwrap() {
                Stage::Complete(result) => *result,
                Stage::Checking => panic!("unexpected second barrier"),
            }
        }
    };
    worker.join().unwrap();
    if let Ok(Some(grant)) = &result {
        assert!(grant.grant.expires_at_unix_ms <= 15_000);
    }
    assert!(result.unwrap_err().to_string().contains("revision"));
    *fixture.clock.barrier.lock().unwrap() = None;
    assert_eq!(
        issuer
            .issue(&binding())
            .unwrap()
            .unwrap()
            .grant
            .expires_at_unix_ms,
        15_000
    );
}

#[test]
fn deployment_final_use_discards_post_io_expiry_without_reusing_its_sequence() {
    let fixture = Fixture::new();
    fixture.clock.step.store(30_001, Ordering::SeqCst);
    assert!(fixture.issuer.issue(&binding()).is_err());
    assert_eq!(fixture.issuer.store.load(STATE_OWNER).unwrap().sequence, 1);
    fixture.clock.step.store(0, Ordering::SeqCst);
    let grant = fixture.issuer.issue(&binding()).unwrap().unwrap();
    assert!(grant.grant.grant_id.ends_with(":2"));
    drop(fixture.issuer);
    let reopened =
        DeploymentFinalUseIssuer::open(&fixture._root.path().join("issuer"), fixture.clock)
            .unwrap();
    assert!(
        reopened
            .issue(&binding())
            .unwrap()
            .unwrap()
            .grant
            .grant_id
            .ends_with(":3")
    );
}

#[test]
#[ignore = "explicit root-only canonical issuer factory qualification on selected protected filesystem"]
fn deployment_protected_root_factory_retains_original_key_head_counter_and_lease() {
    use codex_hepta_contracts::HostAuthorityClock;
    use codex_hepta_contracts::HostAuthorityFrontierStore;
    use codex_hepta_contracts::RootAuthorityDirectory;
    use ed25519_dalek::Verifier;
    // SAFETY: geteuid takes no arguments and borrows no memory.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT").unwrap();
    let state = tempfile::Builder::new()
        .prefix("canonical-root-qualification-")
        .tempdir_in(parent)
        .unwrap();
    std::fs::set_permissions(state.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = RootAuthorityDirectory::open(state.path()).unwrap();
    let clock: Arc<dyn AuthorityClock> =
        Arc::new(HostAuthorityClock::initialize(root.clone(), "canonical-clock".into()).unwrap());
    let frontier = Arc::new(
        HostAuthorityFrontierStore::initialize(
            root,
            "canonical-leases".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
        )
        .unwrap(),
    );
    let path = state.path().join("leases");
    std::fs::create_dir(&path).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
        &path,
        "canonical-leases".into(),
        clock.clone(),
        frontier,
    )
    .unwrap();
    let now = clock.now_unix_ms().unwrap();
    registry.put_lease(lease(now, now + 60_000), 0).unwrap();
    let path = state.path().join("issuer");
    let issuer = DeploymentFinalUseIssuer::create_protected(
        &path,
        "canonical-local".into(),
        vec![policy()],
        clock.clone(),
        registry.verifier(),
        "pinned-lease".into(),
        1,
    )
    .unwrap();
    let public = issuer.trust_key().unwrap();
    let first = issuer.issue(&binding()).unwrap().unwrap();
    ed25519_dalek::VerifyingKey::from_bytes(&public.verifying_key)
        .unwrap()
        .verify(
            &first.grant.signing_bytes().unwrap(),
            &ed25519_dalek::Signature::from_slice(&first.signature).unwrap(),
        )
        .unwrap();
    let denied = std::process::Command::new("/usr/bin/setpriv")
        .args([
            "--reuid",
            "60001",
            "--regid",
            "60001",
            "--clear-groups",
            "--no-new-privs",
            "/usr/bin/test",
            "-r",
        ])
        .arg(path.join("issuer.key"))
        .status()
        .unwrap();
    assert_eq!(denied.code(), Some(1));
    let head = issuer.revoke(&first.grant.grant_id).unwrap();
    assert_eq!(head.revision, 2);
    drop(issuer);
    let issuer = DeploymentFinalUseIssuer::open_protected(
        &path,
        clock,
        registry.verifier(),
        "pinned-lease".into(),
        1,
    )
    .unwrap();
    assert_eq!(
        issuer.trust_key().unwrap().verifying_key,
        public.verifying_key
    );
    assert_eq!(
        DeploymentIssuerObserver::open_protected(&path)
            .unwrap()
            .revocations()
            .unwrap(),
        head
    );
    assert!(
        issuer
            .issue(&binding())
            .unwrap()
            .unwrap()
            .grant
            .grant_id
            .ends_with(":2")
    );
}
