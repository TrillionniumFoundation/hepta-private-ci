use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn callback() -> BaoConsumerCallback {
    Arc::new(|_| Ok(()))
}

#[test]
fn consumer_registry_is_closed_and_unique() {
    assert_eq!(
        RegisteredBaoConsumer::new("../escape".into(), callback()).unwrap_err(),
        BaoFinalUseHostError::InvalidConsumerId
    );
    let consumer = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
    assert_eq!(consumer.id(), "model-provider");
}

#[test]
fn host_rejects_duplicate_consumer_identity() {
    let directory = tempfile::tempdir().unwrap();
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let issuer = SigningKey::from_bytes(&[31; 32]);
    let approver = SigningKey::from_bytes(&[32; 32]);
    let distributor = SigningKey::from_bytes(&[33; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".into(),
        issuer.verifying_key().to_bytes(),
        codex_hepta_contracts::FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )
    .unwrap();
    let approval_verifier = FinalUseApprovalVerifier::new(
        "operator-approver".into(),
        approver.verifying_key().to_bytes(),
    )
    .unwrap();
    let revocation_verifier = FinalUseRevocationFeedVerifier::new(
        "revocation-distributor".into(),
        distributor.verifying_key().to_bytes(),
    )
    .unwrap();
    let first = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
    let second = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
    assert_eq!(
        BaoFinalUseHost::new(
            authority,
            approval_verifier,
            revocation_verifier,
            Arc::new(codex_hepta_contracts::SystemAuthorityClock),
            [first, second],
        )
        .unwrap_err(),
        BaoFinalUseHostError::DuplicateConsumer
    );
}
#[test]
fn pending_authbus_errors_have_actionable_metric_classes() {
    let reservation_id = StableId::new("reservation:bao-pending").unwrap();
    let indeterminate = BaoProductHostError::AuthBus(BaoAuthBusError::Indeterminate {
        reservation_id: reservation_id.clone(),
        provider_error: BaoClientError::TimedOut,
    });
    assert_eq!(
        indeterminate.class(),
        BaoProductErrorClassV1::AwaitingOriginalEvidence
    );

    let settlement = BaoProductHostError::AuthBus(BaoAuthBusError::SettlementPending {
        reservation_id,
        receipt: None,
        control_error: "synthetic settlement outage".to_owned(),
    });
    assert_eq!(
        settlement.class(),
        BaoProductErrorClassV1::AwaitingSettlement
    );
}

#[test]
fn unavailable_freshness_owner_cannot_advance_durable_revocation_head() {
    use codex_hepta_contracts::FinalUseRevocationUpdate;
    use codex_hepta_contracts::FinalUseRevocations;
    use std::os::unix::fs::PermissionsExt;

    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let issuer = SigningKey::from_bytes(&[41; 32]);
    let approver = SigningKey::from_bytes(&[42; 32]);
    let distributor = SigningKey::from_bytes(&[43; 32]);
    let initial_head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".into(),
        issuer.verifying_key().to_bytes(),
        initial_head.clone(),
    )
    .unwrap();
    let host = Arc::new(
        BaoFinalUseHost::new(
            authority,
            FinalUseApprovalVerifier::new(
                "operator-approver".into(),
                approver.verifying_key().to_bytes(),
            )
            .unwrap(),
            FinalUseRevocationFeedVerifier::new(
                "revocation-distributor".into(),
                distributor.verifying_key().to_bytes(),
            )
            .unwrap(),
            Arc::new(codex_hepta_contracts::SystemAuthorityClock),
            [RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap()],
        )
        .unwrap(),
    );
    let now = host.clock.now_unix_ms().unwrap();
    let update = FinalUseRevocationUpdate::new(
        "revocation-distributor".into(),
        FinalUseRevocations {
            revision: 2,
            ..initial_head.clone()
        },
        now,
        now + 30_000,
    );
    let update = SignedFinalUseRevocationUpdate {
        signature: distributor
            .sign(&update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        update,
    };
    let poisoned_host = Arc::clone(&host);
    assert!(
        std::thread::spawn(move || {
            let _guard = poisoned_host.revocation_fresh_until_unix_ms.lock().unwrap();
            panic!("injected freshness owner failure");
        })
        .join()
        .is_err()
    );
    assert_eq!(
        host.apply_revocation_update(&update),
        Err(BaoFinalUseHostError::Unavailable)
    );
    assert_eq!(host.authority.revocation_head().unwrap(), initial_head);
}
