use std::fs;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use crate::CognitiveStore;
use crate::CompactCheckpoint;
use crate::CompactFence;
use crate::CompactLease;
use crate::CompactLossReport;
use crate::CompactParentSnapshot;
use crate::CompactProtectedRef;
use crate::CompactSummaryReceipt;
use crate::H7TrajectoryAppend;
use crate::H7TrajectoryRead;
use crate::H7TrajectoryRecord;
use crate::H7TrajectoryStoreError;
use crate::LocalLeaseState;
use crate::LocalTurnLifecycleBinding;
use crate::append_h7_trajectory_event_bound;
use crate::read_h7_trajectory_bound;
use crate::read_h7_trajectory_bound_for_recovery;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn compact_checkpoint(fence: CompactFence) -> (CompactCheckpoint, CompactParentSnapshot) {
    let snapshot = CompactParentSnapshot::new(
        "ctx:h7-recovery",
        1,
        2,
        1,
        digest("h7-recovery-parent"),
        fence,
    )
    .expect("compact parent snapshot");
    let checkpoint = CompactCheckpoint::new(
        "checkpoint:h7-recovery",
        CompactLease::from_snapshot(snapshot.clone()),
        vec![CompactProtectedRef::new("ref:h7-recovery", "approval", true).expect("protected ref")],
        CompactSummaryReceipt::new(
            digest("summary:h7-recovery"),
            digest("model:h7-recovery"),
            digest("policy:h7-recovery"),
        ),
        CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss report"),
        0,
    )
    .expect("compact checkpoint");
    (checkpoint, snapshot)
}

