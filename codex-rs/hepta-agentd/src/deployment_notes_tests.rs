use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

struct Fixture {
    _root: tempfile::TempDir,
    clock: Arc<Clock>,
    registry: Arc<AuthorityLeaseRegistry>,
    issuer: DeploymentFinalUseIssuer,
    writer: HostAuthorityWriterRegistration,
    target: NotesTargetIdentity,
    binding: FinalUseBinding,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let clock = Arc::new(Clock(AtomicU64::new(10_000)));
        let path = root.path().join("leases");
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let registry = Arc::new(AuthorityLeaseRegistry::open_state_dir_with_clock(
            &path, "original-notes-owner".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(), clock.clone(),
        ).unwrap());
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        let target = NotesTargetIdentity {
            session_instance: "1".repeat(32), task_id: 7, incarnation: "2".repeat(32),
        };
        let writer = HostAuthorityWriterRegistration {
            registered_agent_id: agent.clone(), spawn_generation: 7, owner_epoch: 4,
            local_lease_id: "original-local-writer".into(), local_lease_generation: 9,
            authority_lease: AuthorityLease {
                schema_version: 1, lease_id: "original-writer".into(), authority_epoch: 1,
                revision: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: agent.as_str().into(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: "original-cognitive-owner".into(),
                    scope_sha256: [4; 32], payload_sha256: [5; 32],
                },
                issued_at_unix_ms: 10_000, expires_at_unix_ms: 20_000,
            },
        };
        registry.put_lease(writer.authority_lease.clone(), 0).unwrap();
        let binding = FinalUseBinding {
            subject_id: agent.as_str().into(), destination_id: target.destination_id(),
            scope_sha256: target.scope_digest().into_array(),
            payload_sha256: [2; 32], request_sha256: [3; 32],
        };
        let mut issuer = DeploymentFinalUseIssuer::create(
            &root.path().join("issuer"), "canonical-notes-issuer".into(),
            vec![DeploymentGrantPolicy {
                subject_id: binding.subject_id.clone(), destination_id: binding.destination_id.clone(),
                scope_sha256: binding.scope_sha256, lifetime_ms: 1_000,
            }], clock.clone(),
        ).unwrap();
        // Explicit ordinary owner fixture. It does not qualify protected Root
        // construction or actual Session/Host process identity.
        issuer.lease = Some(ProtectedLease::new(
            registry.verifier(), writer.authority_lease.lease_id.clone(), 1,
        ).unwrap());
        issuer.register_writer_authorization(&writer, &registry.verifier()).unwrap();
        Self { _root: root, clock, registry, issuer, writer, target, binding }
    }

    fn admission(&self) -> RootNotesGrantAdmission {
        RootNotesGrantAdmission::open(&self.issuer, self.registry.clone(),
            self.writer.clone(), &self.target, 1_000).unwrap()
    }

    fn sequence(&self) -> u64 {
        self.issuer.store.load(STATE_OWNER).unwrap().sequence
    }
}

#[test]
fn deployment_notes_distinct_payloads_share_canonical_signer_and_original_counter() {
    let f = Fixture::new();
    let admission = f.admission();
    assert_eq!(f.sequence(), 1);
    let first = admission.issue(&f.issuer, &f.binding).unwrap().unwrap();
    let next = FinalUseBinding { payload_sha256: [7; 32], request_sha256: [8; 32], ..f.binding.clone() };
    let second = admission.issue(&f.issuer, &next).unwrap().unwrap();
    assert_eq!(first.grant.grant_id, "canonical-notes-issuer:1:2");
    assert_eq!(second.grant.grant_id, "canonical-notes-issuer:1:3");
    assert_ne!(admission.lease_id(&f.binding).unwrap(), admission.lease_id(&next).unwrap());
    assert_eq!(first.grant.expires_at_unix_ms, 11_000);
    assert_eq!(second.grant.binding, next);
    let key = f.issuer.trust_key().unwrap();
    ed25519_dalek::VerifyingKey::from_bytes(&key.verifying_key).unwrap()
        .verify_strict(&second.grant.signing_bytes().unwrap(),
            &ed25519_dalek::Signature::from_slice(&second.signature).unwrap()).unwrap();
}

