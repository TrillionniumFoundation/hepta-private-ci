use super::*;
use codex_hepta_authbus::AuthBusAuthorityStore;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_authbus::QuotaSpec;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

struct Fixture {
    _directory: tempfile::TempDir,
    host: AuthBusAuthorityHost,
    signing: SigningKey,
    original: PolicySpec,
}
impl Fixture {
    async fn new() -> TestResult<Self> {
        let directory = tempfile::tempdir()?;
        let checkpoint_dir = directory.path().join("frontier");
        std::fs::create_dir(&checkpoint_dir)?;
        std::fs::set_permissions(&checkpoint_dir, std::fs::Permissions::from_mode(0o700))?;
        let database = directory.path().join("authority.sqlite");
        let store = AuthBusAuthorityStore::open(&database).await?;
        let frontier = store.authority_frontier_digest().await?;
        store.close().await;
        let checkpoint = checkpoint_dir.join("checkpoint.json");
        std::fs::write(
            &checkpoint,
            serde_json::to_vec(&serde_json::json!({
                "schema_version":1,"owner_id":"maintenance-native","generation":1,"digest":frontier.to_string()
            }))?,
        )?;
        std::fs::set_permissions(&checkpoint, std::fs::Permissions::from_mode(0o600))?;
        let host = AuthBusAuthorityHost::open(&database, checkpoint, "maintenance-native").await?;
        let signing = SigningKey::from_bytes(&[87; 32]);
        host.enroll_issuer(
            IssuerPurpose::TrustedTime,
            IssuerSpec {
                issuer_id: StableId::new("maintenance-time")?,
                key_epoch: Generation::new(1)?,
                verifying_key: signing.verifying_key(),
            },
        )
        .await?;
        let original = PolicySpec {
            policy_id: StableId::new("maintenance-policy")?,
            principal: StableId::new("maintenance-principal")?,
            action: StableId::new("action:bao-read")?,
            scope_digest: Digest32::of_bytes(b"maintenance-exact-scope"),
            effect: PolicyEffect::Allow,
            not_before_ms: 1000,
            expires_at_ms: 100_000,
        };
        let fixture = Self {
            _directory: directory,
            host,
            signing,
            original,
        };
        fixture
            .host
            .create_policy(fixture.original.clone(), fixture.time(1).await?)
            .await?;
        Ok(fixture)
    }
    async fn time(&self, revision: u64) -> TestResult<TrustedTimeSample> {
        let claims = TrustedTimeAttestationClaims {
            issuer_id: StableId::new("maintenance-time")?,
            key_epoch: Generation::new(1)?,
            wall_time_ms: 2000 + revision,
            source_revision: revision,
            source_digest: Digest32::of_bytes(&revision.to_le_bytes()),
        };
        let signed = SignedTrustedTimeAttestation {
            signature: self.signing.sign(&claims.signing_bytes()).to_bytes(),
            claims,
        };
        Ok(self.host.observe_trusted_time_attestation(&signed).await?)
    }
    fn intent(&self, change: PolicyChange) -> RootPolicyIntent {
        RootPolicyIntent {
            schema_version: 1,
            runtime_configuration_sha256: [1; 32],
            expected_policy_revision: 1,
            change,
        }
    }
}

