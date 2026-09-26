//! Real owner admission/revocation boundaries with retained historical identities.
use super::*;
use crate::CognitiveScope;
use crate::MemoryDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;
use pretty_assertions::assert_eq;

struct Fixture {
    _temp: tempfile::TempDir,
    layout: codex_hepta_paths::HeptaAgentLayout,
    store: CognitiveStore,
    access: CognitiveAccess,
    request: SharedExperienceGrantV1,
    initial: SharedExperienceUseV1,
}

#[derive(Clone, Copy, Debug)]
enum SeedState {
    Active,
    Expired,
    Revoked,
}

impl Fixture {
    async fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let owner_id = agent_id(61);
        let layout = layout(&temp, &owner_id);
        let store = CognitiveStore::open(&layout).await.unwrap();
        let access = CognitiveAccess::agent_private(owner_id);
        let citation = store
            .append_source(
                &access,
                &source(
                    CognitiveScope::AgentPrivate,
                    "capacity.source",
                    "observed current fact",
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
            consumer: FederationConsumerAccess::new(agent_id(62), workspace("initial")),
            purpose: SharedExperiencePurposeV1::Recall,
            expires_at_unix_seconds: now().unwrap() + 3600,
        };
        let initial = store
            .grant_shared_experience(&access, &request, 0)
            .await
            .unwrap();
        Self {
            _temp: temp,
            layout,
            store,
            access,
            request,
            initial,
        }
    }

    fn request_for(&self, key: &str) -> SharedExperienceGrantV1 {
        let mut request = self.request.clone();
        request.consumer = FederationConsumerAccess::new(agent_id(62), workspace(key));
        request
    }

    // Seed valid-shaped immutable histories in one transaction, rather than
    // spending the watchdog on thousands of fixture fsyncs. All boundaries
    // under test below use the actual owner APIs and current source checks.
    async fn seed(&self, count: usize, state: SeedState) -> Vec<SharedExperienceGrantV1> {
        let mut requests = Vec::with_capacity(count);
        let mut tx = self.store.pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
        for index in 0..count {
            let mut request = self.request_for(&format!("history.{state:?}.{index}"));
            if matches!(state, SeedState::Expired) {
                request.expires_at_unix_seconds = now().unwrap() - 1;
            }
            let key = policy_id(self.store.owner_agent_id(), &request).unwrap();
            sqlx::query("INSERT INTO shared_experience_use_events SELECT ?,1,0,memory_id,memory_revision,content_sha256,consumer_agent_id,?,purpose,parameter_scope,artifact_consumer_id,? FROM shared_experience_use_events WHERE policy_id=? AND revision=1")
                .bind(key.as_str()).bind(request.consumer.workspace_sha256().as_str())
                .bind(request.expires_at_unix_seconds).bind(self.initial.policy_id().as_str())
                .execute(&mut *tx).await.unwrap();
            if matches!(state, SeedState::Revoked) {
                sqlx::query("INSERT INTO shared_experience_use_events SELECT policy_id,2,1,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at FROM shared_experience_use_events WHERE policy_id=? AND revision=1")
                    .bind(key.as_str()).execute(&mut *tx).await.unwrap();
            }
            requests.push(request);
        }
        tx.commit().await.unwrap();
        requests
    }
}

#[tokio::test]
async fn revoked_history_releases_capacity_without_erasing_predecessors_after_reopen() {
    let fixture = Fixture::new().await;
    fixture
        .store
        .revoke_shared_experience(&fixture.access, &fixture.initial)
        .await
        .unwrap();
    fixture
        .seed(
            MAX_ACTIVE_POLICY_IDENTITIES as usize - 1,
            SeedState::Revoked,
        )
        .await;
    let request = fixture.request_for("first-beyond-old-lifetime-limit");
    let admitted = fixture
        .store
        .grant_shared_experience(&fixture.access, &request, 0)
        .await
        .unwrap();
    let identities: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM shared_experience_use_heads")
        .fetch_one(&fixture.store.pool)
        .await
        .unwrap();
    assert_eq!(identities, MAX_ACTIVE_POLICY_IDENTITIES + 1);
    assert!(
        fixture
            .store
            .revalidate_shared_experience(&fixture.initial)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM shared_experience_use_heads WHERE policy_id=?")
            .bind(fixture.initial.policy_id().as_str())
            .execute(&fixture.store.pool)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("UPDATE shared_experience_use_heads SET revoked=0 WHERE policy_id=?")
            .bind(fixture.initial.policy_id().as_str())
            .execute(&fixture.store.pool)
            .await
            .is_err()
    );
    verify_current_use_heads(&fixture.store.pool).await.unwrap();
    fixture.store.pool.close().await;
    drop(fixture.store);
    let reopened = CognitiveStore::open(&fixture.layout).await.unwrap();
    assert!(
        reopened
            .revalidate_shared_experience(&fixture.initial)
            .await
            .is_err()
    );
    reopened
        .revalidate_shared_experience(&admitted)
        .await
        .unwrap();
    assert!(
        reopened
            .grant_shared_experience(&fixture.access, &fixture.request, 0)
            .await
            .is_err()
    );
    reopened
        .revoke_shared_experience(&fixture.access, &fixture.initial)
        .await
        .unwrap();
}

