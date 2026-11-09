//! Integration coverage for PQ ownership with the retained-use/journal fences.
//! In-memory frontier custody is a test fixture, not production qualification.

use super::FixedClock;
use super::PqFixture;
use super::PqTestResult;
use super::pq_fixture;
use crate::FinalUseAuthority;
use crate::FinalUseError;
use crate::VerifiedUseTokenWitnessV1;
use crate::dispatch_final_use_with_witness;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

fn entered_witness(fixture: &PqFixture) -> PqTestResult<VerifiedUseTokenWitnessV1> {
    let token = fixture
        .authority
        .claim(&fixture.signed, &fixture.signed.grant.binding)?;
    let ((), witness) = dispatch_final_use_with_witness(
        &fixture.authority,
        token,
        &fixture.signed.grant.binding,
        |_| (),
    )?;
    Ok(witness)
}

#[test]
fn pq_retained_use_survives_expiry_and_reopen_but_rechecks_profile_and_revocation() -> PqTestResult
{
    let fixture = pq_fixture()?;
    let witness = entered_witness(&fixture)?;
    let head = fixture.authority.revocation_head()?;
    let frontier = fixture.authority.current_external_frontier()?;
    let claims_path = fixture.directory.path().join("authority.claims");
    let claims = std::fs::read(&claims_path)?;
    assert_eq!(
        fixture.authority.verify_retained_use(
            &fixture.signed,
            &fixture.signed.grant.binding,
            &witness,
        ),
        Ok(head.clone())
    );

    // A valid PQ signature over the classical wire domain cannot select the
    // owner's profile, including on a read-only retained-operation path.
    let mut wrong_profile = fixture.signed.clone();
    wrong_profile.grant.schema_version = 1;
    wrong_profile.signature = fixture
        .key
        .sign_exact_message(&wrong_profile.grant.signing_bytes()?)?
        .to_vec();
    assert_eq!(
        fixture.authority.verify_retained_use(
            &wrong_profile,
            &wrong_profile.grant.binding,
            &witness,
        ),
        Err(FinalUseError::InvalidGrant)
    );
    let mut bad_signature = fixture.signed.clone();
    bad_signature.signature[0] ^= 1;
    assert_eq!(
        fixture.authority.verify_retained_use(
            &bad_signature,
            &bad_signature.grant.binding,
            &witness,
        ),
        Err(FinalUseError::InvalidSignature)
    );
    assert_eq!(fixture.authority.current_external_frontier()?, frontier);
    drop(fixture.authority);

    let reopened = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        fixture.directory.path(),
        "security-owner".into(),
        vec![fixture.trust],
        head.clone(),
        Arc::new(FixedClock(9_000)),
        fixture.frontier,
    )?;
    assert_eq!(
        reopened.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness),
        Ok(head.clone())
    );
    assert_eq!(reopened.current_external_frontier()?, frontier);
    assert_eq!(std::fs::read(&claims_path)?, claims);
    assert_eq!(reopened.capacity()?.used_nonces, 1);
    assert_eq!(
        reopened
            .claim(&fixture.signed, &fixture.signed.grant.binding)
            .unwrap_err(),
        FinalUseError::Expired
    );

    let mut revoked = head;
    revoked.revision += 1;
    revoked
        .revoked_grant_ids
        .insert(fixture.signed.grant.grant_id.clone());
    reopened.update_revocations(revoked)?;
    assert_eq!(
        reopened.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness),
        Err(FinalUseError::Revoked)
    );
    Ok(())
}

#[test]
fn pq_replaced_journal_denies_retained_use_and_pending_dispatch_without_refunding_nonce()
-> PqTestResult {
    let fixture = pq_fixture()?;
    let witness = entered_witness(&fixture)?;
    let mut pending = fixture.signed.clone();
    pending.grant.grant_id = "pending-pq-grant".into();
    pending.grant.nonce = [4; 32];
    pending.signature = fixture
        .key
        .sign_exact_message(&pending.grant.signing_bytes()?)?
        .to_vec();
    let token = fixture.authority.claim(&pending, &pending.grant.binding)?;
    let claims_path = fixture.directory.path().join("authority.claims");
    let moved_path = fixture.directory.path().join("original.claims");
    let claims = std::fs::read(&claims_path)?;
    std::fs::rename(&claims_path, &moved_path)?;
    std::fs::write(&claims_path, &claims)?;
    std::fs::set_permissions(&claims_path, std::fs::Permissions::from_mode(0o600))?;
    assert_eq!(
        fixture.authority.verify_retained_use(
            &fixture.signed,
            &fixture.signed.grant.binding,
            &witness,
        ),
        Err(FinalUseError::Unavailable)
    );
    let called = std::cell::Cell::new(false);
    assert_eq!(
        fixture
            .authority
            .with_dispatch_boundary(token, &pending.grant.binding, || called.set(true)),
        Err(FinalUseError::Unavailable)
    );
    assert!(!called.get());
    assert_eq!(std::fs::read(&claims_path)?, claims);
    assert_eq!(std::fs::read(&moved_path)?, claims);
    // Restoring the original pathname does not un-fence an owner that saw drift.
    std::fs::rename(&moved_path, &claims_path)?;
    assert_eq!(
        fixture.authority.current_external_frontier(),
        Err(FinalUseError::Unavailable)
    );
    Ok(())
}
