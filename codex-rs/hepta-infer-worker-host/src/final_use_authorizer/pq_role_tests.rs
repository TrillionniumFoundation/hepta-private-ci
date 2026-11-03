use super::*;
use crate::authority_trust_unix::PqTrustOutcomeV2;
use crate::authority_trust_unix::tests::TestService;
use crate::authority_trust_unix::tests::frontier_service;
use crate::authority_trust_unix::tests::key;
use crate::authority_trust_unix::tests::signed;
use codex_hepta_contracts::FinalUseFrontier;
use pretty_assertions::assert_eq;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::Ordering;

enum Role {
    Revocation,
    Clock,
    Frontier,
}

#[test]
fn configured_pq_roles_require_separate_canonical_keys_before_any_effect() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let initial = FinalUseFrontier::for_initial_head_with_profile(
        &head,
        FinalUseAuthenticationProfile::MlDsa65V2,
    )?;
    let clock = TestService::start(&root, "clock.sock", /*seed*/ 80, |request, signer| {
        signed(request, PqTrustOutcomeV2::Clock { unix_ms: 1100 }, signer)
    })?;
    let frontier = frontier_service(&root, initial)?;
    let issuer_key = key(/*seed*/ 82)?.1;
    let feed_key = key(/*seed*/ 83)?.1;
    let clock_key = key(/*seed*/ 80)?.1;
    let state = root.join("authority");
    let config = PqFinalUseAuthorizerConfig {
        authentication_profile: FinalUseAuthenticationProfile::MlDsa65V2,
        issuer_socket: root.join("issuer.sock"),
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "issuer".into(),
        issuer_keys: vec![issuer_key.clone()],
        authority_state_dir: state.clone(),
        head,
        issuer_timeout_ms: 2000,
        revocation_distributor_id: "feed".into(),
        revocation_keys: vec![feed_key.clone()],
        external_clock: clock.config.clone(),
        external_frontier: frontier.config.clone(),
    };

    // Cover all six pairs while retaining different configured role names,
    // key labels and socket paths. Identity is the actual canonical key.
    for (replacement, role) in [
        (issuer_key.clone(), Role::Revocation),
        (issuer_key.clone(), Role::Clock),
        (issuer_key, Role::Frontier),
        (feed_key.clone(), Role::Clock),
        (feed_key, Role::Frontier),
        (clock_key, Role::Frontier),
    ] {
        let mut changed = config.clone();
        match role {
            Role::Revocation => {
                changed.revocation_keys[0].public_key_spki = replacement.public_key_spki;
                changed.revocation_keys[0].public_key_id = replacement.public_key_id;
            }
            Role::Clock => {
                changed.external_clock.public_key_spki = replacement.public_key_spki;
                changed.external_clock.public_key_id = replacement.public_key_id;
            }
            Role::Frontier => {
                changed.external_frontier.public_key_spki = replacement.public_key_spki;
                changed.external_frontier.public_key_id = replacement.public_key_id;
            }
        }
        assert_eq!(
            UnixFinalUseAuthorizer::from_pq_config(changed)
                .err()
                .ok_or("role reuse unexpectedly accepted")?
                .to_string(),
            "PQ final-use authority roles must use distinct public keys"
        );
        assert_eq!(clock.requests.load(Ordering::Relaxed), 0);
        assert_eq!(frontier.requests.load(Ordering::Relaxed), 0);
        assert!(!state.exists());
    }

    // Future rotation keys remain pinned, so sharing one with another role
    // must be refused even when the current issuer key is distinct.
    let mut changed = config.clone();
    let mut future = key(/*seed*/ 80)?.1;
    future.key_id = "future-issuer".into();
    future.not_before_authority_epoch = 2;
    future.not_after_authority_epoch = 3;
    changed.issuer_keys.push(future);
    assert!(UnixFinalUseAuthorizer::from_pq_config(changed).is_err());

    // A supplied digest cannot disguise repeated SPKI bytes. A mismatched pin
    // is rejected by the canonical decoder before contacting a trust service.
    let mut changed = config.clone();
    changed.external_frontier.public_key_spki = changed.external_clock.public_key_spki.clone();
    assert!(UnixFinalUseAuthorizer::from_pq_config(changed).is_err());
    assert_eq!(clock.requests.load(Ordering::Relaxed), 0);
    assert_eq!(frontier.requests.load(Ordering::Relaxed), 0);
    assert!(!state.exists());

    // The same constructor still opens and reopens an ordinary valid owner,
    // including independently keyed rotations not yet active in this epoch.
    let mut valid = config;
    let mut future = key(/*seed*/ 84)?.1;
    future.key_id = "future-issuer".into();
    future.not_before_authority_epoch = 2;
    future.not_after_authority_epoch = 3;
    valid.issuer_keys.push(future);
    let authorizer = UnixFinalUseAuthorizer::from_pq_config(valid.clone())?;
    assert_eq!(authorizer.authority.frontier()?, initial);
    drop(authorizer);
    let reopened = UnixFinalUseAuthorizer::from_pq_config(valid)?;
    assert_eq!(reopened.authority.frontier()?, initial);
    assert!(state.is_dir());
    assert!(clock.requests.load(Ordering::Relaxed) >= 2);
    assert!(frontier.requests.load(Ordering::Relaxed) >= 2);
    Ok(())
}
