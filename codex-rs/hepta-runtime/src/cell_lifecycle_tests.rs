use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_plasticity::build_writer_handoff_plan_v1;
use codex_hepta_types::Generation;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

use super::*;

#[path = "cell_lifecycle_state_tests.rs"]
mod state_closure_tests;

// Qualification fixtures only: physical independent custody is not modeled.
// They cannot satisfy the unchanged public Control lifecycle admission gate.
#[derive(Clone)]
struct Witness {
    state: Arc<Mutex<RuntimeCellLifecycleAnchorV1>>,
    refuse_once: Arc<AtomicBool>,
}

impl Witness {
    fn new(agent: &StableId) -> Self {
        Self {
            state: Arc::new(Mutex::new(RuntimeCellLifecycleAnchorV1 {
                scope_digest: runtime_cell_lifecycle_journal_scope_v1(agent),
                writer_epoch: 1, sequence: 0, head: Digest32::ZERO,
            })),
            refuse_once: Arc::new(AtomicBool::new(false)),
        }
    }
}

impl RuntimeCellLifecycleAnchorStoreV1 for Witness {
    fn current(&self) -> Result<RuntimeCellLifecycleAnchorV1, RuntimeCellLifecycleError> {
        Ok(*self.state.lock().map_err(|_| RuntimeCellLifecycleError::Unavailable)?)
    }
    fn compare_and_swap(
        &mut self,
        expected: RuntimeCellLifecycleAnchorV1,
        next: RuntimeCellLifecycleAnchorV1,
    ) -> Result<(), RuntimeCellLifecycleError> {
        if self.refuse_once.swap(false, Ordering::SeqCst) {
            return Err(RuntimeCellLifecycleError::Unavailable);
        }
        let mut state = self.state.lock().map_err(|_| RuntimeCellLifecycleError::Unavailable)?;
        if *state != expected {
            return Err(RuntimeCellLifecycleError::Conflict);
        }
        *state = next;
        Ok(())
    }
}

struct Observer;
impl RuntimeCellLifecycleObserverV1 for Observer {
    fn authenticate(
        &self,
        plan: &RuntimeCellLifecyclePlanV1,
        observation: &RuntimeCellLifecycleObservationV1,
    ) -> Result<Digest32, RuntimeCellLifecycleError> {
        if observation.native_receipt != d("native-confirmation").to_string() {
            return Err(RuntimeCellLifecycleError::Authentication);
        }
        let bytes = serde_json::to_vec(observation).map_err(unavailable)?;
        Ok(Digest32::of_parts(&[plan.observer_trust.as_array(), &bytes]))
    }
}

