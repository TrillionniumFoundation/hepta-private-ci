use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
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

#[derive(Clone)]
struct Pair {
    notes: NotesTargetIdentity,
    calculator: CalculatorTargetIdentity,
}
impl Pair {
    fn policy(&self) -> RootDesktopPolicy<'_> {
        RootDesktopPolicy {
            notes: &self.notes,
            calculator: &self.calculator,
            grant_lifetime_ms: 1_000,
        }
    }

    fn successor(session: &str, notes: &str, calculator: &str) -> Self {
        Self {
            notes: NotesTargetIdentity {
                session_instance: session.repeat(32),
                task_id: 1,
                incarnation: notes.repeat(32),
            },
            calculator: CalculatorTargetIdentity {
                session_instance: session.repeat(32),
                task_id: 2,
                incarnation: calculator.repeat(32),
            },
        }
    }
}

struct Fixture {
    _root: tempfile::TempDir,
    clock: Arc<Clock>,
    registry: Arc<AuthorityLeaseRegistry>,
    issuer: DeploymentFinalUseIssuer,
    writer: HostAuthorityWriterRegistration,
    old: Pair,
    next: Pair,
    old_grant: SignedFinalUseGrant,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let clock = Arc::new(Clock(AtomicU64::new(10_000)));
        let directory = root.path().join("leases");
        std::fs::create_dir(&directory).unwrap();
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
        let registry = Arc::new(
            AuthorityLeaseRegistry::open_state_dir_with_clock(
                &directory,
                "desktop-owner".into(),
                AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
                clock.clone(),
            )
            .unwrap(),
        );
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        let predecessor = HostAuthorityWriterRegistration {
            registered_agent_id: agent.clone(),
            spawn_generation: 1,
            owner_epoch: 1,
            local_lease_id: "original-local-writer".into(),
            local_lease_generation: 1,
            authority_lease: AuthorityLease {
                schema_version: 1,
                lease_id: "desktop-writer-1".into(),
                revision: 1,
                authority_epoch: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: agent.as_str().into(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: "original-cognitive-owner".into(),
                    scope_sha256: [4; 32],
                    payload_sha256: [5; 32],
                },
                issued_at_unix_ms: 10_000,
                expires_at_unix_ms: 11_000,
            },
        };
        registry
            .put_lease(predecessor.authority_lease.clone(), 0)
            .unwrap();
        // The issuer owns a distinct finite lease. A writer must expire before
        // its successor rotates; that must not expire the original issuer.
        let mut issuer_lease = predecessor.authority_lease.clone();
        issuer_lease.lease_id = "desktop-issuer-authority".into();
        issuer_lease.binding.operation_class = "runtime.agentd.root_issuer".into();
        issuer_lease.binding.destination_id = "original-desktop-issuer".into();
        issuer_lease.expires_at_unix_ms = 100_000;
        registry.put_lease(issuer_lease.clone(), 0).unwrap();
        let old = Pair::successor("1", "2", "3");
        let next = Pair::successor("4", "5", "6");
        let mut policies = old.policy().policies(agent.as_str()).unwrap().to_vec();
        policies.push(DeploymentGrantPolicy {
            subject_id: agent.as_str().into(),
            destination_id: DeploymentFinalUseIssuer::OBJECTIVE_DESTINATION.into(),
            scope_sha256: [7; 32],
            lifetime_ms: 1_000,
        });
        let mut issuer = DeploymentFinalUseIssuer::create(
            &root.path().join("issuer"),
            "original-desktop-issuer".into(),
            policies,
            clock.clone(),
        )
        .unwrap();
        // Ordinary owner fixture uses the original registry, disk CAS and
        // signer. It does not qualify Root custody or real Session identity.
        issuer.lease =
            Some(ProtectedLease::new(registry.verifier(), issuer_lease.lease_id, 1).unwrap());
        let old_proof = issuer
            .register_writer_authorization(&predecessor, &registry.verifier())
            .unwrap();
        let binding = FinalUseBinding {
            subject_id: agent.as_str().into(),
            destination_id: old.calculator.destination_id(),
            scope_sha256: old.calculator.scope_digest().into_array(),
            payload_sha256: [2; 32],
            request_sha256: [3; 32],
        };
        let old_grant = issuer
            .issue_registered_final_use(&binding, &predecessor, &old_proof, 11_000)
            .unwrap()
            .unwrap();
        clock.0.store(11_000, Ordering::SeqCst);
        let mut writer = predecessor.clone();
        writer.spawn_generation = 3;
        writer.owner_epoch = 2;
        writer.local_lease_generation = 2;
        writer.authority_lease.lease_id = "desktop-writer-2".into();
        writer.authority_lease.binding.payload_sha256 = [6; 32];
        writer.authority_lease.issued_at_unix_ms = 11_000;
        writer.authority_lease.expires_at_unix_ms = 21_000;
        registry
            .put_lease(writer.authority_lease.clone(), 0)
            .unwrap();
        issuer
            .rotate_writer_authorization(&predecessor, &old_proof, &writer)
            .unwrap();
        Self {
            _root: root,
            clock,
            registry,
            issuer,
            writer,
            old,
            next,
            old_grant,
        }
    }

    fn state(&self) -> IssuerState {
        self.issuer.store.load(STATE_OWNER).unwrap()
    }

    fn replace(&self, old: &Pair, next: &Pair) -> io::Result<()> {
        self.issuer
            .replace_desktop_policy(&self.writer, old.policy(), next.policy())
    }
}

