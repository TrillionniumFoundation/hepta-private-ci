//! Real SQL owner recovery/fencing tests; kernel UID separation is qualified
//! separately by starting the production role binary under enrolled accounts.
use crate::ConsumerPortError;
use crate::authority_role_config::SecretsAuthorityServiceConfig;
use crate::authority_role_owner::AuthorityRoleOwner;
use crate::local_service::LocalServiceConfig;
use codex_hepta_contracts::FinalUseApproval;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;

struct Fixture {
    _directory: tempfile::TempDir,
    config: SecretsAuthorityServiceConfig,
    approver: SigningKey,
    distributor: SigningKey,
}
impl Fixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let directory = tempfile::tempdir()?;
        let issuer = SigningKey::from_bytes(&[71; 32]);
        let time = SigningKey::from_bytes(&[72; 32]);
        let approver = SigningKey::from_bytes(&[73; 32]);
        let distributor = SigningKey::from_bytes(&[74; 32]);
        let issuer_file = directory.path().join("issuer.key");
        let time_file = directory.path().join("time.key");
        for (path, seed) in [(&issuer_file, [71; 32]), (&time_file, [72; 32])] {
            std::fs::write(path, seed)?;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        }
        let config = SecretsAuthorityServiceConfig {
            schema_version: 1,
            service: LocalServiceConfig {
                socket_path: directory.path().join("authority.sock"),
                ipc_group_gid: rustix::process::getegid().as_raw(),
                service_uid: rustix::process::geteuid().as_raw(),
                allowed_peer_uids: vec![992, 981],
                request_timeout_ms: 2_000,
                shutdown_drain_ms: 3_000,
            },
            database_path: directory.path().join("authority.sqlite"),
            runtime_uid: 992,
            operator_uid: 981,
            issuer_id: "secrets-native-issuer".into(),
            issuer_signing_key_file: issuer_file,
            issuer_verifying_key: issuer.verifying_key().to_bytes(),
            time_issuer_id: "secrets-native-time".into(),
            time_key_epoch: 1,
            time_signing_key_file: time_file,
            time_verifying_key: time.verifying_key().to_bytes(),
            approver_id: "secrets-native-operator".into(),
            approver_verifying_key: approver.verifying_key().to_bytes(),
            distributor_id: "secrets-native-revocation".into(),
            distributor_verifying_key: distributor.verifying_key().to_bytes(),
            frozen_binding: FinalUseBinding {
                subject_id: "secrets-native-workload".into(),
                destination_id: "provider:heptabao".into(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            initial_revocations: FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            grant_lifetime_ms: 30_000,
        };
        Ok(Self {
            _directory: directory,
            config,
            approver,
            distributor,
        })
    }
    fn approval(
        &self,
        grant: &codex_hepta_contracts::SignedFinalUseGrant,
    ) -> Result<SignedFinalUseApproval, Box<dyn std::error::Error>> {
        let approval = FinalUseApproval::for_grant(self.config.approver_id.clone(), &grant.grant)?;
        let signature = self
            .approver
            .sign(&approval.signing_bytes()?)
            .to_bytes()
            .to_vec();
        Ok(SignedFinalUseApproval {
            approval,
            signature,
        })
    }
    async fn update(
        &self,
        owner: &AuthorityRoleOwner,
        head: FinalUseRevocations,
    ) -> Result<SignedFinalUseRevocationUpdate, Box<dyn std::error::Error>> {
        let now = owner.time().await?.claims.wall_time_ms;
        let update = FinalUseRevocationUpdate::new(
            self.config.distributor_id.clone(),
            head,
            now,
            now + 10_000,
        );
        let signature = self
            .distributor
            .sign(&update.signing_bytes()?)
            .to_bytes()
            .to_vec();
        Ok(SignedFinalUseRevocationUpdate { update, signature })
    }
}
#[tokio::test]
async fn original_grant_and_independent_begin_survive_restart_without_new_effect_admission()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let owner = AuthorityRoleOwner::open(fixture.config.clone()).await?;
    let grant = owner.issue("retained-original").await?;
    let approval = fixture.approval(&grant)?;
    let accepted = owner.begin_original("retained-original", &approval).await?;
    assert_eq!(
        owner.begin_original("retained-original", &approval).await,
        Err(ConsumerPortError::Conflict)
    );
    assert_eq!(
        owner.original_status("retained-original").await?,
        Some(accepted)
    );
    owner.close().await;
    let owner = AuthorityRoleOwner::open(fixture.config.clone()).await?;
    assert_eq!(owner.issue("retained-original").await?, grant);
    assert_eq!(
        owner.original_status("retained-original").await?,
        Some(accepted)
    );
    assert_eq!(
        owner.begin_original("retained-original", &approval).await,
        Err(ConsumerPortError::Conflict)
    );
    assert!(owner.time().await.is_ok());
    owner.close().await;
    Ok(())
}
#[tokio::test]
async fn governed_revocation_does_not_pretend_runtime_cas_and_historical_frontier_cannot_return()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let owner = AuthorityRoleOwner::open(fixture.config.clone()).await?;
    let (initial, head) = owner.frontier().await?;
    let mut advanced = head.clone();
    advanced.revision += 1;
    advanced
        .revoked_grant_ids
        .insert("secrets.read:revoked-original".into());
    let update = fixture.update(&owner, advanced.clone()).await?;
    owner.apply_revocations(&update).await?;
    assert_eq!(owner.frontier().await?, (initial, advanced.clone()));
    let current = FinalUseFrontier {
        authority_epoch: advanced.authority_epoch,
        revocation_revision: advanced.revision,
        state_sha256: [21; 32],
    };
    assert_eq!(
        owner
            .compare_and_set(
                initial,
                FinalUseFrontier {
                    state_sha256: [20; 32],
                    ..initial
                }
            )
            .await,
        Err(ConsumerPortError::Conflict)
    );
    owner.compare_and_set(initial, current).await?;
    let next = FinalUseFrontier {
        state_sha256: [22; 32],
        ..current
    };
    owner.compare_and_set(current, next).await?;
    assert_eq!(
        owner.compare_and_set(next, current).await,
        Err(ConsumerPortError::Conflict)
    );
    owner.close().await;
    let owner = AuthorityRoleOwner::open(fixture.config.clone()).await?;
    assert_eq!(owner.frontier().await?, (next, advanced));
    owner.close().await;
    Ok(())
}
#[tokio::test]
async fn revoked_original_cannot_start_and_signed_revocation_removal_is_rejected()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let owner = AuthorityRoleOwner::open(fixture.config.clone()).await?;
    let grant = owner.issue("revoked-original").await?;
    let approval = fixture.approval(&grant)?;
    let mut head = fixture.config.initial_revocations.clone();
    head.revision += 1;
    head.revoked_grant_ids.insert(grant.grant.grant_id.clone());
    let update = fixture.update(&owner, head.clone()).await?;
    owner.apply_revocations(&update).await?;
    assert_eq!(
        owner.begin_original("revoked-original", &approval).await,
        Err(ConsumerPortError::Rejected)
    );
    head.revision += 1;
    head.revoked_grant_ids.clear();
    let update = fixture.update(&owner, head).await?;
    assert_eq!(
        owner.apply_revocations(&update).await,
        Err(ConsumerPortError::Rejected)
    );
    assert!(owner.time().await.is_ok());
    owner.close().await;
    Ok(())
}
#[tokio::test]
async fn cancelled_writer_fence_keeps_exact_original_readable_without_new_grants()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let owner = AuthorityRoleOwner::open(fixture.config.clone()).await?;
    let grant = owner.issue("original-before-fence").await?;
    let approval = fixture.approval(&grant)?;
    let original = owner
        .begin_original("original-before-fence", &approval)
        .await?;
    owner.fence();
    assert_eq!(
        owner.original_status("original-before-fence").await?,
        Some(original)
    );
    assert_eq!(
        owner.issue("original-after-fence").await,
        Err(ConsumerPortError::Unavailable)
    );
    owner.close().await;
    Ok(())
}
#[tokio::test]
async fn protected_clock_rollback_fences_signing_and_retains_original_status()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let owner = AuthorityRoleOwner::open(fixture.config.clone()).await?;
    let grant = owner.issue("original-clock-floor").await?;
    let approval = fixture.approval(&grant)?;
    let original = owner
        .begin_original("original-clock-floor", &approval)
        .await?;
    sqlx::query(
        "UPDATE authority_role_meta SET last_wall_time_ms=9223372036854775807 WHERE singleton=1",
    )
    .execute(&owner.pool)
    .await?;
    assert!(matches!(
        owner.time().await,
        Err(ConsumerPortError::Unavailable)
    ));
    assert_eq!(
        owner.original_status("original-clock-floor").await?,
        Some(original)
    );
    assert_eq!(
        owner.issue("new-after-clock-fault").await,
        Err(ConsumerPortError::Unavailable)
    );
    owner.close().await;
    Ok(())
}
