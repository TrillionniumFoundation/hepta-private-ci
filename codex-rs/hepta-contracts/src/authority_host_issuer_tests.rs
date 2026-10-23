use super::*;
use crate::AuthorityClock;
use crate::HostAuthorityClock;
use crate::HostFinalUseIssuer;
use crate::HostIssuerError;
use crate::authority_lease::AuthorityLease;
use crate::authority_lease::AuthorityLeaseBinding;
use crate::authority_lease::AuthorityLeaseError;
use crate::authority_lease::AuthorityLeaseFrontier;
use crate::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;

#[path = "authority_host_issuer_race_tests.rs"]
mod race_tests;

struct Fixture {
    _directory: tempfile::TempDir,
    root: Arc<RootAuthorityDirectory>,
    clock: Arc<dyn AuthorityClock>,
    issuer: HostFinalUseIssuer,
    authority: FinalUseAuthority,
    leases: AuthorityLeaseRegistry,
    binding: FinalUseBinding,
}

impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let root = test_directory(directory.path());
        let clock: Arc<dyn AuthorityClock> =
            Arc::new(HostAuthorityClock::initialize(root.clone(), "issuer-clock".into()).unwrap());
        let issuer = HostFinalUseIssuer::initialize(
            root.clone(),
            OWNER.into(),
            "local-key-1".into(),
            1,
            clock.clone(),
        )
        .unwrap();
        let head = FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let final_frontier = Arc::new(
            HostAuthorityFrontierStore::initialize(
                root.clone(),
                OWNER.into(),
                FinalUseFrontier::for_initial_head(&head).unwrap(),
            )
            .unwrap(),
        );
        let lease_frontier = Arc::new(
            HostAuthorityFrontierStore::initialize(
                root.clone(),
                "leases".into(),
                AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            )
            .unwrap(),
        );
        let final_dir = directory.path().join("final-use");
        let lease_dir = directory.path().join("lease-registry");
        for path in [&final_dir, &lease_dir] {
            std::fs::create_dir(path).unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let authority = FinalUseAuthority::open_state_dir_with_issuer_keys(
            &final_dir,
            OWNER.into(),
            vec![issuer.trust_key()],
            head,
            clock.clone(),
            final_frontier,
        )
        .unwrap();
        let leases = AuthorityLeaseRegistry::open_state_dir_with_trust(
            &lease_dir,
            "leases".into(),
            clock.clone(),
            lease_frontier,
        )
        .unwrap();
        let binding = FinalUseBinding {
            subject_id: "isolated-agent".into(),
            destination_id: "no-effect-test".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        };
        Self {
            _directory: directory,
            root,
            clock,
            issuer,
            authority,
            leases,
            binding,
        }
    }

    fn authorize(&self) {
        let now = self.clock.now_unix_ms().unwrap();
        self.leases
            .put_lease(
                AuthorityLease {
                    schema_version: 1,
                    lease_id: "explicit-lease".into(),
                    authority_epoch: 1,
                    revision: 1,
                    binding: AuthorityLeaseBinding {
                        principal_id: self.binding.subject_id.clone(),
                        operation_class: "runtime.agentd.production_operation".into(),
                        destination_id: self.binding.destination_id.clone(),
                        scope_sha256: self.binding.scope_sha256,
                        payload_sha256: self.binding.payload_sha256,
                    },
                    issued_at_unix_ms: now,
                    expires_at_unix_ms: now + 60_000,
                },
                0,
            )
            .unwrap();
    }

    fn issue(&self, binding: &FinalUseBinding) -> Result<SignedFinalUseGrant, HostIssuerError> {
        self.issuer
            .issue(&self.leases.verifier(), "explicit-lease", 1, binding)
    }
}