#[tokio::test]
async fn full_active_quota_rejects_new_and_expired_reactivation_but_allows_renewal_and_revoke() {
    let fixture = Fixture::new().await;
    fixture
        .seed(MAX_ACTIVE_POLICY_IDENTITIES as usize - 1, SeedState::Active)
        .await;
    let mut expired = fixture.seed(1, SeedState::Expired).await.remove(0);
    expired.expires_at_unix_seconds = now().unwrap() + 3600;
    let new_request = fixture.request_for("capacity.new");
    for (request, predecessor) in [(&new_request, 0), (&expired, 1)] {
        assert!(matches!(
            fixture.store.grant_shared_experience(&fixture.access, request, predecessor).await,
            Err(CognitiveStoreError::Invalid(message)) if message == "shared use capacity"
        ));
    }
    let mut renewal = fixture.request.clone();
    renewal.expires_at_unix_seconds += 1;
    let renewed = fixture
        .store
        .grant_shared_experience(&fixture.access, &renewal, 1)
        .await
        .unwrap();
    assert_eq!(renewed.policy_revision(), 2);
    assert_eq!(
        fixture
            .store
            .grant_shared_experience(&fixture.access, &renewal, 1)
            .await
            .unwrap(),
        renewed
    );
    fixture
        .store
        .revoke_shared_experience(&fixture.access, &renewed)
        .await
        .unwrap();
    let reactivated = fixture
        .store
        .grant_shared_experience(&fixture.access, &expired, 1)
        .await
        .unwrap();
    assert_eq!(reactivated.policy_revision(), 2);
    assert!(
        fixture
            .store
            .grant_shared_experience(&fixture.access, &new_request, 0)
            .await
            .is_err()
    );
    fixture
        .store
        .revoke_shared_experience(&fixture.access, &reactivated)
        .await
        .unwrap();
    let newcomer = fixture
        .store
        .grant_shared_experience(&fixture.access, &new_request, 0)
        .await
        .unwrap();
    assert!(
        matches!(fixture.store.grant_shared_experience(&fixture.access, &renewal, 3).await,
        Err(CognitiveStoreError::Invalid(message)) if message == "shared use capacity")
    );
    fixture
        .store
        .revoke_shared_experience(&fixture.access, &newcomer)
        .await
        .unwrap();
    let successor = fixture
        .store
        .grant_shared_experience(&fixture.access, &renewal, 3)
        .await
        .unwrap();
    assert_eq!(successor.policy_revision(), 4);
    assert!(
        fixture
            .store
            .revalidate_shared_experience(&renewed)
            .await
            .is_err()
    );
    fixture
        .store
        .revalidate_shared_experience(&successor)
        .await
        .unwrap();
    verify_current_use_heads(&fixture.store.pool).await.unwrap();
    let plan: Vec<String> = sqlx::query("EXPLAIN QUERY PLAN SELECT COUNT(*) FROM (SELECT 1 FROM shared_experience_use_heads WHERE revoked=0 AND expires_at>? LIMIT ?)")
        .bind(now().unwrap()).bind(MAX_ACTIVE_POLICY_IDENTITIES)
        .fetch_all(&fixture.store.pool).await.unwrap().into_iter()
        .map(|row| row.get::<String, _>("detail")).collect();
    assert!(
        plan.iter()
            .any(|step| step.contains("shared_experience_use_active_expiry")),
        "{plan:?}"
    );
}

#[tokio::test]
async fn expired_history_does_not_exhaust_new_identity_admission() {
    let fixture = Fixture::new().await;
    fixture
        .seed(MAX_ACTIVE_POLICY_IDENTITIES as usize, SeedState::Expired)
        .await;
    let request = fixture.request_for("new.after.expired.history");
    let admitted = fixture
        .store
        .grant_shared_experience(&fixture.access, &request, 0)
        .await
        .unwrap();
    fixture
        .store
        .revalidate_shared_experience(&admitted)
        .await
        .unwrap();
    verify_current_use_heads(&fixture.store.pool).await.unwrap();
}

