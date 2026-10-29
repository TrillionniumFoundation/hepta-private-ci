#![cfg(unix)]
use codex_hepta_bao_adapter::BaoFinalUseHost;
use codex_hepta_bao_adapter::BaoFinalUseHostError;
use codex_hepta_bao_adapter::RegisteredBaoConsumer;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

#[test]
fn original_bao_composition_refuses_classic_authority_with_pq_control_roles() {
    let root = tempfile::tempdir().unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let issuer = SigningKey::from_bytes(&[41; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        root.path(),
        "issuer".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )
    .unwrap();
    let spki = PqNativeSigningKey::public_spki_from_seed(&[42; 32].into());
    let pin = PqAuthorityTrustKey {
        key_id: "pq-key".into(),
        public_key_id: ml_dsa_65_key_id_from_spki(&spki).unwrap(),
        public_key_spki: spki.to_vec(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 9,
    };
    let approval =
        FinalUseApprovalVerifier::new_pq_with_keys("approver".into(), vec![pin.clone()]).unwrap();
    let feed = FinalUseRevocationFeedVerifier::new_pq_with_keys("feed".into(), vec![pin]).unwrap();
    let consumer = RegisteredBaoConsumer::new("consumer".into(), Arc::new(|_| Ok(()))).unwrap();
    assert_eq!(
        BaoFinalUseHost::new(
            authority,
            approval,
            feed,
            Arc::new(SystemAuthorityClock),
            [consumer]
        )
        .unwrap_err(),
        BaoFinalUseHostError::AuthenticationProfileMismatch
    );
}