async fn prepared() -> (
    TempDir,
    CognitiveStore,
    crate::LocalLeaseOutbox,
    crate::LocalCompactExecutor,
    LocalTurnLifecycleBinding,
) {
    let temp = TempDir::new().expect("temp");
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(root).expect("fleet");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000971").expect("owner");
    let store = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .expect("store");
    let fence = CompactFence::new(31, 37, 1, "h7-trajectory-fence").expect("fence");
    let lease = store
        .acquire_host_bound_lease(
            "lease:h7-trajectory",
            fence.authority_epoch,
            fence.owner_epoch,
            fence.generation,
            fence.fencing_token.clone(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock")
                .as_secs()
                + 3_600,
        )
        .await
        .expect("lease")
        .into_handle();
    let executor = store
        .open_local_compact_executor_bound("journal:h7-trajectory", fence, &lease)
        .await
        .expect("executor");
    let binding = LocalTurnLifecycleBinding::from_handles("turn:h7-trajectory", &lease, &executor)
        .expect("binding");
    (temp, store, lease, executor, binding)
}

async fn prepared_with_ttl(
    ttl_seconds: u64,
) -> (
    TempDir,
    CognitiveStore,
    crate::LocalLeaseOutbox,
    crate::LocalCompactExecutor,
    LocalTurnLifecycleBinding,
) {
    let temp = TempDir::new().expect("temp");
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(root).expect("fleet");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000972").expect("owner");
    let store = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .expect("store");
    let fence = CompactFence::new(31, 37, 1, "h7-trajectory-expiring-fence").expect("fence");
    let expires_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
        + ttl_seconds;
    let lease = store
        .acquire_host_bound_lease(
            "lease:h7-trajectory-expiring",
            fence.authority_epoch,
            fence.owner_epoch,
            fence.generation,
            fence.fencing_token.clone(),
            expires_at,
        )
        .await
        .expect("lease")
        .into_handle();
    let executor = store
        .open_local_compact_executor_bound("journal:h7-trajectory-expiring", fence, &lease)
        .await
        .expect("executor");
    let binding =
        LocalTurnLifecycleBinding::from_handles("turn:h7-trajectory-expiring", &lease, &executor)
            .expect("binding");
    (temp, store, lease, executor, binding)
}

fn start_record_for(
    trajectory_id: &str,
    turn_id: &str,
    occurrence_key: &str,
) -> H7TrajectoryRecord {
    H7TrajectoryRecord::turn_start(
        trajectory_id,
        format!("event:{trajectory_id}:1"),
        turn_id,
        occurrence_key,
        digest("state:1"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:start"),
        "{}",
    )
    .expect("start record")
}

fn start_record() -> H7TrajectoryRecord {
    start_record_for(
        "trajectory:h7-trajectory",
        "turn:h7-trajectory",
        "occurrence:h7-trajectory:start",
    )
}

#[test]
fn qualification_terminal_shape_is_exact_and_occurrence_bound() {
    let trajectory_id = "trajectory:h7-shape";
    let turn_id = "turn:h7-shape";
    let start_occurrence_key = "occurrence:h7-shape";
    let terminal_occurrence_key = "occurrence:h7-shape:terminal";
    let start = start_record_for(trajectory_id, turn_id, start_occurrence_key);
    let terminal = H7TrajectoryRecord::terminal(
        trajectory_id,
        2,
        "event:h7-shape:2",
        turn_id,
        terminal_occurrence_key,
        1,
        digest("shape-parent"),
        digest("shape-state:2"),
        digest("shape-policy"),
        digest("shape-model"),
        digest("shape-receipt"),
        "turn_stopped",
        "turn_stopped",
        "{}",
    )
    .expect("terminal record");
    let read = H7TrajectoryRead {
        trajectory_id: trajectory_id.to_string(),
        events: vec![start.clone(), terminal.clone()],
        head_sha256: digest("shape-head"),
    };
    assert!(read.is_complete_qualification_terminal(
        turn_id,
        start_occurrence_key,
        terminal_occurrence_key,
    ));

    let mut wrong_start_occurrence = start_occurrence_key.to_string();
    wrong_start_occurrence.push_str(":wrong");
    assert!(!read.is_complete_qualification_terminal(
        turn_id,
        &wrong_start_occurrence,
        terminal_occurrence_key,
    ));
    let wrong_terminal_occurrence = format!("{terminal_occurrence_key}:wrong");
    assert!(!read.is_complete_qualification_terminal(
        turn_id,
        start_occurrence_key,
        &wrong_terminal_occurrence,
    ));

    let mut mismatched_start = start.clone();
    mismatched_start.occurrence_key.push_str(":wrong");
    let mismatched_start_read = H7TrajectoryRead {
        trajectory_id: trajectory_id.to_string(),
        events: vec![mismatched_start, terminal.clone()],
        head_sha256: digest("shape-head-mismatched-start"),
    };
    assert!(!mismatched_start_read.is_complete_qualification_terminal(
        turn_id,
        start_occurrence_key,
        terminal_occurrence_key,
    ));

    let mut mismatched_terminal = terminal.clone();
    mismatched_terminal.occurrence_key.push_str(":wrong");
    let mismatched_terminal_read = H7TrajectoryRead {
        trajectory_id: trajectory_id.to_string(),
        events: vec![start.clone(), mismatched_terminal],
        head_sha256: digest("shape-head-mismatched-terminal"),
    };
    assert!(
        !mismatched_terminal_read.is_complete_qualification_terminal(
            turn_id,
            start_occurrence_key,
            terminal_occurrence_key,
        )
    );

    let malformed = H7TrajectoryRead {
        trajectory_id: trajectory_id.to_string(),
        events: vec![start, terminal.clone(), terminal],
        head_sha256: digest("shape-head-extra"),
    };
    assert!(!malformed.is_complete_qualification_terminal(
        turn_id,
        start_occurrence_key,
        terminal_occurrence_key,
    ));
}

#[tokio::test]
async fn bound_trajectory_is_append_only_causal_and_reopenable() {
    let (temp, store, lease, executor, binding) = prepared().await;
    let start = start_record();
    let start_result = append_h7_trajectory_event_bound(&lease, &executor, &binding, &start)
        .await
        .expect("append start");
    let H7TrajectoryAppend::Inserted {
        event_sha256: parent,
        ..
    } = start_result
    else {
        panic!("first event must be inserted")
    };
    let terminal = H7TrajectoryRecord::terminal(
        "trajectory:h7-trajectory",
        2,
        "event:h7-trajectory:2",
        "turn:h7-trajectory",
        "occurrence:h7-trajectory:terminal",
        1,
        parent,
        digest("state:2"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:terminal"),
        "stopped",
        "turn_stopped",
        "{\"terminal\":true}",
    )
    .expect("terminal record");
    let terminal_result = append_h7_trajectory_event_bound(&lease, &executor, &binding, &terminal)
        .await
        .expect("append terminal");
    assert!(matches!(
        terminal_result,
        H7TrajectoryAppend::Inserted { .. }
    ));
    let replay = append_h7_trajectory_event_bound(&lease, &executor, &binding, &terminal)
        .await
        .expect("terminal replay");
    let replay_hash = match &replay {
        H7TrajectoryAppend::Replay {
            event_seq: 2,
            event_sha256,
        } => event_sha256.clone(),
        other => panic!("terminal replay expected, got {other:?}"),
    };
    let after_terminal = H7TrajectoryRecord::terminal(
        "trajectory:h7-trajectory",
        3,
        "event:h7-trajectory:3",
        "turn:h7-trajectory",
        "occurrence:h7-trajectory:after-terminal",
        2,
        replay_hash,
        digest("state:3"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:after-terminal"),
        "stopped",
        "turn_stopped_again",
        "{}",
    )
    .expect("after-terminal record");
    assert!(matches!(
        append_h7_trajectory_event_bound(&lease, &executor, &binding, &after_terminal).await,
        Err(H7TrajectoryStoreError::CasConflict(message))
            if message.contains("already terminal")
    ));

    let read = store
        .read_h7_trajectory("trajectory:h7-trajectory")
        .await
        .expect("read trajectory")
        .expect("trajectory exists");
    assert_eq!(read.events, vec![start, terminal]);
    assert_eq!(read.events.len(), 2);

    lease.release().await.expect("release");
    drop(executor);
    drop(lease);
    drop(store);
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000971").expect("owner");
    let fleet = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet reopen");
    let reopened = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .expect("reopen store");
    let reopened_read = reopened
        .read_h7_trajectory("trajectory:h7-trajectory")
        .await
        .expect("reopen read")
        .expect("reopened trajectory");
    assert_eq!(reopened_read.events.len(), 2);
}

#[tokio::test]
async fn recovery_read_observes_expired_terminal_without_appending_h7_rows() {
    let (_temp, _store, lease, executor, binding) = prepared_with_ttl(5).await;
    let trajectory_id = "trajectory:h7-trajectory-expiring";
    let turn_id = "turn:h7-trajectory-expiring";
    let occurrence_key = "occurrence:h7-trajectory-expiring:start";
    let start = start_record_for(trajectory_id, turn_id, occurrence_key);
    let H7TrajectoryAppend::Inserted {
        event_sha256: parent,
        ..
    } = append_h7_trajectory_event_bound(&lease, &executor, &binding, &start)
        .await
        .expect("append start")
    else {
        panic!("first event must be inserted")
    };
    let terminal = H7TrajectoryRecord::terminal(
        trajectory_id,
        2,
        format!("event:{trajectory_id}:2"),
        turn_id,
        format!("{occurrence_key}:terminal"),
        1,
        parent,
        digest("state:2"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:terminal"),
        "turn_stopped",
        "turn_stopped",
        "{\"terminal\":true}",
    )
    .expect("terminal record");
    append_h7_trajectory_event_bound(&lease, &executor, &binding, &terminal)
        .await
        .expect("append terminal");
    let before = lease.snapshot_counts().await.expect("counts before expiry");
    tokio::time::sleep(Duration::from_secs(6)).await;

    let recovery =
        read_h7_trajectory_bound_for_recovery(&lease, &executor, &binding, trajectory_id)
            .await
            .expect("recovery read");
    assert!(recovery.lease_expired);
    assert_eq!(recovery.trajectory.expect("trajectory").events.len(), 2);
    assert_eq!(
        lease.snapshot_counts().await.expect("counts after read"),
        before,
        "recovery read must not append H7/event/outbox rows"
    );

    let rolled_back = lease.expire_lease().await.expect("timeout CAS");
    assert_eq!(rolled_back.state, LocalLeaseState::RolledBack);
    assert_eq!(
        lease
            .snapshot_counts()
            .await
            .expect("counts after timeout")
            .lease_rows,
        before.lease_rows + 1
    );
    let replay = lease
        .expire_lease()
        .await
        .expect("idempotent timeout replay");
    assert_eq!(replay, rolled_back);
}

#[tokio::test]
async fn head_scoped_expired_terminal_gate_survives_store_reopen() {
    let (temp, store, lease, executor, binding) = prepared_with_ttl(5).await;
    let trajectory_id = "trajectory:h7-trajectory-expiring";
    let turn_id = "turn:h7-trajectory-expiring";
    let occurrence_key = "occurrence:h7-trajectory-expiring:start";
    let receipt = match lease
        .admit(occurrence_key, "codex.turn.qualification.start.v1", "{}")
        .await
        .expect("admit")
    {
        crate::LocalAdmission::Queued(receipt) | crate::LocalAdmission::Replay(receipt) => receipt,
    };
    let start = H7TrajectoryRecord::new(
        trajectory_id,
        1,
        format!("event:{trajectory_id}:1"),
        crate::H7TrajectoryEventKind::TurnStart,
        turn_id,
        occurrence_key,
        None,
        None,
        digest("state:1"),
        digest("policy:none"),
        digest("model:none"),
        crate::h7_trajectory_local_receipt_digest(&receipt),
        "turn_started",
        0,
        true,
        "{}",
        "not_applicable",
    )
    .expect("start record");
    let H7TrajectoryAppend::Inserted {
        event_sha256: parent,
        ..
    } = append_h7_trajectory_event_bound(&lease, &executor, &binding, &start)
        .await
        .expect("append start")
    else {
        panic!("first event must be inserted")
    };
    let terminal = H7TrajectoryRecord::terminal(
        trajectory_id,
        2,
        format!("event:{trajectory_id}:2"),
        turn_id,
        format!("{occurrence_key}:terminal"),
        1,
        parent,
        digest("state:2"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:terminal"),
        "turn_stopped",
        "turn_stopped",
        "{\"terminal\":true}",
    )
    .expect("terminal record");
    append_h7_trajectory_event_bound(&lease, &executor, &binding, &terminal)
        .await
        .expect("append terminal");
    let (checkpoint, snapshot) = compact_checkpoint(binding.fence.clone());
    executor
        .append_intent("op:h7-recovery-compact", &checkpoint, &snapshot)
        .await
        .expect("append bound compact witness");
    let expiry = lease
        .binding()
        .expect("binding")
        .lease_expires_at_unix_seconds;
    drop(binding);
    drop(executor);
    drop(lease);
    drop(store);
    tokio::time::sleep(Duration::from_secs(6)).await;

    let owner = AgentId::parse("00000000-0000-4000-8000-000000000972").expect("owner");
    let fleet = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("reopen fleet");
    let reopened = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .expect("reopen store");
    let inspected = reopened
        .inspect_local_lease_head("lease:h7-trajectory-expiring")
        .await
        .expect("inspect head");
    let head = inspected.head.expect("expired active head");
    assert_eq!(
        inspected.disposition,
        crate::LocalLeaseHeadDisposition::ExpiredActive
    );
    assert_eq!(head.lease_expires_at_unix_seconds, Some(expiry));
    let wrong_journal = crate::inspect_expired_terminal_h7(
        &reopened,
        &head,
        "journal:h7-trajectory-expiring:wrong",
        trajectory_id,
        turn_id,
        occurrence_key,
    )
    .await
    .expect_err("a bound compact journal must not be replaceable by a guessed id");
    assert!(matches!(
        wrong_journal,
        H7TrajectoryStoreError::StaleFence(message)
            if message.contains("compact journal identity mismatch")
    ));
    let witness = crate::inspect_expired_terminal_h7(
        &reopened,
        &head,
        "journal:h7-trajectory-expiring",
        trajectory_id,
        turn_id,
        occurrence_key,
    )
    .await
    .expect("head-scoped H7 gate")
    .expect("complete terminal witness");
    assert_eq!(witness.terminal_event_seq, 2);
    let recovered = reopened
        .reopen_host_bound_lease(head, 31, 37, expiry)
        .await
        .expect("reopen expired head for timeout CAS");
    let rolled_back = recovered.expire_lease().await.expect("timeout CAS");
    assert_eq!(rolled_back.state, LocalLeaseState::RolledBack);
}

#[tokio::test]
async fn bound_read_rejects_terminal_trajectory_from_prior_lease_head() {
    let (_temp, store, lease, executor, binding) = prepared().await;
    let start = start_record();
    let H7TrajectoryAppend::Inserted {
        event_sha256: parent,
        ..
    } = append_h7_trajectory_event_bound(&lease, &executor, &binding, &start)
        .await
        .expect("append start")
    else {
        panic!("first event must be inserted")
    };
    let terminal = H7TrajectoryRecord::terminal(
        "trajectory:h7-trajectory",
        2,
        "event:h7-trajectory:2",
        "turn:h7-trajectory",
        "occurrence:h7-trajectory:terminal",
        1,
        parent,
        digest("state:2"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:terminal"),
        "stopped",
        "turn_stopped",
        "{}",
    )
    .expect("terminal record");
    append_h7_trajectory_event_bound(&lease, &executor, &binding, &terminal)
        .await
        .expect("append terminal");
    let released = lease.release().await.expect("release generation one");

    let next = store
        .acquire_host_bound_lease_after_head(
            "lease:h7-trajectory",
            released,
            31,
            38,
            2,
            "h7-trajectory-fence-2",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock")
                .as_secs()
                + 3_600,
        )
        .await
        .expect("acquire generation two")
        .into_handle();
    let fence = CompactFence::new(31, 38, 2, "h7-trajectory-fence-2").expect("fence");
    let next_executor = store
        .open_local_compact_executor_bound("journal:h7-trajectory-2", fence, &next)
        .await
        .expect("executor generation two");
    let next_binding =
        LocalTurnLifecycleBinding::from_handles("turn:h7-trajectory", &next, &next_executor)
            .expect("binding generation two");
    let error = read_h7_trajectory_bound(
        &next,
        &next_executor,
        &next_binding,
        "trajectory:h7-trajectory",
    )
    .await
    .expect_err("prior terminal head must not be reused by a new generation");
    assert!(matches!(
        error,
        H7TrajectoryStoreError::StaleFence(message)
            if message.contains("does not match the current lifecycle binding")
    ));
}

#[tokio::test]
async fn trajectory_rejects_mixed_generation_event_chain() {
    let (_temp, store, lease, executor, binding) = prepared().await;
    let start = start_record();
    let H7TrajectoryAppend::Inserted {
        event_sha256: parent,
        ..
    } = append_h7_trajectory_event_bound(&lease, &executor, &binding, &start)
        .await
        .expect("append start")
    else {
        panic!("first event must be inserted")
    };
    let released = lease.release().await.expect("release generation one");
    let next = store
        .acquire_host_bound_lease_after_head(
            "lease:h7-trajectory",
            released,
            31,
            38,
            2,
            "h7-trajectory-fence-2",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock")
                .as_secs()
                + 3_600,
        )
        .await
        .expect("acquire generation two")
        .into_handle();
    let fence = CompactFence::new(31, 38, 2, "h7-trajectory-fence-2").expect("fence");
    let next_executor = store
        .open_local_compact_executor_bound("journal:h7-trajectory-2", fence, &next)
        .await
        .expect("executor generation two");
    let next_binding =
        LocalTurnLifecycleBinding::from_handles("turn:h7-trajectory", &next, &next_executor)
            .expect("binding generation two");
    let terminal = H7TrajectoryRecord::terminal(
        "trajectory:h7-trajectory",
        2,
        "event:h7-trajectory:2",
        "turn:h7-trajectory",
        "occurrence:h7-trajectory:terminal",
        1,
        parent,
        digest("state:2"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:terminal"),
        "stopped",
        "turn_stopped",
        "{}",
    )
    .expect("terminal record");
    let error = append_h7_trajectory_event_bound(&next, &next_executor, &next_binding, &terminal)
        .await
        .expect_err("one trajectory cannot cross lease generations");
    assert!(matches!(
        error,
        H7TrajectoryStoreError::Corrupt(message)
            if message.contains("does not match the current lifecycle binding")
    ));
    next.release().await.expect("release generation two");
}

#[tokio::test]
async fn trajectory_rejects_gap_parent_policy_and_stale_binding() {
    let (_temp, store, lease, executor, binding) = prepared().await;
    let start = start_record();
    append_h7_trajectory_event_bound(&lease, &executor, &binding, &start)
        .await
        .expect("start");
    let mut gap = H7TrajectoryRecord::terminal(
        "trajectory:h7-trajectory",
        3,
        "event:h7-trajectory:3",
        "turn:h7-trajectory",
        "occurrence:h7-trajectory:gap",
        2,
        digest("wrong-parent"),
        digest("state:3"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:gap"),
        "stopped",
        "turn_stopped",
        "{}",
    )
    .expect("gap record");
    assert!(matches!(
        append_h7_trajectory_event_bound(&lease, &executor, &binding, &gap).await,
        Err(H7TrajectoryStoreError::CasConflict(_))
    ));
    gap.propensity_json = Some("{}".to_string());
    assert!(matches!(
        gap.validate(),
        Err(H7TrajectoryStoreError::PolicyActionNotQualified)
    ));
    lease.release().await.expect("release");
    let stale = H7TrajectoryRecord::terminal(
        "trajectory:h7-trajectory",
        2,
        "event:h7-trajectory:2",
        "turn:h7-trajectory",
        "occurrence:h7-trajectory:stale",
        1,
        digest("parent"),
        digest("state:2"),
        digest("policy:none"),
        digest("model:none"),
        digest("receipt:stale"),
        "stopped",
        "turn_stopped",
        "{}",
    )
    .expect("stale record");
    assert!(matches!(
        append_h7_trajectory_event_bound(&lease, &executor, &binding, &stale).await,
        Err(H7TrajectoryStoreError::Binding(_))
            | Err(H7TrajectoryStoreError::StaleFence(_))
            | Err(H7TrajectoryStoreError::Lease(_))
    ));
    assert!(
        store
            .read_h7_trajectory("trajectory:h7-trajectory")
            .await
            .expect("read after stale")
            .is_some()
    );
}

#[test]
fn trajectory_record_rejects_non_observation_flags() {
    let mut record = start_record();
    record.production_caller = true;
    assert!(matches!(
        record.validate(),
        Err(H7TrajectoryStoreError::BoundaryViolation)
    ));

    let feedback = H7TrajectoryRecord::new(
        "trajectory:h7-feedback",
        2,
        "event:h7-feedback:2",
        crate::H7TrajectoryEventKind::Feedback,
        "turn:h7-feedback",
        "occurrence:h7-feedback",
        Some(1),
        Some(digest("feedback-parent")),
        digest("state:feedback"),
        digest("policy:feedback"),
        digest("model:feedback"),
        digest("receipt:feedback"),
        "feedback",
        0,
        true,
        "{}",
        "not_applicable",
    )
    .expect_err("untyped feedback must stay outside the local observation slice");
    assert!(matches!(
        feedback,
        H7TrajectoryStoreError::PolicyActionNotQualified
    ));

    let mut rewarded = start_record();
    rewarded.reward_bps = 1;
    assert!(matches!(
        rewarded.validate(),
        Err(H7TrajectoryStoreError::PolicyActionNotQualified)
    ));
}
