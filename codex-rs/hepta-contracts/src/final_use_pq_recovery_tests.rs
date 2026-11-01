//! Sequence controls through the real durable FinalUse owner and consumer entry.
//! The external frontier is a fixture, not a deployed independent trust service.

use super::*;
use pretty_assertions::assert_eq;

fn sign_grant(
    key: &PqNativeSigningKey,
    grant: FinalUseGrant,
) -> Result<SignedFinalUseGrant, Box<dyn std::error::Error>> {
    Ok(SignedFinalUseGrant {
        signature: key.sign_exact_message(&grant.signing_bytes()?)?.to_vec(),
        grant,
    })
}

#[test]
fn pq_final_use_rejections_preserve_later_service_and_recovery_preserves_spent_nonces() {
    let fixture = pq_fixture();
    let state_path = fixture.directory.path().join("authority.json");
    let claims_path = fixture.directory.path().join("authority.claims");
    let old_state = std::fs::read(&state_path).unwrap();
    let old_claims = std::fs::read(&claims_path).unwrap();
    let initial_frontier = fixture.authority.frontier().unwrap();
    let initial_capacity = fixture.authority.capacity().unwrap();
    let binding = fixture.signed.grant.binding.clone();

    let mut classic = fixture.signed.clone();
    classic.grant.schema_version = 1;
    classic.signature = SigningKey::from_bytes(&[47; 32])
        .sign(&classic.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    assert!(fixture.authority.claim(&classic, &binding).is_err());

    let mut expired = fixture.signed.grant.clone();
    expired.expires_at_unix_ms = 2_000;
    assert!(
        fixture
            .authority
            .claim(&sign_grant(&fixture.key, expired).unwrap(), &binding)
            .is_err()
    );
    let mut stale = fixture.signed.grant.clone();
    stale.authority_epoch = 8;
    assert!(
        fixture
            .authority
            .claim(&sign_grant(&fixture.key, stale).unwrap(), &binding)
            .is_err()
    );
    let mut other_binding = binding.clone();
    other_binding.payload_sha256[0] ^= 1;
    assert!(
        fixture
            .authority
            .claim(&fixture.signed, &other_binding)
            .is_err()
    );
    assert_eq!(fixture.authority.frontier().unwrap(), initial_frontier);
    assert_eq!(fixture.authority.capacity().unwrap(), initial_capacity);
    assert_eq!(std::fs::read(&state_path).unwrap(), old_state);
    assert_eq!(std::fs::read(&claims_path).unwrap(), old_claims);

    // The very same valid request succeeds after all four rejections. Exercise
    // consumer entry, not just signature verification or claim construction.
    let token = fixture.authority.claim(&fixture.signed, &binding).unwrap();
    let (value, witness) =
        crate::deliver_final_use_with_witness(&fixture.authority, token, &binding, || 11).unwrap();
    assert_eq!(value, 11);
    witness.validate().unwrap();
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 1);

    let mut head = fixture.authority.revocation_head().unwrap();
    head.revision += 1;
    head.revoked_grant_ids
        .insert(fixture.signed.grant.grant_id.clone());
    fixture.authority.update_revocations(head.clone()).unwrap();
    let revoked_frontier = fixture.authority.frontier().unwrap();
    assert_eq!(
        fixture
            .authority
            .claim(&fixture.signed, &binding)
            .unwrap_err(),
        FinalUseError::Revoked
    );
    assert_eq!(fixture.authority.frontier().unwrap(), revoked_frontier);

    let mut next = fixture.signed.grant.clone();
    next.grant_id = "pq-after-rejection".into();
    next.nonce = [4; 32];
    let next = sign_grant(&fixture.key, next).unwrap();
    let token = fixture.authority.claim(&next, &binding).unwrap();
    assert_eq!(
        fixture.authority.with_verified_use(token, &binding, || 12),
        Ok(12)
    );
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 2);
    let current_state = std::fs::read(&state_path).unwrap();
    let current_claims = std::fs::read(&claims_path).unwrap();
    let current_frontier = fixture.authority.frontier().unwrap();
    drop(fixture.authority);

    // Restore both local files, retaining the external CAS frontier. Failure
    // must neither reset that frontier nor make the restored nonce reusable.
    std::fs::write(&state_path, old_state).unwrap();
    std::fs::write(&claims_path, old_claims).unwrap();
    assert_eq!(
        FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
            fixture.directory.path(),
            "security-owner".into(),
            vec![fixture.trust.clone()],
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            Arc::new(FixedClock(2_000)),
            fixture.frontier.clone(),
        )
        .unwrap_err(),
        FinalUseError::AntiRollbackViolation
    );
    assert_eq!(
        fixture.frontier.load("security-owner").unwrap(),
        current_frontier
    );

    // Recovery uses the actual current state. It does not manufacture a new
    // namespace, reset the external witness or refresh any consumed credit.
    std::fs::write(&state_path, current_state).unwrap();
    std::fs::write(&claims_path, current_claims).unwrap();
    let recovered = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        fixture.directory.path(),
        "security-owner".into(),
        vec![fixture.trust],
        head,
        Arc::new(FixedClock(2_000)),
        fixture.frontier,
    )
    .unwrap();
    assert_eq!(recovered.frontier().unwrap(), current_frontier);
    assert_eq!(
        recovered.claim(&next, &binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    assert_eq!(
        recovered.claim(&fixture.signed, &binding).unwrap_err(),
        FinalUseError::Revoked
    );
    let mut after_recovery = next.grant;
    after_recovery.grant_id = "pq-after-recovery".into();
    after_recovery.nonce = [5; 32];
    let after_recovery = sign_grant(&fixture.key, after_recovery).unwrap();
    let token = recovered.claim(&after_recovery, &binding).unwrap();
    assert_eq!(recovered.with_verified_use(token, &binding, || 13), Ok(13));
    assert_eq!(recovered.capacity().unwrap().used_nonces, 3);
}
