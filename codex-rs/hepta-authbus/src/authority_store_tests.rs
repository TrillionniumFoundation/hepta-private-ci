use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identifier")
}

fn sample(revision: u64, wall_time_ms: u64) -> TrustedTimeSample {
    TrustedTimeSample::new(
        wall_time_ms,
        revision,
        Digest32::of_bytes(format!("trusted-time:{revision}:{wall_time_ms}").as_bytes()),
    )
    .expect("valid trusted time")
}

fn policy(effect: PolicyEffect) -> PolicySpec {
    PolicySpec {
        policy_id: id("policy:tools"),
        principal: id("principal:agent"),
        action: id("action:provider.call"),
        scope_digest: Digest32::of_bytes(b"provider-scope"),
        effect,
        not_before_ms: 1_000,
        expires_at_ms: 10_000,
    }
}

async fn store() -> (TempDir, AuthBusAuthorityStore) {
    let root = TempDir::new().expect("temp dir");
    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
    (root, store)
}

#[tokio::test]
async fn authorization_is_revision_bound_and_explicit_deny_grants_no_authority() {
    let (_root, store) = store().await;
    let created = store
        .create_policy(policy(PolicyEffect::Allow), sample(1, 1_100))
        .await
        .expect("create policy");
    assert_eq!(created.revision, 1);

    let allow = store
        .authorize(
            &created.principal,
            &created.action,
            created.scope_digest,
            /*policy_revision*/ 1,
            sample(2, 1_200),
        )
        .await
        .expect("allow decision");
    assert!(allow.allowed());
    assert!(!allow.authority().grants_any());

    let replaced = store
        .replace_policy(
            policy(PolicyEffect::Deny),
            /*expected_revision*/ 1,
            sample(3, 1_300),
        )
        .await
        .expect("replace policy");
    assert_eq!(replaced.revision, 2);
    assert!(matches!(
        store
            .authorize(
                &replaced.principal,
                &replaced.action,
                replaced.scope_digest,
                /*policy_revision*/ 1,
                sample(4, 1_400),
            )
            .await,
        Err(AuthBusAuthorityError::StalePolicyRevision)
    ));
    let deny = store
        .authorize(
            &replaced.principal,
            &replaced.action,
            replaced.scope_digest,
            /*policy_revision*/ 2,
            sample(4, 1_400),
        )
        .await
        .expect("deny decision");
    assert!(!deny.allowed());
    assert!(!deny.authority().grants_any());
    assert_ne!(allow.decision_digest(), deny.decision_digest());

    let revoked = store
        .revoke_policy(
            &replaced.policy_id,
            /*expected_revision*/ 2,
            sample(5, 1_500),
        )
        .await
        .expect("revoke policy");
    assert_eq!(revoked.revision, 3);
    assert!(revoked.revoked);
    assert!(matches!(
        store
            .authorize(
                &revoked.principal,
                &revoked.action,
                revoked.scope_digest,
                /*policy_revision*/ 3,
                sample(6, 1_600),
            )
            .await,
        Err(AuthBusAuthorityError::PolicyUnavailable)
    ));
}

#[tokio::test]
async fn trusted_time_floor_survives_reopen_and_failed_authorization() {
    let root = TempDir::new().expect("temp dir");
    let path = root.path().join("authbus.sqlite");
    let store = AuthBusAuthorityStore::open(&path)
        .await
        .expect("open authority store");
    let first = sample(10, 2_000);
    store
        .observe_time(first.clone())
        .await
        .expect("record trusted time");
    drop(store);

    let store = AuthBusAuthorityStore::open(&path)
        .await
        .expect("reopen authority store");
    assert_eq!(
        store.last_trusted_time().await.expect("read time"),
        Some(first)
    );
    let missing = sample(11, 2_100);
    assert!(matches!(
        store
            .authorize(
                &id("principal:missing"),
                &id("action:missing"),
                Digest32::of_bytes(b"missing"),
                /*policy_revision*/ 1,
                missing.clone(),
            )
            .await,
        Err(AuthBusAuthorityError::PolicyMissing)
    ));
    assert_eq!(
        store.last_trusted_time().await.expect("read time"),
        Some(missing)
    );
    assert!(matches!(
        store.observe_time(sample(12, 2_099)).await,
        Err(AuthBusAuthorityError::ClockRollback)
    ));
}

