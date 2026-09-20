use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

fn fixture() -> (
    tempfile::TempDir,
    std::path::PathBuf,
    SigningKey,
    SignedFinalUseGrant,
) {
    let parent = tempfile::tempdir().unwrap();
    let state = parent.path().join("authority-state");
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 17,
        grant_id: "windows-one".into(),
        nonce: [9; 32],
        binding: FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "ui.native.platform:copy_text".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    (
        parent,
        state,
        issuer,
        SignedFinalUseGrant { grant, signature },
    )
}

fn open(
    state: &std::path::Path,
    issuer: &SigningKey,
    head: FinalUseRevocations,
) -> Result<FinalUseAuthority, FinalUseError> {
    FinalUseAuthority::open_state_dir(
        state,
        "security-owner".into(),
        issuer.verifying_key().to_bytes(),
        head,
    )
}

#[test]
fn windows_durable_nonce_survives_restart_and_keeps_single_owner() {
    let (_parent, state, issuer, signed) = fixture();
    let head = FinalUseRevocations {
        authority_epoch: 17,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let authority = open(&state, &issuer, head.clone()).unwrap();
    assert_eq!(
        open(&state, &issuer, head.clone()).unwrap_err(),
        FinalUseError::StateLocked
    );
    let token = authority.claim(&signed, &signed.grant.binding).unwrap();
    assert_eq!(
        authority.with_verified_use(token, &signed.grant.binding, || 7),
        Ok(7)
    );
    drop(authority);

    let reopened = open(&state, &issuer, head).unwrap();
    assert_eq!(
        reopened
            .claim(&signed, &signed.grant.binding)
            .unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
}

#[test]
fn windows_revocation_head_survives_restart() {
    let (_parent, state, issuer, signed) = fixture();
    let authority = open(
        &state,
        &issuer,
        FinalUseRevocations {
            authority_epoch: 17,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap();
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 17,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
        })
        .unwrap();
    drop(authority);

    let reopened = open(
        &state,
        &issuer,
        FinalUseRevocations {
            authority_epoch: 17,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap();
    assert_eq!(
        reopened
            .claim(&signed, &signed.grant.binding)
            .unwrap_err(),
        FinalUseError::Revoked
    );
}
