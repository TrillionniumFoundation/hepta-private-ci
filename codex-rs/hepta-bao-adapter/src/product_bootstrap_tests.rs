use super::*;
use pretty_assertions::assert_eq;

#[cfg(unix)]
#[tokio::test]
async fn composition_validates_original_sweep_limit_before_single_claim_normalization() {
    use codex_hepta_contracts::FinalUseApprovalVerifier;
    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SystemAuthorityClock;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt;

    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let issuer = SigningKey::from_bytes(&[101; 32]);
    let approver = SigningKey::from_bytes(&[102; 32]);
    let distributor = SigningKey::from_bytes(&[103; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &directory.path().join("authority"),
        "bootstrap-test-issuer".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )
    .unwrap();
    let host = Arc::new(
        BaoFinalUseHost::new(
            authority,
            FinalUseApprovalVerifier::new(
                "bootstrap-test-approver".into(),
                approver.verifying_key().to_bytes(),
            )
            .unwrap(),
            FinalUseRevocationFeedVerifier::new(
                "bootstrap-test-distributor".into(),
                distributor.verifying_key().to_bytes(),
            )
            .unwrap(),
            Arc::new(SystemAuthorityClock),
            [crate::RegisteredBaoConsumer::new(
                "bootstrap-test-consumer".into(),
                Arc::new(|_| panic!("composition must never enter a consumer")),
            )
            .unwrap()],
        )
        .unwrap(),
    );
    let owner = Arc::new(
        SqliteBaoOwnerV1::open(
            &directory.path().join("bootstrap.sqlite"),
            /*external_checkpoint*/ None,
        )
        .await
        .unwrap(),
    );
    for recovery_batch_limit in [0, 1_025] {
        let config = BaoSqliteProductRuntimeConfigV1 {
            recovery_batch_limit,
            ..Default::default()
        };
        assert_eq!(
            compose_hepta_secrets_runtime(Arc::clone(&host), Arc::clone(&owner), config,).err(),
            Some(BaoFinalUseHostError::InvalidRuntimeConfiguration)
        );
    }
    for recovery_batch_limit in [1, 1_024] {
        let config = BaoSqliteProductRuntimeConfigV1 {
            recovery_batch_limit,
            ..Default::default()
        };
        let runtime =
            compose_hepta_secrets_runtime(Arc::clone(&host), Arc::clone(&owner), config).unwrap();
        assert_eq!(runtime.max_claims_per_sweep, recovery_batch_limit);
    }
    owner.close().await;
}