struct RevokedObserver;
impl RuntimeCellLifecycleObserverV1 for RevokedObserver {
    fn authenticate(
        &self,
        _: &RuntimeCellLifecyclePlanV1,
        _: &RuntimeCellLifecycleObservationV1,
    ) -> Result<Digest32, RuntimeCellLifecycleError> {
        Err(RuntimeCellLifecycleError::Authentication)
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn plan(change: RuntimeCellStructuralChangeV1) -> RuntimeCellLifecyclePlanV1 {
    let (predecessors, successors) = match change {
        RuntimeCellStructuralChangeV1::Split => {
            (vec![id("cell:a")], vec![id("cell:b"), id("cell:c")])
        }
        RuntimeCellStructuralChangeV1::Merge => {
            (vec![id("cell:a"), id("cell:b")], vec![id("cell:c")])
        }
        RuntimeCellStructuralChangeV1::Replace => (vec![id("cell:a")], vec![id("cell:b")]),
        RuntimeCellStructuralChangeV1::Retire => (vec![id("cell:a")], vec![]),
    };
    RuntimeCellLifecyclePlanV1 {
        operation_id: id("operation:split"), agent_id: id("agent:a"), cns_id: id("cns:a"),
        observer_id: id("observer:independent"), observer_trust: d("observer-trust"),
        principal_scope: d("principal"), change, predecessors, successors,
        predecessor_generation: Generation::new(/*value*/ 1).unwrap(),
        successor_generation: Generation::new(/*value*/ 2).unwrap(),
        predecessor_topology: d("old-topology"), successor_topology: d("new-topology"),
        predecessor_state_root: d("old-state"), successor_state_root: d("new-state"),
        successor_bundle: d("new-bundle"),
        handoff: build_writer_handoff_plan_v1(
            id("module:a"), id("writer:old"), id("writer:new"),
            /*predecessor_writer_fence*/ 1, /*successor_writer_fence*/ 2,
            d("old-topology"), d("migration"), d("rollback"), d("acknowledgement"),
        ).unwrap(),
        recovery_of: None, created_at_ms: 100, deadline_ms: 1000,
    }
}

fn observation(
    plan: &RuntimeCellLifecyclePlanV1,
    intent: &RuntimeCellLifecycleIntentV1,
    at: u64,
) -> RuntimeCellLifecycleObservationV1 {
    let stage = intent.stage.code();
    let published = stage >= RuntimeCellLifecycleStageV1::Publish.code();
    let transferred = stage >= RuntimeCellLifecycleStageV1::TransferState.code();
    RuntimeCellLifecycleObservationV1 {
        agent_id: plan.agent_id.to_string(), operation_id: plan.operation_id.to_string(),
        observer_id: plan.observer_id.to_string(), observer_trust: plan.observer_trust.to_string(),
        plan_digest: intent.plan_digest.to_string(), stage: intent.stage,
        semantic_operation: intent.semantic_operation.to_string(),
        prepared_revision: intent.prepared_revision, attempt_digest: intent.attempt_digest.to_string(),
        outcome: RuntimeCellLifecycleNativeOutcomeV1::Applied,
        admission_closed: intent.stage != RuntimeCellLifecycleStageV1::Resume,
        inflight: 0, unknown_effects: 0,
        writer_fence: if stage >= RuntimeCellLifecycleStageV1::FenceWriters.code() { 2 } else { 1 },
        generation: if published { 2 } else { 1 },
        topology: if published { plan.successor_topology } else { plan.predecessor_topology }.to_string(),
        state_root: if transferred { plan.successor_state_root } else { plan.predecessor_state_root }.to_string(),
        bundle: if transferred { plan.successor_bundle } else { d("old-bundle") }.to_string(),
        native_receipt: d("native-confirmation").to_string(), observed_at_ms: at,
    }
}

#[expect(
    clippy::disallowed_methods,
    reason = "isolated lifecycle tests explicitly create only temporary SQLite owner fixtures"
)]
async fn pool(path: &std::path::Path) -> SqlitePool {
    SqlitePoolOptions::new().max_connections(2).connect_with(
        SqliteConnectOptions::new().filename(path).create_if_missing(true),
    ).await.unwrap()
}

#[tokio::test]
async fn split_merge_replace_retire_reopen_each_phase_without_reissuing_intent() {
    for change in [
        RuntimeCellStructuralChangeV1::Split, RuntimeCellStructuralChangeV1::Merge,
        RuntimeCellStructuralChangeV1::Replace, RuntimeCellStructuralChangeV1::Retire,
    ] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("shared-owner.sqlite");
        let plan = plan(change);
        let witness = Witness::new(&plan.agent_id);
        let mut journal = RuntimeCellLifecycleJournalV1::attach(
            pool(&path).await, plan.agent_id.clone(), /*writer_epoch*/ 1,
            witness.clone(), /*max_events*/ 100,
        ).await.unwrap();
        let mut snapshot = journal.create(&plan, /*now_ms*/ 100).await.unwrap();
        let mut now = 101;
        while snapshot.stage().is_some() {
            let intent = journal.prepare_next(&plan, snapshot.revision(), now).await.unwrap();
            assert_eq!(intent.authority, codex_hepta_types::AuthorityPosture::DENY_ALL);
            let pending = journal.read(&plan).await.unwrap().unwrap();
            assert_eq!(
                journal.prepare_next(&plan, pending.revision(), now).await.unwrap_err(),
                RuntimeCellLifecycleError::ReconciliationRequired,
            );
            journal.pool.close().await;
            drop(journal);
            journal = RuntimeCellLifecycleJournalV1::attach(
                pool(&path).await, plan.agent_id.clone(), /*writer_epoch*/ 1,
                witness.clone(), /*max_events*/ 100,
            ).await.unwrap();
            assert_eq!(journal.pending_intent(&plan).await.unwrap(), Some(intent.clone()));
            let observed = observation(&plan, &intent, now);
            snapshot = journal.record_observation(
                &plan, pending.revision(), observed.clone(), &Observer,
            ).await.unwrap();
            assert_eq!(journal.read_observation(&plan, intent.stage).await.unwrap(), Some(observed));
            now += 1;
        }
        assert!(snapshot.completed());
        assert_eq!(snapshot.revision(), 14);
        assert_eq!(witness.current().unwrap().sequence, 15);
        assert_eq!(journal.read(&plan).await.unwrap(), Some(snapshot));
    }
}