#[tokio::test]
async fn queued_writer_does_not_admit_a_grant_that_expired_while_waiting() {
    use std::future::Future;
    use std::task::Poll;
    use std::time::Duration;
    let fixture = Fixture::new().await;
    let mut request = fixture.request_for("expires.while.writer.queued");
    request.expires_at_unix_seconds = now().unwrap() + 2;
    let blocker = fixture
        .store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    let mut admission = Box::pin(fixture.store.grant_shared_experience(
        &fixture.access,
        &request,
        0,
    ));
    std::future::poll_fn(|cx| {
        assert!(matches!(admission.as_mut().poll(cx), Poll::Pending));
        Poll::Ready(())
    })
    .await;
    assert!(now().unwrap() < request.expires_at_unix_seconds);
    tokio::time::sleep(Duration::from_secs(2)).await;
    blocker.commit().await.unwrap();
    assert!(matches!(admission.await,
        Err(CognitiveStoreError::Invalid(message)) if message == "shared use expiry outside bounded lifetime"));
    assert!(
        fixture
            .store
            .read_shared_experience(
                &request.consumer,
                &policy_id(fixture.store.owner_agent_id(), &request).unwrap(),
                &request.purpose
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn missing_quota_head_is_rejected_on_reopen_even_with_intact_schema() {
    let fixture = Fixture::new().await;
    // Pin fault injection to one transaction: other pool connections must
    // never observe an intermediate schema without its immutability trigger.
    let mut fault = fixture
        .store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    sqlx::query("DROP TRIGGER shared_experience_use_heads_no_delete")
        .execute(&mut *fault)
        .await
        .unwrap();
    sqlx::query("DELETE FROM shared_experience_use_heads")
        .execute(&mut *fault)
        .await
        .unwrap();
    sqlx::raw_sql(
        "CREATE TRIGGER shared_experience_use_heads_no_delete
BEFORE DELETE ON shared_experience_use_heads BEGIN
    SELECT RAISE(ABORT,'shared use predecessors are retained after expiry or revocation');
END;",
    )
    .execute(&mut *fault)
    .await
    .unwrap();
    fault.commit().await.unwrap();
    let remaining: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM shared_experience_use_heads")
        .fetch_one(&fixture.store.pool)
        .await
        .unwrap();
    assert_eq!(
        remaining, 0,
        "corruption fixture must actually remove every head"
    );
    assert!(matches!(
        verify_current_use_heads(&fixture.store.pool).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
    fixture.store.pool.close().await;
    drop(fixture.store);
    assert!(matches!(CognitiveStore::open(&fixture.layout).await,
        Err(CognitiveStoreError::Corrupt(message)) if message.contains("shared use current projection")));
}

#[tokio::test]
async fn v15_upgrade_backfills_all_retained_heads_before_serving() {
    let fixture = Fixture::new().await;
    fixture.seed(2, SeedState::Expired).await;
    fixture.seed(2, SeedState::Revoked).await;
    let expected: Vec<(String, i64, i64, i64)> = sqlx::query_as(
        "SELECT policy_id,revision,revoked,expires_at FROM shared_experience_use_heads ORDER BY policy_id",
    ).fetch_all(&fixture.store.pool).await.unwrap();
    // Reproduce the previously deployed v15 schema and migration ledger while
    // retaining authentic immutable source/grant histories. Normal open must
    // execute v16 and validate the result before exposing the store.
    sqlx::raw_sql(
        "DROP TRIGGER shared_experience_use_project_head;
        DROP TRIGGER shared_experience_use_heads_valid_insert;
        DROP TRIGGER shared_experience_use_heads_valid_update;
        DROP TRIGGER shared_experience_use_heads_no_delete;
        DROP TABLE shared_experience_use_heads;
        DELETE FROM _sqlx_migrations WHERE version=16;",
    )
    .execute(&fixture.store.pool)
    .await
    .unwrap();
    fixture.store.pool.close().await;
    drop(fixture.store);
    let reopened = CognitiveStore::open(&fixture.layout).await.unwrap();
    let actual: Vec<(String, i64, i64, i64)> = sqlx::query_as(
        "SELECT policy_id,revision,revoked,expires_at FROM shared_experience_use_heads ORDER BY policy_id",
    ).fetch_all(&reopened.pool).await.unwrap();
    assert_eq!(actual, expected);
    verify_current_use_heads(&reopened.pool).await.unwrap();
    reopened
        .revalidate_shared_experience(&fixture.initial)
        .await
        .unwrap();
}