#[tokio::test]
async fn renewal_retains_original_pending_reservation_and_all_quota_counters() -> TestResult {
    let fixture = Fixture::new().await?;
    let time = fixture.time(2).await?;
    let quota = fixture
        .host
        .create_quota(
            QuotaSpec {
                quota_key: StableId::new("quota:maintenance")?,
                principal: fixture.original.principal.clone(),
                scope_digest: fixture.original.scope_digest,
                unit: StableId::new("unit:request")?,
                period_id: StableId::new("period:original")?,
                limit: 3,
            },
            time.clone(),
        )
        .await?;
    let decision = fixture
        .host
        .authorize(
            &fixture.original.principal,
            &fixture.original.action,
            fixture.original.scope_digest,
            1,
            time.clone(),
        )
        .await?;
    let pending = fixture
        .host
        .reserve(
            &decision,
            ReservationRequest {
                quota_key: quota.quota_key.clone(),
                operation_id: StableId::new("operation:original-pending")?,
                amount: 1,
                effect_digest: Digest32::of_bytes(b"original-effect"),
                expected_quota_revision: quota.revision,
                expires_at_ms: 90_000,
            },
            time,
        )
        .await?;
    let quota_before = fixture.host.quota_snapshot(&quota.quota_key).await?;
    let intent = fixture.intent(PolicyChange::Renew {
        expires_at_ms: 200_000,
    });
    let renewed = apply_policy_intent(
        &fixture.host,
        fixture.original.clone(),
        &intent,
        fixture.time(3).await?,
    )
    .await?;
    assert_eq!(
        renewed,
        SecretsPolicyMaintenanceResult {
            policy_id: fixture.original.policy_id.to_string(),
            revision: 2,
            expires_at_ms: 200_000,
            revoked: false,
            already_applied: false
        }
    );
    let repeated = apply_policy_intent(
        &fixture.host,
        fixture.original.clone(),
        &intent,
        fixture.time(4).await?,
    )
    .await?;
    assert_eq!(
        repeated,
        SecretsPolicyMaintenanceResult {
            already_applied: true,
            ..renewed
        }
    );
    assert_eq!(
        fixture.host.reservation(&pending.reservation_id).await?,
        pending
    );
    assert_eq!(
        fixture.host.quota_snapshot(&quota.quota_key).await?,
        quota_before
    );
    assert!(
        fixture
            .host
            .authorize(
                &fixture.original.principal,
                &fixture.original.action,
                fixture.original.scope_digest,
                1,
                fixture.time(5).await?
            )
            .await
            .is_err()
    );
    assert!(
        fixture
            .host
            .authorize(
                &fixture.original.principal,
                &fixture.original.action,
                fixture.original.scope_digest,
                2,
                fixture.time(6).await?
            )
            .await?
            .allowed()
    );
    fixture.host.close().await;
    Ok(())
}

#[tokio::test]
async fn stale_revision_changed_scope_and_reduced_expiry_do_not_mutate_policy() -> TestResult {
    let fixture = Fixture::new().await?;
    let before = fixture
        .host
        .policy_snapshot(&fixture.original.policy_id)
        .await?;
    let mut intent = fixture.intent(PolicyChange::Renew {
        expires_at_ms: 200_000,
    });
    intent.expected_policy_revision = 2;
    assert!(matches!(
        apply_policy_intent(
            &fixture.host,
            fixture.original.clone(),
            &intent,
            fixture.time(2).await?
        )
        .await,
        Err(ConsumerPortError::Conflict)
    ));
    intent.expected_policy_revision = 1;
    let mut changed = fixture.original.clone();
    changed.scope_digest = Digest32::of_bytes(b"different-scope");
    assert!(matches!(
        apply_policy_intent(&fixture.host, changed, &intent, fixture.time(3).await?).await,
        Err(ConsumerPortError::Conflict)
    ));
    intent.change = PolicyChange::Renew {
        expires_at_ms: 99_999,
    };
    assert!(matches!(
        apply_policy_intent(
            &fixture.host,
            fixture.original.clone(),
            &intent,
            fixture.time(4).await?
        )
        .await,
        Err(ConsumerPortError::Rejected)
    ));
    assert_eq!(
        fixture
            .host
            .policy_snapshot(&fixture.original.policy_id)
            .await?,
        before
    );
    fixture.host.close().await;
    Ok(())
}

#[tokio::test]
async fn root_revocation_is_exact_idempotent_and_cannot_be_renewed() -> TestResult {
    let fixture = Fixture::new().await?;
    let intent = fixture.intent(PolicyChange::Revoke {});
    let revoked = apply_policy_intent(
        &fixture.host,
        fixture.original.clone(),
        &intent,
        fixture.time(2).await?,
    )
    .await?;
    assert_eq!(
        revoked,
        SecretsPolicyMaintenanceResult {
            policy_id: fixture.original.policy_id.to_string(),
            revision: 2,
            expires_at_ms: 100_000,
            revoked: true,
            already_applied: false
        }
    );
    assert!(
        apply_policy_intent(
            &fixture.host,
            fixture.original.clone(),
            &intent,
            fixture.time(3).await?
        )
        .await?
        .already_applied
    );
    let mut renew = fixture.intent(PolicyChange::Renew {
        expires_at_ms: 200_000,
    });
    renew.expected_policy_revision = 2;
    assert!(matches!(
        apply_policy_intent(
            &fixture.host,
            fixture.original.clone(),
            &renew,
            fixture.time(4).await?
        )
        .await,
        Err(ConsumerPortError::Rejected)
    ));
    fixture.host.close().await;
    Ok(())
}