#[tokio::test]
async fn lost_anchor_ack_recovers_original_pending_operation_without_dispatch() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("owner.sqlite");
    let plan = plan(RuntimeCellStructuralChangeV1::Split);
    let witness = Witness::new(&plan.agent_id);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(
        pool(&path).await, plan.agent_id.clone(), /*writer_epoch*/ 1,
        witness.clone(), /*max_events*/ 100,
    ).await.unwrap();
    let snapshot = journal.create(&plan, /*now_ms*/ 100).await.unwrap();
    witness.refuse_once.store(true, Ordering::SeqCst);
    assert_eq!(
        journal.prepare_next(&plan, snapshot.revision(), /*now_ms*/ 101).await.unwrap_err(),
        RuntimeCellLifecycleError::CommitUncertain,
    );
    assert_eq!(journal.read(&plan).await.unwrap_err(), RuntimeCellLifecycleError::CommitUncertain);
    journal.pool.close().await;
    drop(journal);
    let recovered = RuntimeCellLifecycleJournalV1::recover(
        pool(&path).await, &plan, /*writer_epoch*/ 1, witness, /*max_events*/ 100, &Observer,
    ).await.unwrap();
    assert_eq!(
        recovered.pending_intent(&plan).await.unwrap(),
        Some(intent(&plan, RuntimeCellLifecycleStageV1::StopAdmission, 1).unwrap()),
    );
}

#[tokio::test]
async fn drain_unknowns_bad_provenance_and_stale_writer_cannot_advance() {
    let directory = tempfile::tempdir().unwrap();
    let plan = plan(RuntimeCellStructuralChangeV1::Merge);
    let witness = Witness::new(&plan.agent_id);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(
        pool(&directory.path().join("owner.sqlite")).await,
        plan.agent_id.clone(), /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100,
    ).await.unwrap();
    journal.create(&plan, /*now_ms*/ 100).await.unwrap();
    let stop = journal.prepare_next(&plan, /*expected_revision*/ 0, /*now_ms*/ 101).await.unwrap();
    let mut bad = observation(&plan, &stop, /*at*/ 102);
    bad.native_receipt = d("self-asserted").to_string();
    assert_eq!(
        journal.record_observation(&plan, /*expected_revision*/ 1, bad, &Observer).await.unwrap_err(),
        RuntimeCellLifecycleError::Authentication,
    );
    journal.record_observation(
        &plan, /*expected_revision*/ 1, observation(&plan, &stop, /*at*/ 102), &Observer,
    ).await.unwrap();
    let drain = journal.prepare_next(&plan, /*expected_revision*/ 2, /*now_ms*/ 103).await.unwrap();
    let before = journal.read(&plan).await.unwrap();
    let mut unresolved = observation(&plan, &drain, /*at*/ 104);
    unresolved.unknown_effects = 1;
    assert_eq!(
        journal.record_observation(&plan, /*expected_revision*/ 3, unresolved, &Observer).await.unwrap_err(),
        RuntimeCellLifecycleError::InvalidObservation,
    );
    assert_eq!(journal.read(&plan).await.unwrap(), before);
    witness.state.lock().unwrap().writer_epoch = 2;
    assert_eq!(journal.read(&plan).await.unwrap_err(), RuntimeCellLifecycleError::StaleWriter);
}

