use super::*;
use crate::CognitiveScope;
use crate::MemoryDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

#[tokio::test]
async fn independent_agents_share_only_declared_use_and_current_evidence() {
    let temp = tempfile::tempdir().unwrap();
    let owner_id = agent_id(1);
    let consumer_id = agent_id(2);
    let owner_layout = layout(&temp, &owner_id);
    let store = CognitiveStore::open(&owner_layout).await.unwrap();
    let clean = CognitiveStore::open(&layout(&temp, &consumer_id))
        .await
        .unwrap();
    let access = CognitiveAccess::agent_private(owner_id.clone());
    let citation = store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "source.shared",
                "observed input -> verified result",
            ),
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "shared.experience".into(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "use current API signature before editing",
                    citation.clone(),
                ),
            },
        )
        .await
        .unwrap();
    let consumer =
        FederationConsumerAccess::new(consumer_id.clone(), workspace("isolated.clean.workspace"));
    assert!(
        clean
            .latest_memory(
                &CognitiveAccess::agent_private(consumer_id.clone()),
                &memory.id.memory_id
            )
            .await
            .is_err()
    );
    let request = SharedExperienceGrantV1 {
        memory_id: memory.id.memory_id.clone(),
        memory_revision: 1,
        consumer: consumer.clone(),
        purpose: SharedExperiencePurposeV1::Recall,
        expires_at_unix_seconds: now().unwrap() + 60,
    };
    let recall = store
        .grant_shared_experience(&access, &request, 0)
        .await
        .unwrap();
    assert_eq!(
        store
            .grant_shared_experience(&access, &request, 0)
            .await
            .unwrap(),
        recall,
        "lost acknowledgement is an exact replay"
    );
    let mut conflicting = request.clone();
    conflicting.expires_at_unix_seconds += 1;
    assert!(
        store
            .grant_shared_experience(&access, &conflicting, 0)
            .await
            .is_err()
    );
    let replay_purpose = SharedExperiencePurposeV1::Replay {
        parameter_scope: "domain.code-head".into(),
        artifact_consumer: consumer_id.clone(),
    };
    assert!(
        store
            .read_shared_experience(&consumer, recall.policy_id(), &replay_purpose)
            .await
            .is_err()
    );
    assert!(
        store
            .read_shared_experience(
                &FederationConsumerAccess::new(consumer_id.clone(), workspace("other.workspace")),
                recall.policy_id(),
                &SharedExperiencePurposeV1::Recall
            )
            .await
            .is_err()
    );
    let mut training = request.clone();
    training.purpose = replay_purpose.clone();
    let replay = store
        .grant_shared_experience(&access, &training, 0)
        .await
        .unwrap();
    assert_eq!(
        store
            .read_shared_experience(&consumer, replay.policy_id(), &replay_purpose)
            .await
            .unwrap()
            .memory(),
        &memory
    );
    let other_target = SharedExperiencePurposeV1::Replay {
        parameter_scope: "global.base".into(),
        artifact_consumer: consumer_id.clone(),
    };
    assert!(
        store
            .read_shared_experience(&consumer, replay.policy_id(), &other_target)
            .await
            .is_err()
    );
    let other_recipient = SharedExperiencePurposeV1::Replay {
        parameter_scope: "domain.code-head".into(),
        artifact_consumer: agent_id(3),
    };
    assert!(
        store
            .read_shared_experience(&consumer, replay.policy_id(), &other_recipient)
            .await
            .is_err()
    );
    assert!(
        store
            .grant_shared_experience(
                &CognitiveAccess::agent_private(consumer_id.clone()),
                &training,
                0
            )
            .await
            .is_err()
    );
    // Reopening source does not renew permission or install private context.
    store.pool.close().await;
    drop(store);
    let store = CognitiveStore::open(&owner_layout).await.unwrap();
    store.revalidate_shared_experience(&replay).await.unwrap();
    store
        .revoke_shared_experience(&access, &replay)
        .await
        .unwrap();
    assert!(store.revalidate_shared_experience(&replay).await.is_err());
    store
        .revoke_shared_experience(&access, &replay)
        .await
        .unwrap();
    assert!(
        store
            .grant_shared_experience(&access, &training, 0)
            .await
            .is_err(),
        "replay cannot undo revocation"
    );
    store.revalidate_shared_experience(&recall).await.unwrap();
    store
        .correct_memory(
            &access,
            &memory.id.memory_id,
            1,
            &memory_revision(
                CognitiveScope::AgentPrivate,
                "corrected source applicability",
                citation,
            ),
        )
        .await
        .unwrap();
    assert!(store.revalidate_shared_experience(&recall).await.is_err());
    assert!(
        clean
            .latest_memory(
                &CognitiveAccess::agent_private(consumer_id),
                &memory.id.memory_id
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn migration_rebuilds_exact_schema_and_source_withdrawal_never_reopens_use() {
    let temp = tempfile::tempdir().unwrap();
    let owner = agent_id(4);
    let path = layout(&temp, &owner);
    let store = CognitiveStore::open(&path).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let citation = store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "withdraw-source",
                "verified observation",
            ),
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "withdraw-memory".into(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "shared evidence",
                    citation.clone(),
                ),
            },
        )
        .await
        .unwrap();
    let request = SharedExperienceGrantV1 {
        memory_id: memory.id.memory_id.clone(),
        memory_revision: 1,
        consumer: FederationConsumerAccess::new(agent_id(5), workspace("clean")),
        purpose: SharedExperiencePurposeV1::Recall,
        expires_at_unix_seconds: now().unwrap() + 60,
    };
    let receipt = store
        .grant_shared_experience(&access, &request, 0)
        .await
        .unwrap();
    let withdrawn = crate::ForgetMemoryDraft {
        scope: CognitiveScope::AgentPrivate,
        reason: "source withdrawn".into(),
        valid_from_unix_seconds: now().unwrap(),
        citations: vec![citation],
    };
    store
        .forget_memory(&access, &memory.id.memory_id, 1, &withdrawn)
        .await
        .unwrap();
    assert!(store.revalidate_shared_experience(&receipt).await.is_err());
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&path).await.unwrap();
    assert!(
        reopened
            .revalidate_shared_experience(&receipt)
            .await
            .is_err()
    );
    assert!(
        reopened
            .grant_shared_experience(&access, &request, 1)
            .await
            .is_err()
    );
    // The grant history itself remains append-only, not a cache to clear.
    assert!(
        sqlx::query("DELETE FROM shared_experience_use_events")
            .execute(&reopened.pool)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn last_active_revision_can_be_revoked_and_stays_revoked_after_restart() {
    let temp = tempfile::tempdir().unwrap();
    let owner_id = agent_id(7);
    let owner_layout = layout(&temp, &owner_id);
    let store = CognitiveStore::open(&owner_layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner_id);
    let citation = store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "capacity.source",
                "independently observed fact",
            ),
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "capacity.memory".into(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "bounded shared evidence",
                    citation,
                ),
            },
        )
        .await
        .unwrap();
    let request = SharedExperienceGrantV1 {
        memory_id: memory.id.memory_id,
        memory_revision: 1,
        consumer: FederationConsumerAccess::new(agent_id(8), workspace("capacity.consumer")),
        purpose: SharedExperiencePurposeV1::Recall,
        expires_at_unix_seconds: now().unwrap() + 3600,
    };
    let initial = store
        .grant_shared_experience(&access, &request, 0)
        .await
        .unwrap();
    // Seed the equivalent immutable renewal history once. The boundary under
    // test still uses the real grant, read, revoke and reopen owner APIs.
    sqlx::query("WITH RECURSIVE revisions(n) AS (VALUES(2) UNION ALL SELECT n+1 FROM revisions WHERE n < ?) INSERT INTO shared_experience_use_events SELECT policy_id,n,revoked,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at FROM shared_experience_use_events,revisions WHERE policy_id=? AND revision=1")
        .bind(MAX_POLICY_REVISIONS - 1).bind(initial.policy_id().as_str())
        .execute(&store.pool).await.unwrap();
    let receipt = store
        .grant_shared_experience(&access, &request, (MAX_POLICY_REVISIONS - 1) as u64)
        .await
        .unwrap();
    assert_eq!(receipt.policy_revision(), MAX_POLICY_REVISIONS as u64);
    store.revalidate_shared_experience(&receipt).await.unwrap();
    assert!(
        store
            .grant_shared_experience(&access, &request, receipt.policy_revision())
            .await
            .is_err()
    );
    // The reserved slot is enforced by SQLite too, not only by the Rust API.
    assert!(sqlx::query("INSERT INTO shared_experience_use_events SELECT policy_id,revision+1,0,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at FROM shared_experience_use_events WHERE policy_id=? AND revision=?")
        .bind(receipt.policy_id().as_str()).bind(receipt.policy_revision() as i64)
        .execute(&store.pool).await.is_err());
    store
        .revoke_shared_experience(&access, &receipt)
        .await
        .unwrap();
    store
        .revoke_shared_experience(&access, &receipt)
        .await
        .unwrap();
    assert!(store.revalidate_shared_experience(&receipt).await.is_err());
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&owner_layout).await.unwrap();
    assert!(
        reopened
            .revalidate_shared_experience(&receipt)
            .await
            .is_err()
    );
    reopened
        .revoke_shared_experience(&access, &receipt)
        .await
        .unwrap();
    assert!(
        reopened
            .grant_shared_experience(&access, &request, MAX_POLICY_REVISIONS as u64 + 1)
            .await
            .is_err()
    );
}