#[test]
fn real_issuer_key_is_retained_and_unsafe_or_missing_state_is_not_repaired() {
    let fixture = Fixture::new();
    let original = fixture.issuer.trust_key();
    let reopened = HostFinalUseIssuer::open(
        fixture.root.clone(),
        OWNER.into(),
        "local-key-1".into(),
        1,
        fixture.clock.clone(),
    )
    .unwrap();
    assert_eq!(reopened.trust_key(), original);
    assert!(matches!(
        HostFinalUseIssuer::initialize(
            fixture.root.clone(),
            OWNER.into(),
            "local-key-1".into(),
            1,
            fixture.clock.clone()
        ),
        Err(AuthorityTrustError::Conflict)
    ));
    assert!(
        HostFinalUseIssuer::open(
            fixture.root.clone(),
            OWNER.into(),
            "absent-key".into(),
            1,
            fixture.clock.clone()
        )
        .is_err()
    );
    let independent = Fixture::new();
    assert_ne!(
        original.verifying_key,
        independent.issuer.trust_key().verifying_key
    );
    let key_path = std::fs::read_dir(fixture._directory.path())
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .find(|path| {
            path.file_name()
                .unwrap()
                .to_str()
                .unwrap()
                .starts_with("issuer-v1-")
                && path
                    .extension()
                    .is_some_and(|extension| extension == "json")
        })
        .unwrap();
    let retained = std::fs::read(&key_path).unwrap();
    std::fs::set_permissions(&key_path, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert!(
        HostFinalUseIssuer::open(
            fixture.root.clone(),
            OWNER.into(),
            "local-key-1".into(),
            1,
            fixture.clock.clone()
        )
        .is_err()
    );
    assert_eq!(std::fs::read(key_path).unwrap(), retained);
}

#[test]
fn no_lease_or_changed_binding_cannot_mint_a_grant() {
    let fixture = Fixture::new();
    assert_eq!(
        fixture.issue(&fixture.binding),
        Err(HostIssuerError::Lease(AuthorityLeaseError::LeaseNotFound))
    );
    fixture.authorize();
    for changed in [
        FinalUseBinding {
            subject_id: "other-agent".into(),
            ..fixture.binding.clone()
        },
        FinalUseBinding {
            destination_id: "other-device".into(),
            ..fixture.binding.clone()
        },
        FinalUseBinding {
            scope_sha256: [9; 32],
            ..fixture.binding.clone()
        },
        FinalUseBinding {
            payload_sha256: [9; 32],
            ..fixture.binding.clone()
        },
    ] {
        assert_eq!(
            fixture.issue(&changed),
            Err(HostIssuerError::Lease(AuthorityLeaseError::BindingMismatch))
        );
    }
}

#[test]
fn original_final_use_verifies_real_grant_and_rejects_replay_and_revocation() {
    let fixture = Fixture::new();
    fixture.authorize();
    let grant = fixture.issue(&fixture.binding).unwrap();
    assert!(grant.grant.expires_at_unix_ms - grant.grant.not_before_unix_ms <= 30_000);
    fixture.authority.claim(&grant, &fixture.binding).unwrap();
    assert!(matches!(
        fixture.authority.claim(&grant, &fixture.binding),
        Err(FinalUseError::AlreadyClaimed)
    ));
    let revoked = fixture.issue(&fixture.binding).unwrap();
    let mut head = fixture.authority.revocation_head().unwrap();
    head.revision += 1;
    head.revoked_grant_ids
        .insert(revoked.grant.grant_id.clone());
    fixture.authority.update_revocations(head).unwrap();
    assert!(matches!(
        fixture.authority.claim(&revoked, &fixture.binding),
        Err(FinalUseError::Revoked)
    ));
    fixture.leases.revoke("explicit-lease", 1, [7; 32]).unwrap();
    assert_eq!(
        fixture.issue(&fixture.binding),
        Err(HostIssuerError::Lease(
            AuthorityLeaseError::RevisionMismatch
        ))
    );
    assert_eq!(
        fixture.issuer.issue(
            &fixture.leases.verifier(),
            "explicit-lease",
            2,
            &fixture.binding
        ),
        Err(HostIssuerError::Lease(AuthorityLeaseError::Revoked))
    );
}