#[tokio::test]
async fn acknowledged_source_rollback_and_cross_agent_anchor_are_detected() {
    let directory = tempfile::tempdir().unwrap();
    let pool = pool(&directory.path().join("owner.sqlite")).await;
    let plan = plan(RuntimeCellStructuralChangeV1::Replace);
    let witness = Witness::new(&plan.agent_id);
    let wrong = RuntimeCellLifecycleJournalV1::attach(
        pool.clone(), id("agent:other"), /*writer_epoch*/ 1, witness.clone(), /*max_events*/ 100,
    ).await;
    assert!(matches!(wrong, Err(RuntimeCellLifecycleError::ScopeMismatch)));
    let mut journal = RuntimeCellLifecycleJournalV1::attach(
        pool.clone(), plan.agent_id.clone(), /*writer_epoch*/ 1, witness, /*max_events*/ 100,
    ).await.unwrap();
    journal.create(&plan, /*now_ms*/ 100).await.unwrap();
    journal.prepare_next(&plan, /*expected_revision*/ 0, /*now_ms*/ 101).await.unwrap();
    sqlx::query("DELETE FROM hepta_cell_lifecycle_event_v1 WHERE sequence = 2")
        .execute(&pool).await.unwrap();
    assert_eq!(journal.read(&plan).await.unwrap_err(), RuntimeCellLifecycleError::Corrupt);
}

#[tokio::test]
async fn late_reconciliation_cannot_extend_the_deadline() {
    let directory = tempfile::tempdir().unwrap();
    let plan = plan(RuntimeCellStructuralChangeV1::Split);
    let witness = Witness::new(&plan.agent_id);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(
        pool(&directory.path().join("owner.sqlite")).await,
        plan.agent_id.clone(), /*writer_epoch*/ 1, witness, /*max_events*/ 100,
    ).await.unwrap();
    journal.create(&plan, /*now_ms*/ 100).await.unwrap();
    let pending = journal.prepare_next(&plan, /*expected_revision*/ 0, /*now_ms*/ 999).await.unwrap();
    journal.record_observation(
        &plan, /*expected_revision*/ 1, observation(&plan, &pending, /*at*/ 1001), &Observer,
    ).await.unwrap();
    assert_eq!(
        journal.prepare_next(&plan, /*expected_revision*/ 2, /*now_ms*/ 1002).await.unwrap_err(),
        RuntimeCellLifecycleError::Deadline,
    );
}

#[tokio::test]
async fn unacknowledged_native_observation_must_be_independently_reauthenticated() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("owner.sqlite");
    let plan = plan(RuntimeCellStructuralChangeV1::Split);
    let witness = Witness::new(&plan.agent_id);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(
        pool(&path).await, plan.agent_id.clone(), /*writer_epoch*/ 1,
        witness.clone(), /*max_events*/ 100,
    ).await.unwrap();
    journal.create(&plan, /*now_ms*/ 100).await.unwrap();
    let pending = journal.prepare_next(&plan, /*expected_revision*/ 0, /*now_ms*/ 101).await.unwrap();
    let observed = observation(&plan, &pending, /*at*/ 102);
    witness.refuse_once.store(true, Ordering::SeqCst);
    assert_eq!(
        journal.record_observation(&plan, /*expected_revision*/ 1, observed.clone(), &Observer).await.unwrap_err(),
        RuntimeCellLifecycleError::CommitUncertain,
    );
    journal.pool.close().await;
    drop(journal);
    let denied = RuntimeCellLifecycleJournalV1::recover(
        pool(&path).await, &plan, /*writer_epoch*/ 1, witness.clone(),
        /*max_events*/ 100, &RevokedObserver,
    ).await;
    assert!(matches!(denied, Err(RuntimeCellLifecycleError::Authentication)));
    let recovered = RuntimeCellLifecycleJournalV1::recover(
        pool(&path).await, &plan, /*writer_epoch*/ 1, witness,
        /*max_events*/ 100, &Observer,
    ).await.unwrap();
    assert_eq!(
        recovered.read_observation(&plan, RuntimeCellLifecycleStageV1::StopAdmission).await.unwrap(),
        Some(observed),
    );
}

