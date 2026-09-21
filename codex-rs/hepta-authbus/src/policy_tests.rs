use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use super::AuthPolicyStore;
use super::PolicyError;
use super::PolicyRevisionDraftV1;
use super::PolicyRuleV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn revision(value: u64) -> Revision {
    Revision::new(value).expect("revision")
}

fn rule(principal: &str, action: &str, resource: &str, allowed: bool) -> PolicyRuleV1 {
    PolicyRuleV1 {
        principal_id: id(principal),
        action_id: id(action),
        resource_id: id(resource),
        allowed,
    }
}

fn draft(value: u64, rules: Vec<PolicyRuleV1>) -> PolicyRevisionDraftV1 {
    PolicyRevisionDraftV1 {
        revision: revision(value),
        source_digest: Digest32::of_bytes(format!("source-{value}").as_bytes()),
        rules,
    }
}

async fn opened() -> (TempDir, AuthPolicyStore) {
    let temp = tempfile::tempdir().expect("tempdir");
    let store = AuthPolicyStore::open(temp.path())
        .await
        .expect("open policy store");
    (temp, store)
}

#[tokio::test]
async fn exact_principal_action_resource_is_allowed_and_missing_rule_denies() {
    let (_temp, store) = opened().await;
    let digest = store
        .publish_revision(draft(
            1,
            vec![
                rule("operator.alice", "request_retry", "runtime.agentd", true),
                rule(
                    "operator.alice",
                    "request_rollback",
                    "runtime.agentd",
                    false,
                ),
            ],
        ))
        .await
        .expect("publish policy");

    let allowed = store
        .authorize(
            &id("operator.alice"),
            &id("request_retry"),
            &id("runtime.agentd"),
            revision(1),
        )
        .await
        .expect("authorize");
    assert!(allowed.allowed);
    assert_eq!(allowed.policy_digest, digest);
    assert!(!allowed.decision_digest.is_zero());

    let explicit_deny = store
        .authorize(
            &id("operator.alice"),
            &id("request_rollback"),
            &id("runtime.agentd"),
            revision(1),
        )
        .await
        .expect("explicit deny");
    assert!(!explicit_deny.allowed);

    let missing = store
        .authorize(
            &id("operator.bob"),
            &id("request_retry"),
            &id("runtime.agentd"),
            revision(1),
        )
        .await
        .expect("missing rule is a decision");
    assert!(!missing.allowed);
}

#[tokio::test]
async fn stale_revision_and_policy_rollback_fail_closed() {
    let (_temp, store) = opened().await;
    store
        .publish_revision(draft(
            1,
            vec![rule(
                "operator.alice",
                "request_retry",
                "runtime.agentd",
                true,
            )],
        ))
        .await
        .expect("publish v1");
    store
        .publish_revision(draft(
            2,
            vec![rule(
                "operator.alice",
                "request_retry",
                "runtime.agentd",
                false,
            )],
        ))
        .await
        .expect("publish v2");

    let stale = store
        .authorize(
            &id("operator.alice"),
            &id("request_retry"),
            &id("runtime.agentd"),
            revision(1),
        )
        .await
        .expect_err("stale revision");
    assert!(matches!(
        stale,
        PolicyError::StaleRevision {
            expected,
            current
        } if expected == revision(1) && current == revision(2)
    ));

    let rollback = store
        .publish_revision(draft(1, vec![]))
        .await
        .expect_err("policy rollback");
    assert!(matches!(rollback, PolicyError::StaleRevision { .. }));
}

#[tokio::test]
async fn exact_revision_replay_is_idempotent_but_changed_semantics_conflict() {
    let (_temp, store) = opened().await;
    let original = draft(
        7,
        vec![rule(
            "operator.alice",
            "request_reconcile",
            "runtime.agentd",
            true,
        )],
    );
    let first = store
        .publish_revision(original.clone())
        .await
        .expect("publish");
    let second = store
        .publish_revision(original)
        .await
        .expect("idempotent publish");
    assert_eq!(first, second);

    let changed = store
        .publish_revision(PolicyRevisionDraftV1 {
            revision: revision(7),
            source_digest: Digest32::of_bytes(b"changed-source"),
            rules: vec![rule(
                "operator.alice",
                "request_reconcile",
                "runtime.agentd",
                false,
            )],
        })
        .await
        .expect_err("same revision changed semantics");
    assert!(matches!(changed, PolicyError::Conflict(_)));
}

#[tokio::test]
async fn duplicate_exact_scope_rules_are_rejected_before_commit() {
    let (_temp, store) = opened().await;
    let duplicate = rule(
        "operator.alice",
        "request_retry",
        "runtime.agentd",
        true,
    );
    let error = store
        .publish_revision(draft(1, vec![duplicate.clone(), duplicate]))
        .await
        .expect_err("duplicate rule");
    assert!(matches!(error, PolicyError::Conflict(_)));
    assert_eq!(store.current_revision().await.expect("current"), None);
}

#[tokio::test]
async fn crash_reopen_preserves_current_policy_and_decision_digest() {
    let (temp, store) = opened().await;
    store
        .publish_revision(draft(
            4,
            vec![rule(
                "operator.alice",
                "runtime_stop",
                "runtime.agentd",
                true,
            )],
        ))
        .await
        .expect("publish");
    let before = store
        .authorize(
            &id("operator.alice"),
            &id("runtime_stop"),
            &id("runtime.agentd"),
            revision(4),
        )
        .await
        .expect("decision before reopen");
    store.close().await;

    let reopened = AuthPolicyStore::open(temp.path())
        .await
        .expect("reopen");
    let after = reopened
        .authorize(
            &id("operator.alice"),
            &id("runtime_stop"),
            &id("runtime.agentd"),
            revision(4),
        )
        .await
        .expect("decision after reopen");
    assert_eq!(before, after);
}

#[tokio::test]
async fn reopen_rejects_rolled_back_current_pointer() {
    let (temp, store) = opened().await;
    let v1 = store
        .publish_revision(draft(1, vec![]))
        .await
        .expect("v1");
    store
        .publish_revision(draft(2, vec![]))
        .await
        .expect("v2");

    sqlx::query(
        "UPDATE auth_policy_current
         SET revision=1, policy_digest=?
         WHERE singleton=1",
    )
    .bind(v1.to_string())
    .execute(&store.pool)
    .await
    .expect("sabotage current pointer");
    store.close().await;

    let error = AuthPolicyStore::open(temp.path())
        .await
        .expect_err("rolled-back current pointer must fail reopen");
    assert!(matches!(error, PolicyError::Corrupt(_)));
}
