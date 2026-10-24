//! Actual original Root registry handoff, without a fabricated kernel boot.
use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use pretty_assertions::assert_eq;

#[test]
#[ignore = "requires isolated actual Root checkpoint directory"]
fn root_native_retirement_preserves_original_issued_record_and_revocation() {
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
        .expect("explicit isolated original Root state required");
    let temp = tempfile::tempdir_in(parent).unwrap();
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = RootAuthorityDirectory::open(temp.path()).unwrap();
    let clock = Arc::new(
        HostAuthorityClock::initialize(root.clone(), "native-retire-clock".into()).unwrap(),
    );
    let frontier = Arc::new(
        HostAuthorityFrontierStore::initialize(
            root,
            "native-retire-leases".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
        )
        .unwrap(),
    );
    let path = temp.path().join("leases");
    platform::private_dir(&path, 0, 0, 0o700).unwrap();
    let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
        &path,
        "native-retire-leases".into(),
        clock.clone(),
        frontier,
    )
    .unwrap();
    let now = clock.now_unix_ms().unwrap();
    let issued = AuthorityLease {
        schema_version: 1,
        lease_id: "actual-original-issued-writer".into(),
        authority_epoch: 1,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: AGENT.into(),
            operation_class: "runtime.agentd.production_writer".into(),
            destination_id: format!("cognitive.owner:{AGENT}"),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
        },
        issued_at_unix_ms: now,
        expires_at_unix_ms: now + 20_000,
    };
    registry
        .put_lease(issued.clone(), /*expected_revision*/ 0)
        .unwrap();
    retire_lease_for_handoff(&registry, &clock, &issued, [3; 32]).unwrap();
    let revoked = registry.read_revocation(&issued.lease_id).unwrap().unwrap();
    let retained = registry.read_lease(&issued.lease_id).unwrap().unwrap();
    let mut expected = issued.clone();
    expected.revision += 1;
    assert_eq!(retained.lease, expected);
    // Later cold opening has a different administrative reason. It reuses
    // the actual original revocation and cannot revoke/extend the lease twice.
    retire_lease_for_handoff(&registry, &clock, &issued, [4; 32]).unwrap();
    assert_eq!(
        registry.read_revocation(&issued.lease_id).unwrap().unwrap(),
        revoked
    );
    assert_eq!(
        registry.read_lease(&issued.lease_id).unwrap().unwrap(),
        retained
    );
    let mut different = issued.clone();
    different.binding.payload_sha256 = [9; 32];
    assert!(retire_lease_for_handoff(&registry, &clock, &different, [5; 32]).is_err());
    assert_eq!(
        registry.read_revocation(&issued.lease_id).unwrap().unwrap(),
        revoked
    );
    assert_eq!(
        registry.read_lease(&issued.lease_id).unwrap().unwrap(),
        retained
    );
    assert!(
        registry
            .verifier()
            .verify_use(&issued.lease_id, issued.revision, &issued.binding)
            .is_err()
    );
}