#[tokio::test]
async fn proved_no_contact_reuses_the_same_operation_but_unknown_cannot() {
    let directory = tempfile::tempdir().unwrap();
    let plan = plan(RuntimeCellStructuralChangeV1::Split);
    let witness = Witness::new(&plan.agent_id);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(
        pool(&directory.path().join("owner.sqlite")).await,
        plan.agent_id.clone(), /*writer_epoch*/ 1, witness, /*max_events*/ 100,
    ).await.unwrap();
    journal.create(&plan, /*now_ms*/ 100).await.unwrap();
    let first = journal.prepare_next(&plan, /*expected_revision*/ 0, /*now_ms*/ 101).await.unwrap();
    assert_eq!(
        journal.prepare_next(&plan, /*expected_revision*/ 1, /*now_ms*/ 102).await.unwrap_err(),
        RuntimeCellLifecycleError::ReconciliationRequired,
    );
    let mut absent = observation(&plan, &first, /*at*/ 103);
    absent.outcome = RuntimeCellLifecycleNativeOutcomeV1::NotApplied;
    absent.admission_closed = false;
    let state = journal.record_observation(
        &plan, /*expected_revision*/ 1, absent, &Observer,
    ).await.unwrap();
    assert_eq!(state.stage(), Some(RuntimeCellLifecycleStageV1::StopAdmission));
    let retry = journal.prepare_next(&plan, state.revision(), /*now_ms*/ 104).await.unwrap();
    assert_eq!(retry.semantic_operation, first.semantic_operation);
    assert_eq!(retry.prepared_revision, 3);
    assert_ne!(retry.attempt_digest, first.attempt_digest);
    let done = journal.record_observation(
        &plan, /*expected_revision*/ 3, observation(&plan, &retry, /*at*/ 105), &Observer,
    ).await.unwrap();
    assert_eq!(done.stage(), Some(RuntimeCellLifecycleStageV1::Drain));
}

