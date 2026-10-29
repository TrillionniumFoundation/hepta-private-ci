use super::*;
use crate::authority_trust_unix::PqTrustOutcomeV2;
use crate::authority_trust_unix::tests::TestService;
use crate::authority_trust_unix::tests::frontier_service;
use crate::authority_trust_unix::tests::key;
use crate::authority_trust_unix::tests::signed;
use codex_hepta_contracts::FinalUseFrontier;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;
use std::sync::atomic::Ordering;

#[test]
fn ancestor_aliases_are_rejected_before_external_requests_or_owner_open() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let external = root.join("external");
    let services = external.join("services");
    fs::create_dir_all(&services)?;
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let initial = FinalUseFrontier::for_initial_head_with_profile(
        &head,
        FinalUseAuthenticationProfile::MlDsa65V2,
    )?;
    let clock = TestService::start(&services, "clock.sock", /*seed*/ 80, |request, key| {
        signed(request, PqTrustOutcomeV2::Clock { unix_ms: 1100 }, key)
    });
    let frontier = frontier_service(&services, initial);
    let state = root.join("new-owner");
    let issuer = root.join("not-yet-listening.sock");
    let config = PqFinalUseAuthorizerConfig {
        authentication_profile: FinalUseAuthenticationProfile::MlDsa65V2,
        issuer_socket: issuer.clone(),
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "issuer".into(),
        issuer_keys: vec![key(/*seed*/ 82).1],
        authority_state_dir: state.clone(),
        head,
        issuer_timeout_ms: 2000,
        revocation_distributor_id: "feed".into(),
        revocation_keys: vec![key(/*seed*/ 83).1],
        external_clock: clock.config.clone(),
        external_frontier: frontier.config.clone(),
    };
    let alias = root.join("external-alias");
    symlink(&external, &alias)?;
    // The alias is an ancestor, not the immediate socket parent: an lstat of
    // alias/services sees a normal directory and alone does not close the gap.
    let mut cases = Vec::new();
    let mut changed = config.clone();
    changed.external_clock.socket_path = alias.join("services/clock.sock");
    cases.push(changed);
    let mut changed = config.clone();
    changed.external_frontier.socket_path = alias.join("services/frontier.sock");
    cases.push(changed);
    let mut changed = config.clone();
    changed.issuer_socket = alias.join("services/clock.sock");
    cases.push(changed);
    let mut changed = config.clone();
    changed.issuer_socket = alias.join("services/not-yet-listening.sock");
    cases.push(changed);
    let mut changed = config.clone();
    changed.authority_state_dir = alias.join("services");
    cases.push(changed);
    let mut changed = config.clone();
    changed.authority_state_dir = alias.join("missing-owner");
    cases.push(changed);
    let mut changed = config.clone();
    changed.authority_state_dir = services.clone();
    cases.push(changed);
    let mut changed = config.clone();
    changed.issuer_socket = root.join("missing-parent/issuer.sock");
    cases.push(changed);
    let mut changed = config.clone();
    changed.external_clock.socket_path = services.join("../services/clock.sock");
    cases.push(changed);
    let mut changed = config.clone();
    changed.issuer_socket = clock.config.socket_path.clone();
    cases.push(changed);
    for changed in cases {
        assert!(UnixFinalUseAuthorizer::from_pq_config(changed).is_err());
        assert_eq!(clock.requests.load(Ordering::Relaxed), 0);
        assert_eq!(frontier.requests.load(Ordering::Relaxed), 0);
        assert!(!state.exists());
        assert!(!services.join("authority.lock").exists());
        assert!(!external.join("missing-owner").exists());
    }
    // Normal canonical configuration may have a missing owner/issuer leaf;
    // only the original authority store creates its new protected directory.
    let authorizer = UnixFinalUseAuthorizer::from_pq_config(config)?;
    assert_eq!(
        authorizer.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );
    assert!(state.is_dir());
    assert!(!issuer.exists());
    assert!(clock.requests.load(Ordering::Relaxed) >= 2);
    assert!(frontier.requests.load(Ordering::Relaxed) >= 2);
    Ok(())
}
