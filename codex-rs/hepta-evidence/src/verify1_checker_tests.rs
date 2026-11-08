use std::path::Path;

use codex_state::SqliteConfig;
use sqlx::Connection;
use sqlx::SqliteConnection;

use crate::Verify1FixtureGoal;
use crate::Verify1Scope;
use crate::Verify1Verdict;
use crate::check_verify1_sqlite;
use crate::verify1_report::python_integer_json;

// Schema matches experiments/verification_cell_verify1/runtime.py. The real
// Python producer is exercised separately when its frozen capsule is available.
async fn fixture(path: &Path) -> (SqliteConnection, Verify1FixtureGoal, Verify1Scope) {
    let config = SqliteConfig::from_sqlite_home(path.parent().unwrap().try_into().unwrap());
    let pool = config.open_durable_evidence_pool(path).await.unwrap();
    let mut db = pool.acquire().await.unwrap().detach();
    pool.close().await;
    sqlx::raw_sql("CREATE TABLE meta(epoch INTEGER NOT NULL,tick INTEGER NOT NULL);
        CREATE TABLE resources(name TEXT PRIMARY KEY,value INTEGER NOT NULL);
        CREATE TABLE intents(operation_id TEXT PRIMARY KEY,request TEXT NOT NULL,tick INTEGER NOT NULL,finished INTEGER NOT NULL,ack INTEGER NOT NULL);
        CREATE TABLE readbacks(operation_id TEXT PRIMARY KEY,epoch INTEGER NOT NULL,evidence TEXT NOT NULL);
        CREATE TABLE journal(sequence INTEGER PRIMARY KEY,kind TEXT,payload TEXT);
        CREATE TABLE accepted(singleton INTEGER PRIMARY KEY CHECK(singleton=1),epoch INTEGER,goal TEXT,evidence TEXT);
        INSERT INTO meta VALUES(3,3); INSERT INTO resources VALUES('left',7),('right',9);")
        .execute(&mut db).await.unwrap();
    let goal = Verify1FixtureGoal {
        task_id: "task:猴".to_string(),
        left: 7,
        right: 9,
    };
    let raw = String::from_utf8(python_integer_json(&goal).unwrap()).unwrap();
    sqlx::query("INSERT INTO journal(kind,payload) VALUES('goal',?)")
        .bind(raw)
        .execute(&mut db)
        .await
        .unwrap();
    for tick in 1..=3 {
        sqlx::query("INSERT INTO intents VALUES(?,?,?,1,1)")
            .bind(format!("{}/step/{tick}", goal.task_id))
            .bind("a".repeat(64))
            .bind(tick)
            .execute(&mut db)
            .await
            .unwrap();
    }
    let scope = Verify1Scope {
        task_id: goal.task_id.clone(),
        attempt_id: "attempt:native".to_string(),
        subject_sha256: goal.subject_sha256().unwrap().as_str().to_string(),
        state_version: 3,
        domain: "sqlite_two_field_engineering_fixture_v1".to_string(),
        event: "terminal_goal_value_error".to_string(),
        horizon_start: 4,
        horizon_end: 4,
    };
    (db, goal, scope)
}

#[tokio::test]
async fn recomputes_actual_semantics_even_when_foreign_journal_claims_proved() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("fixture.sqlite");
    let (mut db, goal, scope) = fixture(&path).await;
    let good = check_verify1_sqlite(&path, &goal, &scope).await.unwrap();
    assert_eq!(
        (
            good.verdict,
            good.scope.clone(),
            good.residual_obligations.clone()
        ),
        (Verify1Verdict::Proved, scope.clone(), vec![])
    );
    sqlx::query("INSERT INTO journal(kind,payload) VALUES('claimed_receipt',?)")
        .bind(serde_json::to_string(&good).unwrap())
        .execute(&mut db)
        .await
        .unwrap();
    sqlx::query("UPDATE resources SET value=10 WHERE name='right'")
        .execute(&mut db)
        .await
        .unwrap();
    let wrong = check_verify1_sqlite(&path, &goal, &scope).await.unwrap();
    assert_eq!(
        (wrong.verdict, wrong.reason.as_str()),
        (Verify1Verdict::Refuted, "goal_values_mismatch")
    );
    assert_ne!(wrong.evidence_sha256, good.evidence_sha256);
    sqlx::query("DELETE FROM resources WHERE name='right'")
        .execute(&mut db)
        .await
        .unwrap();
    assert_eq!(
        check_verify1_sqlite(&path, &goal, &scope)
            .await
            .unwrap()
            .verdict,
        Verify1Verdict::Refuted
    );
    let accepted: (i64,) = sqlx::query_as("SELECT count(*) FROM accepted")
        .fetch_one(&mut db)
        .await
        .unwrap();
    assert_eq!(accepted, (0,));
    db.close().await.unwrap();
}