#[tokio::test]
async fn stale_no_contact_proof_cannot_clear_a_new_prepare_at_the_same_timestamp() {
    let directory = tempfile::tempdir().unwrap();
    let plan = plan(RuntimeCellStructuralChangeV1::Split);
    let witness = Witness::new(&plan.agent_id);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(
        pool(&directory.path().join("owner.sqlite")).await,
        plan.agent_id.clone(), /*writer_epoch*/ 1, witness, /*max_events*/ 100,
    ).await.unwrap();
    journal.create(&plan, /*now_ms*/ 100).await.unwrap();
    let first = journal.prepare_next(&plan, /*expected_revision*/ 0, /*now_ms*/ 101).await.unwrap();
    let mut old_absence = observation(&plan, &first, /*at*/ 102);
    old_absence.outcome = RuntimeCellLifecycleNativeOutcomeV1::NotApplied;
    old_absence.admission_closed = false;
    journal.record_observation(
        &plan, /*expected_revision*/ 1, old_absence.clone(), &Observer,
    ).await.unwrap();

    // Millisecond clocks can legitimately repeat. The new durable prepare
    // creates a new observation obligation without changing the native ID.
    let retry = journal.prepare_next(&plan, /*expected_revision*/ 2, /*now_ms*/ 102).await.unwrap();
    assert_eq!(retry.semantic_operation, first.semantic_operation);
    assert_ne!(retry.attempt_digest, first.attempt_digest);
    let before = journal.read(&plan).await.unwrap();
    assert_eq!(
        journal.record_observation(
            &plan, /*expected_revision*/ 3, old_absence.clone(), &Observer,
        ).await.unwrap_err(),
        RuntimeCellLifecycleError::Conflict,
    );
    assert_eq!(journal.read(&plan).await.unwrap(), before);
    assert_eq!(journal.pending_intent(&plan).await.unwrap(), Some(retry.clone()));

    // Relabeling only the revision fails the canonical attempt binding before
    // authentication; a real observer also signs both fields together.
    let mut relabeled = old_absence;
    relabeled.prepared_revision = retry.prepared_revision;
    assert_eq!(
        journal.record_observation(
            &plan, /*expected_revision*/ 3, relabeled, &Observer,
        ).await.unwrap_err(),
        RuntimeCellLifecycleError::ScopeMismatch,
    );
    assert_eq!(journal.read(&plan).await.unwrap(), before);
    let applied = observation(&plan, &retry, /*at*/ 102);
    let finished = journal.record_observation(
        &plan, /*expected_revision*/ 3, applied.clone(), &Observer,
    ).await.unwrap();
    assert_eq!(finished.stage(), Some(RuntimeCellLifecycleStageV1::Drain));
    assert_eq!(
        journal.read_observation(&plan, RuntimeCellLifecycleStageV1::StopAdmission).await.unwrap(),
        Some(applied),
    );
}

#[tokio::test]
async fn intent_reserves_its_observation_capacity_against_other_operations() {
    let directory = tempfile::tempdir().unwrap();
    let plan = plan(RuntimeCellStructuralChangeV1::Split);
    let mut journal = RuntimeCellLifecycleJournalV1::attach(
        pool(&directory.path().join("owner.sqlite")).await, plan.agent_id.clone(),
        1, Witness::new(&plan.agent_id), /*max_events*/ 3,
    ).await.unwrap();
    journal.create(&plan, 100).await.unwrap();
    let pending = journal.prepare_next(&plan, 0, 101).await.unwrap();
    let mut competing = plan.clone();
    competing.operation_id = id("operation:other");
    assert_eq!(journal.create(&competing, 102).await.unwrap_err(), RuntimeCellLifecycleError::Capacity);
    let settled = journal.record_observation(&plan, 1, observation(&plan, &pending, 102), &Observer).await.unwrap();
    assert!(!settled.pending_reconciliation());
    assert_eq!(settled.revision(), 2);
}

#[tokio::test]
async fn insufficient_global_or_per_operation_capacity_never_returns_a_fresh_intent() {
    for maximum in [2, 100] {
        let directory = tempfile::tempdir().unwrap();
        let plan = plan(RuntimeCellStructuralChangeV1::Split);
        let mut journal = RuntimeCellLifecycleJournalV1::attach(
            pool(&directory.path().join("owner.sqlite")).await, plan.agent_id.clone(),
            1, Witness::new(&plan.agent_id), maximum,
        ).await.unwrap();
        let mut snapshot = journal.create(&plan, 100).await.unwrap();
        if maximum == 100 {
            for _ in 0..31 {
                let intent = journal.prepare_next(&plan, snapshot.revision(), 101).await.unwrap();
                let mut absent = observation(&plan, &intent, 101);
                absent.outcome = RuntimeCellLifecycleNativeOutcomeV1::NotApplied;
                absent.admission_closed = false;
                snapshot = journal.record_observation(&plan, intent.prepared_revision, absent, &Observer).await.unwrap();
            }
            assert_eq!(snapshot.revision(), 62);
        }
        assert_eq!(journal.prepare_next(&plan, snapshot.revision(), 102).await.unwrap_err(), RuntimeCellLifecycleError::Capacity);
        assert_eq!(journal.pending_intent(&plan).await.unwrap(), None);
        assert_eq!(journal.read(&plan).await.unwrap(), Some(snapshot));
    }
}
