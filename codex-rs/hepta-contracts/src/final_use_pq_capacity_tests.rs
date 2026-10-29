use super::*;
use pretty_assertions::assert_eq;

#[test]
fn pq_revocation_capacity_agrees_across_feed_owner_frontier_and_reopen() {
    let fixture = pq_fixture();
    let mut head = fixture.authority.revocation_head().unwrap();
    head.revision += 1;
    head.revoked_grant_ids = (0..256).map(|id| format!("revoked-{id:03}")).collect();
    let update = FinalUseRevocationUpdate::new_pq(
        "distributor".into(),
        head.clone(),
        /*issued_at_unix_ms*/ 1_000,
        /*expires_at_unix_ms*/ 3_000,
    );
    assert!(update.signing_bytes().is_ok());
    fixture.authority.update_revocations(head.clone()).unwrap();
    let capacity = fixture.authority.capacity().unwrap();
    assert_eq!(capacity.revoked_grants, capacity.max_revocations);
    assert!(capacity.rollover_required_with_reserve(/*reserve*/ 1));
    let before = fixture.authority.frontier().unwrap();
    let snapshot = std::fs::read(fixture.directory.path().join("authority.json")).unwrap();
    let mut overflow = head.clone();
    overflow.revision += 1;
    overflow.revoked_grant_ids.insert("one-too-many".into());
    assert_eq!(
        fixture.authority.update_revocations(overflow.clone()),
        Err(FinalUseError::StaleRevocationHead)
    );
    assert_eq!(fixture.authority.frontier().unwrap(), before);
    assert_eq!(
        std::fs::read(fixture.directory.path().join("authority.json")).unwrap(),
        snapshot
    );
    assert!(
        FinalUseRevocationUpdate::new_pq(
            "distributor".into(),
            overflow.clone(),
            /*issued_at_unix_ms*/ 1_000,
            /*expires_at_unix_ms*/ 3_000,
        )
        .signing_bytes()
        .is_err()
    );
    assert_eq!(
        FinalUseFrontier::for_initial_head_with_profile(
            &overflow,
            FinalUseAuthenticationProfile::MlDsa65V2,
        ),
        Err(FinalUseError::InvalidTrust)
    );
    // Classic capacity remains valid under its explicitly pinned profile.
    assert!(FinalUseFrontier::for_initial_head(&overflow).is_ok());
    drop(fixture.authority);
    let reopened = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        fixture.directory.path(),
        "security-owner".into(),
        vec![fixture.trust],
        head,
        Arc::new(FixedClock(2_000)),
        fixture.frontier,
    )
    .unwrap();
    assert_eq!(reopened.capacity().unwrap(), capacity);
}

#[test]
fn pq_oversized_initial_head_fails_before_state_initialization() {
    let fixture = pq_fixture();
    let directory = tempfile::tempdir().unwrap();
    let mut head = fixture.authority.revocation_head().unwrap();
    head.revoked_grant_ids = (0..257).map(|id| format!("revoked-{id:03}")).collect();
    let result = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        directory.path(),
        "security-owner".into(),
        vec![fixture.trust],
        head,
        Arc::new(FixedClock(2_000)),
        fixture.frontier,
    );
    assert!(matches!(result, Err(FinalUseError::InvalidTrust)));
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 0);
}