#[test]
fn desktop_policy_pair_cas_preserves_original_owner_and_reconciles_exact_lost_ack() {
    let f = Fixture::new();
    let before = f.state();
    let frontier = f.registry.frontier().unwrap();
    let key = f.issuer.trust_key().unwrap();
    let mut expected = before.clone();
    let policies = f
        .next
        .policy()
        .policies(f.writer.registered_agent_id.as_str())
        .unwrap();
    expected.policies[0] = policies[0].clone();
    expected.policies[1] = policies[1].clone();
    f.replace(&f.old, &f.next).unwrap();
    assert_eq!(
        serde_json::to_value(f.state()).unwrap(),
        serde_json::to_value(&expected).unwrap()
    );
    f.replace(&f.old, &f.next).unwrap();
    assert_eq!(
        serde_json::to_value(f.state()).unwrap(),
        serde_json::to_value(expected).unwrap()
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
    assert_eq!(
        f.issuer.trust_key().unwrap().verifying_key,
        key.verifying_key
    );
    ed25519_dalek::VerifyingKey::from_bytes(&key.verifying_key)
        .unwrap()
        .verify_strict(
            &f.old_grant.grant.signing_bytes().unwrap(),
            &ed25519_dalek::Signature::from_slice(&f.old_grant.signature).unwrap(),
        )
        .unwrap();
    let proof = f.issuer.retained_writer_authorization(&f.writer).unwrap();
    assert!(
        f.issuer
            .issue_registered_final_use(&f.old_grant.grant.binding, &f.writer, &proof, 21_000,)
            .unwrap()
            .is_none()
    );
    let binding = FinalUseBinding {
        destination_id: f.next.calculator.destination_id(),
        scope_sha256: f.next.calculator.scope_digest().into_array(),
        ..f.old_grant.grant.binding.clone()
    };
    let next = f
        .issuer
        .issue_registered_final_use(&binding, &f.writer, &proof, 21_000)
        .unwrap()
        .unwrap();
    assert_eq!(next.grant.binding, binding);
    assert_eq!(f.state().sequence, before.sequence + 1);
}

#[test]
fn desktop_policy_wrong_calculator_predecessor_does_not_replace_notes() {
    let f = Fixture::new();
    let before = f.state();
    let mut wrong = f.old.clone();
    wrong.calculator.incarnation = "7".repeat(32);
    assert!(f.replace(&wrong, &f.next).is_err());
    assert_eq!(
        serde_json::to_value(f.state()).unwrap(),
        serde_json::to_value(before).unwrap()
    );
}

#[test]
fn desktop_policy_partial_pair_and_ambiguous_slot_are_never_promoted() {
    for duplicate in [false, true] {
        let f = Fixture::new();
        let before = f.state();
        let mut inconsistent = before.clone();
        if duplicate {
            inconsistent.policies.push(before.policies[1].clone());
        } else {
            inconsistent.policies[1] = f
                .next
                .policy()
                .policies(f.writer.registered_agent_id.as_str())
                .unwrap()[1]
                .clone();
        }
        f.issuer
            .store
            .compare_and_set(STATE_OWNER, &before, &inconsistent)
            .unwrap();
        assert!(f.replace(&f.old, &f.next).is_err());
        assert_eq!(
            serde_json::to_value(f.state()).unwrap(),
            serde_json::to_value(inconsistent).unwrap()
        );
    }
}

#[test]
fn desktop_policy_expired_or_revoked_writer_keeps_both_original_slots() {
    for revoked in [false, true] {
        let f = Fixture::new();
        let before = f.state();
        if revoked {
            f.registry
                .revoke(&f.writer.authority_lease.lease_id, 1, [9; 32])
                .unwrap();
        } else {
            f.clock.0.store(21_000, Ordering::SeqCst);
        }
        assert!(f.replace(&f.old, &f.next).is_err());
        assert_eq!(
            serde_json::to_value(f.state()).unwrap(),
            serde_json::to_value(before).unwrap()
        );
    }
}

#[test]
fn desktop_policy_competing_successors_publish_only_one_complete_pair() {
    let f = Fixture::new();
    let other = Pair::successor("7", "8", "9");
    let (first, second) = std::thread::scope(|scope| {
        let first = scope.spawn(|| f.replace(&f.old, &f.next));
        let second = scope.spawn(|| f.replace(&f.old, &other));
        (first.join().unwrap(), second.join().unwrap())
    });
    assert_ne!(first.is_ok(), second.is_ok());
    let expected = if first.is_ok() { &f.next } else { &other };
    let expected = expected
        .policy()
        .policies(f.writer.registered_agent_id.as_str())
        .unwrap();
    assert_eq!(&f.state().policies[..2], &expected);
}

#[test]
fn desktop_policy_cross_session_pair_or_reused_incarnation_cannot_change_owner_state() {
    let f = Fixture::new();
    let before = f.state();
    let mut split = f.next.clone();
    split.calculator.session_instance = "7".repeat(32);
    assert!(f.replace(&f.old, &split).is_err());
    let mut reused = f.next.clone();
    reused.notes.incarnation = f.old.notes.incarnation.clone();
    assert!(f.replace(&f.old, &reused).is_err());
    assert_eq!(
        serde_json::to_value(f.state()).unwrap(),
        serde_json::to_value(before).unwrap()
    );
}

#[test]
fn desktop_policy_public_entry_requires_actual_root_before_any_state_change() {
    // SAFETY: only read this process's actual kernel credential.
    if unsafe { libc::getuid() } == 0 && unsafe { libc::geteuid() } == 0 {
        return;
    }
    let f = Fixture::new();
    let before = f.state();
    assert_eq!(
        f.issuer
            .replace_registered_desktop_policy(&f.writer, f.old.policy(), f.next.policy(),)
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(
        serde_json::to_value(f.state()).unwrap(),
        serde_json::to_value(before).unwrap()
    );
}

#[test]
fn desktop_policy_two_successors_keep_one_original_issuer_then_revocation_fences_the_pair() {
    let f = Fixture::new();
    let key = f.issuer.trust_key().unwrap().verifying_key;
    f.replace(&f.old, &f.next).unwrap();
    let proof = f.issuer.retained_writer_authorization(&f.writer).unwrap();
    f.clock.0.store(21_000, Ordering::SeqCst);
    let mut next_writer = f.writer.clone();
    next_writer.spawn_generation = 5;
    next_writer.owner_epoch = 3;
    next_writer.local_lease_generation = 3;
    next_writer.authority_lease.lease_id = "desktop-writer-3".into();
    next_writer.authority_lease.issued_at_unix_ms = 21_000;
    next_writer.authority_lease.expires_at_unix_ms = 31_000;
    f.registry
        .put_lease(next_writer.authority_lease.clone(), 0)
        .unwrap();
    f.issuer
        .rotate_writer_authorization(&f.writer, &proof, &next_writer)
        .unwrap();
    let third = Pair::successor("a", "b", "c");
    f.issuer
        .replace_desktop_policy(&next_writer, f.next.policy(), third.policy())
        .unwrap();
    assert_eq!(f.issuer.trust_key().unwrap().verifying_key, key);
    let preserved = serde_json::to_value(f.state()).unwrap();
    f.registry
        .revoke("desktop-issuer-authority", 1, [8; 32])
        .unwrap();
    let fourth = Pair::successor("d", "e", "f");
    assert!(
        f.issuer
            .replace_desktop_policy(&next_writer, third.policy(), fourth.policy())
            .is_err()
    );
    assert_eq!(serde_json::to_value(f.state()).unwrap(), preserved);
}

/// Reuse this exact disk/key/registry fixture in the sibling Calculator test.
/// The existing writer rotation and independent issuer parent remain intact.
pub(crate) fn original_calculator_issuer_fixture() -> (
    tempfile::TempDir,
    Arc<AuthorityLeaseRegistry>,
    DeploymentFinalUseIssuer,
    HostAuthorityWriterRegistration,
    CalculatorTargetIdentity,
) {
    let f = Fixture::new();
    (f._root, f.registry, f.issuer, f.writer, f.old.calculator)
}