#[test]
fn deployment_notes_repeated_binding_never_renews_expired_or_pruned_lease() {
    let f = Fixture::new();
    let admission = f.admission();
    admission.issue(&f.issuer, &f.binding).unwrap().unwrap();
    let id = admission.lease_id(&f.binding).unwrap();
    let original = f.registry.read_lease(&id).unwrap().unwrap().lease;
    f.clock.0.store(10_500, Ordering::SeqCst);
    let second = admission.issue(&f.issuer, &f.binding).unwrap().unwrap();
    assert_eq!(second.grant.expires_at_unix_ms, original.expires_at_unix_ms);
    assert_eq!(f.registry.read_lease(&id).unwrap().unwrap().lease, original);
    f.clock.0.store(11_000, Ordering::SeqCst);
    assert_eq!(admission.issue(&f.issuer, &f.binding).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(f.sequence(), 3);
    assert_eq!(f.registry.prune_expired_leases(1).unwrap(), 1);
    assert!(f.registry.read_lease(&id).unwrap().is_none());
    assert_eq!(admission.issue(&f.issuer, &f.binding).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    assert!(f.registry.read_lease(&id).unwrap().is_none());
    assert_eq!(f.sequence(), 3);
}

#[test]
fn deployment_notes_wrong_scope_subject_or_incarnation_creates_no_lease_or_grant() {
    let f = Fixture::new();
    let admission = f.admission();
    let before = f.registry.frontier().unwrap();
    for binding in [
        FinalUseBinding { destination_id: "device-owner".into(), ..f.binding.clone() },
        FinalUseBinding { subject_id: "another-owner".into(), ..f.binding.clone() },
        FinalUseBinding { scope_sha256: [9; 32], ..f.binding.clone() },
        FinalUseBinding { request_sha256: [0; 32], ..f.binding.clone() },
        FinalUseBinding { payload_sha256: [0; 32], ..f.binding.clone() },
    ] {
        assert!(admission.issue(&f.issuer, &binding).unwrap().is_none());
    }
    let other = NotesTargetIdentity { incarnation: "3".repeat(32), ..f.target.clone() };
    assert!(RootNotesGrantAdmission::open(&f.issuer, f.registry.clone(), f.writer.clone(), &other, 1_000).is_err());
    assert_eq!(f.registry.frontier().unwrap(), before);
    assert_eq!(f.sequence(), 1);
}

#[test]
fn deployment_notes_revoked_effect_and_writer_cannot_sign_or_reset() {
    let f = Fixture::new();
    let admission = f.admission();
    admission.issue(&f.issuer, &f.binding).unwrap().unwrap();
    let id = admission.lease_id(&f.binding).unwrap();
    f.registry.revoke(&id, 1, [9; 32]).unwrap();
    assert_eq!(admission.issue(&f.issuer, &f.binding).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(f.sequence(), 2);
    f.registry.revoke(&f.writer.authority_lease.lease_id, 1, [8; 32]).unwrap();
    let before = f.registry.frontier().unwrap();
    let next = FinalUseBinding { request_sha256: [7; 32], ..f.binding.clone() };
    assert_eq!(admission.issue(&f.issuer, &next).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(f.registry.frontier().unwrap(), before);
    assert_eq!(f.sequence(), 2);
}

#[test]
fn deployment_notes_lookalike_registry_cannot_install_delegation() {
    let f = Fixture::new();
    let other = Fixture::new();
    let before = other.registry.frontier().unwrap();
    assert!(RootNotesGrantAdmission::open(&f.issuer, other.registry.clone(),
        f.writer.clone(), &f.target, 1_000).is_err());
    assert_eq!(other.registry.frontier().unwrap(), before);
    assert_eq!(f.sequence(), 1);
}

#[test]
fn deployment_notes_changed_canonical_proof_cannot_sign_after_original_delegation() {
    let f = Fixture::new();
    let admission = f.admission();
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    let mut changed = state.clone();
    changed.writer_authorization.as_mut().unwrap().claims.spawn_generation += 1;
    f.issuer.store.compare_and_set(STATE_OWNER, &state, &changed).unwrap();
    let before = f.registry.frontier().unwrap();
    assert!(admission.issue(&f.issuer, &f.binding).is_err());
    assert_eq!(f.registry.frontier().unwrap(), before);
    assert_eq!(f.sequence(), 1);
}

#[test]
fn deployment_notes_policy_incarnation_cas_retains_key_head_counter_and_old_grant() {
    let f = Fixture::new();
    let admission = f.admission();
    let old_grant = admission.issue(&f.issuer, &f.binding).unwrap().unwrap();
    let key = f.issuer.trust_key().unwrap();
    let head = f.issuer.revocations().unwrap();
    let next = NotesTargetIdentity { incarnation: "3".repeat(32), ..f.target.clone() };
    f.issuer.replace_notes_policy(&f.writer, &f.target, 1_000, &next, 1_000).unwrap();
    let changed = f.issuer.store.load(STATE_OWNER).unwrap();
    f.issuer.replace_notes_policy(&f.writer, &f.target, 1_000, &next, 1_000).unwrap();
    assert!(admission.issue(&f.issuer, &f.binding).unwrap().is_none());
    assert_eq!(f.issuer.store.load(STATE_OWNER).unwrap().sequence, changed.sequence);
    assert_eq!(f.sequence(), 2);
    assert_eq!(f.issuer.trust_key().unwrap().verifying_key, key.verifying_key);
    assert_eq!(f.issuer.revocations().unwrap(), head);
    let new_admission = RootNotesGrantAdmission::open(&f.issuer, f.registry.clone(),
        f.writer.clone(), &next, 1_000).unwrap();
    let binding = FinalUseBinding { destination_id: next.destination_id(),
        scope_sha256: next.scope_digest().into_array(), ..f.binding.clone() };
    assert_eq!(new_admission.issue(&f.issuer, &binding).unwrap().unwrap().grant.grant_id,
        "canonical-notes-issuer:1:3");
    ed25519_dalek::VerifyingKey::from_bytes(&key.verifying_key).unwrap()
        .verify_strict(&old_grant.grant.signing_bytes().unwrap(),
            &ed25519_dalek::Signature::from_slice(&old_grant.signature).unwrap()).unwrap();
}

#[test]
fn deployment_notes_policy_wrong_predecessor_or_expired_writer_cannot_change_state() {
    let f = Fixture::new();
    let next = NotesTargetIdentity { incarnation: "3".repeat(32), ..f.target.clone() };
    let before = f.issuer.store.load(STATE_OWNER).unwrap();
    assert!(f.issuer.replace_notes_policy(&f.writer, &f.target, 999, &next, 1_000).is_err());
    assert!(f.issuer.replace_notes_policy(&f.writer, &f.target, 1_000, &next, 0).is_err());
    f.clock.0.store(20_000, Ordering::SeqCst);
    assert!(f.issuer.replace_notes_policy(&f.writer, &f.target, 1_000, &next, 1_000).is_err());
    assert!(f.issuer.store.load(STATE_OWNER).unwrap() == before);
}

#[test]
#[ignore = "explicit Root-only exact Notes admission on selected protected filesystem"]
fn deployment_notes_actual_root_clock_registry_and_canonical_issuer_issue_distinct_payloads() {
    use codex_hepta_contracts::HostAuthorityClock;
    use codex_hepta_contracts::HostAuthorityFrontierStore;
    use codex_hepta_contracts::RootAuthorityDirectory;
    // SAFETY: geteuid has no arguments or borrowed memory.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT").unwrap();
    let home = tempfile::Builder::new().prefix("notes-exact-root-").tempdir_in(parent).unwrap();
    std::fs::set_permissions(home.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = RootAuthorityDirectory::open(home.path()).unwrap();
    let clock: Arc<dyn AuthorityClock> = Arc::new(
        HostAuthorityClock::initialize(root.clone(), "notes-exact-clock".into()).unwrap());
    let frontier = Arc::new(HostAuthorityFrontierStore::initialize(root,
        "notes-exact-leases".into(), AuthorityLeaseFrontier::for_empty_epoch(1).unwrap()).unwrap());
    let leases = home.path().join("leases");
    std::fs::create_dir(&leases).unwrap();
    std::fs::set_permissions(&leases, std::fs::Permissions::from_mode(0o700)).unwrap();
    let registry = Arc::new(AuthorityLeaseRegistry::open_state_dir_with_trust(
        &leases, "notes-exact-leases".into(), clock.clone(), frontier).unwrap());
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    // This explicit Root component fixture supplies a synthetic Notes identity;
    // a real Session Reserved capability is a separate launcher qualification.
    let target = NotesTargetIdentity { session_instance: "1".repeat(32), task_id: 7,
        incarnation: "2".repeat(32) };
    let now = clock.now_unix_ms().unwrap();
    let writer = HostAuthorityWriterRegistration {
        registered_agent_id: agent.clone(), spawn_generation: 7, owner_epoch: 4,
        local_lease_id: "original-local-writer".into(), local_lease_generation: 9,
        authority_lease: AuthorityLease {
            schema_version: 1, lease_id: "notes-exact-writer".into(), authority_epoch: 1,
            revision: 1, binding: AuthorityLeaseBinding {
                principal_id: agent.as_str().into(), operation_class: "runtime.agentd.production_writer".into(),
                destination_id: "original-cognitive-owner".into(), scope_sha256: [4; 32], payload_sha256: [5; 32],
            }, issued_at_unix_ms: now, expires_at_unix_ms: now + 60_000,
        },
    };
    registry.put_lease(writer.authority_lease.clone(), 0).unwrap();
    let path = home.path().join("issuer");
    let issuer = DeploymentFinalUseIssuer::create_protected(&path, "canonical-notes-root".into(),
        vec![DeploymentGrantPolicy { subject_id: agent.as_str().into(), destination_id: target.destination_id(),
            scope_sha256: target.scope_digest().into_array(), lifetime_ms: 1_000 }],
        clock.clone(), registry.verifier(), writer.authority_lease.lease_id.clone(), 1).unwrap();
    let proof = issuer.register_writer_authorization(&writer, &registry.verifier()).unwrap();
    assert_eq!(proof.claims.sequence, 1);
    let admission = RootNotesGrantAdmission::from_registered_notes(
        &issuer, registry.clone(), writer.clone(), &target, 1_000).unwrap();
    let binding = FinalUseBinding { subject_id: agent.as_str().into(), destination_id: target.destination_id(),
        scope_sha256: target.scope_digest().into_array(), request_sha256: [1; 32], payload_sha256: [2; 32] };
    let first = admission.issue(&issuer, &binding).unwrap().unwrap();
    let second = admission.issue(&issuer, &FinalUseBinding {
        request_sha256: [3; 32], payload_sha256: [4; 32], ..binding.clone() }).unwrap().unwrap();
    assert_eq!(first.grant.grant_id, "canonical-notes-root:1:2");
    assert_eq!(second.grant.grant_id, "canonical-notes-root:1:3");
    assert_eq!(registry.capacity().unwrap().leases, 3);
    let denied = std::process::Command::new("/usr/bin/setpriv").args([
        "--reuid", "60001", "--regid", "60001", "--clear-groups", "--no-new-privs", "/usr/bin/test", "-r",
    ]).arg(path.join("issuer.key")).status().unwrap();
    assert_eq!(denied.code(), Some(1));
    let key = issuer.trust_key().unwrap();
    drop(admission);
    drop(issuer);
    let reopened = DeploymentFinalUseIssuer::open_protected(&path, clock, registry.verifier(),
        writer.authority_lease.lease_id.clone(), 1).unwrap();
    assert_eq!(reopened.trust_key().unwrap().verifying_key, key.verifying_key);
    assert_eq!(reopened.store.load(STATE_OWNER).unwrap().sequence, 3);
}
