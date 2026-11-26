//! Same-head freshness cannot mutate nonces or admit stale/different policy.
use super::tests::fixture;
use super::*;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
#[test]
fn current_head_freshness_is_exact_signed_and_does_not_change_nonce_frontier() {
    let (authority, grant, _directory, _approver, distributor) = fixture();
    let now = grant.grant.not_before_unix_ms + 1_000;
    let head = authority.revocation_head().unwrap();
    let before = authority.frontier().unwrap();
    let verifier = FinalUseRevocationFeedVerifier::new(
        "signed-operator".into(),
        distributor.verifying_key().to_bytes(),
    )
    .unwrap();
    let update =
        FinalUseRevocationUpdate::new("signed-operator".into(), head.clone(), now - 1, now + 20);
    let mut signed = SignedFinalUseRevocationUpdate {
        signature: distributor
            .sign(&update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        update,
    };
    let receipt = verifier
        .authenticate_current_head(&authority, &signed, now)
        .unwrap();
    assert_eq!(
        (
            receipt.authority_epoch(),
            receipt.revision(),
            receipt.valid_until_unix_ms()
        ),
        (head.authority_epoch, head.revision, now + 20)
    );
    assert_eq!(authority.frontier().unwrap(), before);
    assert!(matches!(
        verifier.apply(&authority, &signed, now),
        Err(FinalUseControlError::Authority(
            FinalUseError::StaleRevocationHead
        ))
    ));
    assert!(matches!(
        verifier.authenticate_current_head(&authority, &signed, now + 20),
        Err(FinalUseControlError::RevocationFeedStale)
    ));
    signed.signature[0] ^= 1;
    assert!(matches!(
        verifier.authenticate_current_head(&authority, &signed, now),
        Err(FinalUseControlError::InvalidSignature)
    ));
    signed
        .update
        .head
        .revoked_grant_ids
        .insert(grant.grant.grant_id);
    signed.signature = distributor
        .sign(&signed.update.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    assert!(matches!(
        verifier.authenticate_current_head(&authority, &signed, now),
        Err(FinalUseControlError::Authority(
            FinalUseError::StaleRevocationHead
        ))
    ));
    assert_eq!(authority.frontier().unwrap(), before);
}
