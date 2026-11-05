//! Actual local key/state checks, not protected Root administration authority.
use super::*;
use codex_hepta_contracts::SystemAuthorityClock;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

fn fixture() -> Result<
    (
        tempfile::TempDir,
        DeploymentFinalUseIssuer,
        SignedFinalUseGrant,
    ),
    Box<dyn std::error::Error>,
> {
    let root = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let issuer = DeploymentFinalUseIssuer::create(
        &root.path().join("issuer"),
        "signed-original".into(),
        vec![DeploymentGrantPolicy {
            subject_id: "original-owner".into(),
            destination_id: "original-note".into(),
            scope_sha256: [1; 32],
            lifetime_ms: 30_000,
        }],
        Arc::new(SystemAuthorityClock),
    )?;
    let signed = issuer
        .issue(&FinalUseBinding {
            subject_id: "original-owner".into(),
            destination_id: "original-note".into(),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
            request_sha256: [3; 32],
        })?
        .ok_or("fixture grant absent")?;
    Ok((root, issuer, signed))
}

#[test]
fn original_signature_nonce_and_each_signed_field_are_independently_required()
-> Result<(), Box<dyn std::error::Error>> {
    let (_root, issuer, signed) = fixture()?;
    let before = issuer.revocations()?;
    assert_eq!(
        issuer.verify_original_signed_grant(&signed, Instant::now() + Duration::from_secs(1))?,
        before
    );
    let (_other_root, other, _) = fixture()?;
    assert!(
        other
            .verify_original_signed_grant(&signed, Instant::now() + Duration::from_secs(1))
            .is_err()
    );
    for field in 0..14 {
        let mut changed = signed.clone();
        match field {
            0 => changed.grant.nonce[0] ^= 1,
            1 => changed.grant.binding.request_sha256[0] ^= 1,
            2 => changed.grant.binding.payload_sha256[0] ^= 1,
            3 => changed.grant.binding.scope_sha256[0] ^= 1,
            4 => changed.grant.authority_epoch += 1,
            5 => changed.grant.signer_id.push('x'),
            6 => changed.grant.grant_id.push('x'),
            7 => changed.grant.expires_at_unix_ms += 1,
            8 => changed.signature[0] ^= 1,
            9 => {
                changed.signature.pop();
            }
            10 => changed.grant.binding.subject_id.push('x'),
            11 => changed.grant.binding.destination_id.push('x'),
            12 => changed.grant.not_before_unix_ms += 1,
            13 => changed.grant.schema_version += 1,
            _ => unreachable!(),
        }
        assert!(
            issuer
                .verify_original_signed_grant(&changed, Instant::now() + Duration::from_secs(1))
                .is_err()
        );
    }
    assert_eq!(issuer.revocations()?, before);
    Ok(())
}

#[test]
fn valid_own_signature_cannot_bypass_old_epoch_canonical_id_or_elapsed_budget()
-> Result<(), Box<dyn std::error::Error>> {
    let (_root, issuer, signed) = fixture()?;
    let mut noncanonical = signed.clone();
    noncanonical.grant.grant_id = "signed-original:1:0001".into();
    noncanonical.signature = issuer
        .key
        .sign(&noncanonical.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    assert!(
        issuer
            .verify_original_signed_grant(&noncanonical, Instant::now() + Duration::from_secs(1))
            .is_err()
    );
    assert!(
        issuer
            .verify_original_signed_grant(&signed, Instant::now())
            .is_err()
    );
    // This explicit local fixture advances its real issuer state while keeping
    // the real key. An old artifact stays validly signed but not current epoch.
    let state = issuer.store.load(STATE_OWNER)?;
    let mut next = state.clone();
    next.head.authority_epoch += 1;
    issuer.store.compare_and_set(STATE_OWNER, &state, &next)?;
    issuer.key.verifying_key().verify_strict(
        &signed.grant.signing_bytes()?,
        &ed25519_dalek::Signature::from_slice(&signed.signature)?,
    )?;
    assert!(
        issuer
            .verify_original_signed_grant(&signed, Instant::now() + Duration::from_secs(1))
            .is_err()
    );
    assert_eq!(issuer.revocations()?, next.head);
    Ok(())
}

#[test]
fn exact_original_head_cas_refuses_stale_revision_without_advancing_real_state()
-> Result<(), Box<dyn std::error::Error>> {
    let (_root, issuer, signed) = fixture()?;
    let original = issuer.revocations()?;
    let first = issuer.revoke(&signed.grant.grant_id)?;
    assert!(
        issuer
            .revoke_at_observed_head(
                "signed-original:1:2",
                &original,
                Instant::now() + Duration::from_secs(1)
            )
            .is_err()
    );
    assert_eq!(issuer.revocations()?, first);
    assert!(
        issuer
            .revoke_at_observed_head("signed-original:1:2", &first, Instant::now())
            .is_err()
    );
    assert_eq!(issuer.revocations()?, first);
    assert_eq!(
        issuer.revoke_at_observed_head(
            &signed.grant.grant_id,
            &first,
            Instant::now() + Duration::from_secs(1)
        )?,
        first
    );
    Ok(())
}

#[test]
fn expired_original_artifact_can_only_be_observed_without_advancing_any_state()
-> Result<(), Box<dyn std::error::Error>> {
    struct AfterExpiry(u64);
    impl codex_hepta_contracts::AuthorityClock for AfterExpiry {
        fn now_unix_ms(&self) -> Result<u64, codex_hepta_contracts::AuthorityTrustError> {
            Ok(self.0)
        }
    }
    let (_root, mut issuer, signed) = fixture()?;
    let original = issuer.store.load(STATE_OWNER)?;
    issuer.clock = Arc::new(AfterExpiry(signed.grant.expires_at_unix_ms));
    assert_eq!(
        issuer.observe_original_signed_grant(&signed, Instant::now() + Duration::from_secs(1))?,
        original.head
    );
    assert!(
        issuer
            .verify_original_signed_grant(&signed, Instant::now() + Duration::from_secs(1))
            .is_err()
    );
    assert!(issuer.store.load(STATE_OWNER)? == original);
    Ok(())
}