#[tokio::test]
async fn binds_original_goal_version_and_frontier() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("fixture.sqlite");
    let (mut db, goal, scope) = fixture(&path).await;
    let mut other_goal = goal.clone();
    other_goal.right = 10;
    let mut other_scope = scope.clone();
    other_scope.subject_sha256 = other_goal.subject_sha256().unwrap().as_str().to_string();
    assert!(
        check_verify1_sqlite(&path, &other_goal, &other_scope)
            .await
            .is_err()
    );
    other_scope = scope.clone();
    other_scope.state_version = 2;
    let stale = check_verify1_sqlite(&path, &goal, &other_scope)
        .await
        .unwrap();
    assert_eq!(
        (
            stale.verdict,
            stale.reason.as_str(),
            stale.scope.state_version
        ),
        (Verify1Verdict::Unknown, "pinned_state_version_mismatch", 3)
    );
    sqlx::query("UPDATE meta SET tick=2")
        .execute(&mut db)
        .await
        .unwrap();
    assert_eq!(
        check_verify1_sqlite(&path, &goal, &scope)
            .await
            .unwrap()
            .reason,
        "state_frontier_mismatch"
    );
    other_scope = scope.clone();
    other_scope.event = "other_event".to_string();
    assert!(
        check_verify1_sqlite(&path, &goal, &other_scope)
            .await
            .is_err()
    );
    sqlx::raw_sql("UPDATE meta SET epoch=1,tick=1; DELETE FROM intents WHERE tick>1; DELETE FROM resources WHERE name='right';")
        .execute(&mut db).await.unwrap();
    let mut prefix_scope = scope.clone();
    prefix_scope.horizon_start = 1;
    prefix_scope.state_version = 1;
    let prefix = check_verify1_sqlite(&path, &goal, &prefix_scope)
        .await
        .unwrap();
    assert_eq!(
        (
            prefix.verdict,
            prefix.property.as_str(),
            prefix.checked_step
        ),
        (
            Verify1Verdict::Proved,
            "fixture_prefix_goal_and_owner_readback_at_snapshot",
            1
        )
    );
    prefix_scope.horizon_start = 4;
    assert_eq!(
        check_verify1_sqlite(&path, &goal, &prefix_scope)
            .await
            .unwrap()
            .verdict,
        Verify1Verdict::Unknown
    );
    db.close().await.unwrap();
}

#[tokio::test]
async fn missing_ack_requires_current_owner_readback_without_replaying_or_accepting() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("fixture.sqlite");
    let (mut db, goal, scope) = fixture(&path).await;
    sqlx::query("UPDATE intents SET ack=0 WHERE tick=2")
        .execute(&mut db)
        .await
        .unwrap();
    let missing = check_verify1_sqlite(&path, &goal, &scope).await.unwrap();
    assert_eq!(
        (missing.verdict, missing.reason.as_str()),
        (Verify1Verdict::Unknown, "missing_ack_requires_readback")
    );
    sqlx::query("INSERT INTO readbacks VALUES(?,2,?)")
        .bind(format!("{}/step/2", goal.task_id))
        .bind("b".repeat(64))
        .execute(&mut db)
        .await
        .unwrap();
    assert_eq!(
        check_verify1_sqlite(&path, &goal, &scope)
            .await
            .unwrap()
            .verdict,
        Verify1Verdict::Unknown
    );
    sqlx::query("UPDATE readbacks SET epoch=3")
        .execute(&mut db)
        .await
        .unwrap();
    assert_eq!(
        check_verify1_sqlite(&path, &goal, &scope)
            .await
            .unwrap()
            .verdict,
        Verify1Verdict::Proved
    );
    let state: (i64,i64,i64,i64) = sqlx::query_as("SELECT epoch,tick,(SELECT sum(ack) FROM intents),(SELECT count(*) FROM accepted) FROM meta")
        .fetch_one(&mut db).await.unwrap();
    assert_eq!(state, (3, 3, 2, 0));
    db.close().await.unwrap();
}

#[tokio::test]
async fn malformed_or_absent_fixture_fails_without_creation() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("fixture.sqlite");
    let (mut db, goal, scope) = fixture(&path).await;
    sqlx::query("UPDATE intents SET finished=2 WHERE tick=2")
        .execute(&mut db)
        .await
        .unwrap();
    assert!(check_verify1_sqlite(&path, &goal, &scope).await.is_err());
    let absent = temp.path().join("absent.sqlite");
    assert!(check_verify1_sqlite(&absent, &goal, &scope).await.is_err());
    assert!(!absent.exists());
    db.close().await.unwrap();
}
