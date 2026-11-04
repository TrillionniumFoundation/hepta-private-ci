//! Exercise the ordinary owner while another connection reserves its writer.
//! No provider is contacted and the original fence and receipt checks remain.

use super::*;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowTransition;
use pretty_assertions::assert_eq;
use std::time::Duration;

#[tokio::test]
async fn step_write_waits_for_reservation_while_ordinary_reads_remain_available() {
    let fixture = Fixture::new();
    let (store, owner, intent, payload) = prepared_store(&fixture).await;
    let prepared = store
        .prepare_taskflow_step(
            "step-run", "work", /*attempt*/ 1, &owner, &intent, &payload,
            "contention-prepare", /*now_ms*/ 21,
        )
        .await
        .expect("prepare step before contention");
    let sqlite_home =
        AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root()).expect("sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("independent writer connection");
    let reservation = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("reserve independent writer");
    let claim = store.claim_taskflow_step(
        "step-run", "work", /*attempt*/ 1, &owner, &intent, &payload,
        "contention-claim", /*now_ms*/ 22,
    );
    tokio::pin!(claim);
    // Poll the actual mutation with a live writer reservation. A deferred
    // read/upgrade returns Unavailable immediately; an immediate write waits
    // without replacing the original future or replaying the command.
    let waiting = tokio::time::timeout(Duration::from_millis(100), &mut claim).await;
    assert!(waiting.is_err(), "writer returned before release: {waiting:?}");
    let before_release = tokio::time::timeout(
        Duration::from_secs(2),
        store.read_taskflow_step("step-run", "work", /*attempt*/ 1, &owner),
    )
    .await
    .expect("ordinary read must not need the writer reservation")
    .expect("read prepared step")
    .expect("prepared step exists");
    assert_eq!(before_release, prepared.receipt);
    reservation.commit().await.expect("release independent writer");
    let claimed = tokio::time::timeout(Duration::from_secs(5), &mut claim)
        .await
        .expect("claim completes after release")
        .expect("same claim succeeds without retry");
    assert_eq!(claimed.status, TaskFlowStepCommandStatus::Applied);
    assert_eq!(claimed.receipt.state, TaskFlowStepState::Claimed);
    assert_eq!(claimed.receipt.event_seq, prepared.receipt.event_seq + 1);
    let replay = store
        .claim_taskflow_step(
            "step-run", "work", /*attempt*/ 1, &owner, &intent, &payload,
            "contention-claim", /*now_ms*/ 22,
        )
        .await
        .expect("exact replay after release");
    assert_eq!(replay.status, TaskFlowStepCommandStatus::AlreadyApplied);
    assert_eq!(replay.receipt, claimed.receipt);
    pool.close().await;
    store.close().await;
}

#[tokio::test]
async fn run_write_waits_for_reservation_while_ordinary_reads_remain_available() {
    let fixture = Fixture::new();
    let (store, owner, _, _) = prepared_store(&fixture).await;
    let before = store
        .taskflow_run("step-run")
        .await
        .expect("read running owner")
        .expect("run exists");
    let command = TaskFlowCommand::new(
        "step-run", "contention-quarantine", owner, before.revision,
        TaskFlowTransition::Indeterminate {
            reason: "known provider outcome remains unresolved".into(),
        },
        /*now_ms*/ 23,
    )
    .expect("bounded ordinary owner command");
    let sqlite_home =
        AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root()).expect("sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("independent writer connection");
    let reservation = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("reserve independent writer");
    let apply = store.apply_taskflow_command(&command);
    tokio::pin!(apply);
    let waiting = tokio::time::timeout(Duration::from_millis(100), &mut apply).await;
    assert!(waiting.is_err(), "writer returned before release: {waiting:?}");
    let before_release = tokio::time::timeout(Duration::from_secs(2), store.taskflow_run("step-run"))
        .await
        .expect("ordinary run read must remain available")
        .expect("read original run")
        .expect("original run exists");
    assert_eq!(before_release, before);
    reservation.commit().await.expect("release independent writer");
    tokio::time::timeout(Duration::from_secs(5), &mut apply)
        .await
        .expect("command completes after release")
        .expect("same owner command succeeds without retry");
    let after = store
        .taskflow_run("step-run")
        .await
        .expect("read committed owner command")
        .expect("run still exists");
    assert_eq!(after.revision, before.revision + 1);
    assert_eq!(after.state, codex_hepta_automation::TaskFlowRunState::Indeterminate);
    store
        .apply_taskflow_command(&command)
        .await
        .expect("exact command replay succeeds");
    assert_eq!(
        store.taskflow_run("step-run").await.expect("read after replay"),
        Some(after),
    );
    pool.close().await;
    store.close().await;
}
