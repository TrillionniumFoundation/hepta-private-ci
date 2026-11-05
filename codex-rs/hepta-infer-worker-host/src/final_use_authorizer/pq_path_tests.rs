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
    })?;
    let frontier = frontier_service(&services, initial)?;
    let state = root.join("new-owner");
    let issuer = root.join("not-yet-listening.sock");
    let config = PqFinalUseAuthorizerConfig {
        authentication_profile: FinalUseAuthenticationProfile::MlDsa65V2,
        issuer_socket: issuer.clone(),
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "issuer".into(),
        issuer_keys: vec![key(/*seed*/ 82)?.1],
        authority_state_dir: state.clone(),
        head,
        issuer_timeout_ms: 2000,
        revocation_distributor_id: "feed".into(),
        revocation_keys: vec![key(/*seed*/ 83)?.1],
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
    // Distinct role keys and service IDs must not conceal the same endpoint.
    // Keep both pins unchanged: each refusal must precede any trust request.
    let mut changed = config.clone();
    changed.external_frontier.socket_path = clock.config.socket_path.clone();
    cases.push(changed);
    let mut changed = config.clone();
    changed.external_clock.socket_path = frontier.config.socket_path.clone();
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

#[test]
fn shared_clock_frontier_endpoint_is_rejected_before_service_open() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    // Regular files deliberately cannot serve RPCs. The configuration must be
    // refused by role separation before either trust client is constructed.
    let clock_path = root.join("clock-endpoint");
    let frontier_path = root.join("frontier-endpoint");
    for path in [&clock_path, &frontier_path] {
        fs::write(path, [])?;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    }
    let clock_key = key(/*seed*/ 90)?.1;
    let frontier_key = key(/*seed*/ 91)?.1;
    let state = root.join("new-owner");
    let config = PqFinalUseAuthorizerConfig {
        authentication_profile: FinalUseAuthenticationProfile::MlDsa65V2,
        issuer_socket: root.join("issuer.sock"),
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "issuer".into(),
        issuer_keys: vec![key(/*seed*/ 92)?.1],
        authority_state_dir: state.clone(),
        head: FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        issuer_timeout_ms: 2000,
        revocation_distributor_id: "feed".into(),
        revocation_keys: vec![key(/*seed*/ 93)?.1],
        external_clock: UnixPqTrustEndpointConfig {
            socket_path: clock_path.clone(),
            peer_uid: rustix::process::geteuid().as_raw(),
            service_id: "independent-clock".into(),
            key_generation: 1,
            public_key_id: clock_key.public_key_id,
            public_key_spki: clock_key.public_key_spki,
            timeout_ms: 2000,
        },
        external_frontier: UnixPqTrustEndpointConfig {
            socket_path: frontier_path.clone(),
            peer_uid: rustix::process::geteuid().as_raw(),
            service_id: "independent-frontier".into(),
            key_generation: 1,
            public_key_id: frontier_key.public_key_id,
            public_key_spki: frontier_key.public_key_spki,
            timeout_ms: 2000,
        },
    };
    for shared in [clock_path, frontier_path] {
        let mut changed = config.clone();
        changed.external_clock.socket_path = shared.clone();
        changed.external_frontier.socket_path = shared;
        let error = UnixFinalUseAuthorizer::from_pq_config(changed)
            .err()
            .ok_or("clock and frontier accepted the same endpoint")?;
        assert_eq!(
            error.to_string(),
            "PQ final-use requires distinct explicit external trust services"
        );
        assert!(!state.exists());
    }
    Ok(())
}
