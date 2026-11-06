use std::fs;
use std::fs::OpenOptions;
use std::process::Command;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::*;
use crate::FileAnchorWitnessStore;
use crate::JournalScope;
use crate::cell_task_cost::*;
use crate::cell_test_support::checked;

#[path = "cell_generation_observation_tests.rs"]
mod observation;
#[path = "cell_generation_test_support.rs"]
mod support;
use support::*;

#[test]
fn state_prefix_outbox_cost_and_replay_survive_owner_reopen() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "one");
    assert_eq!(owner.admit(req.clone(), /*now_micros*/ 11), Ok(None));
    let proposed = proposal(&req);
    let receipt = checked(owner.commit(proposed.clone(), /*now_micros*/ 20));
    let snapshot = checked(owner.snapshot()).clone();
    let chunk = checked(checked(owner.pending_output()).cloned().ok_or("outbox"));
    let costs = checked(owner.task_cost()).clone();
    drop(owner);
    let mut reopened = fixture.open();
    assert_eq!(reopened.snapshot(), Ok(&snapshot));
    assert_eq!(reopened.pending_output(), Ok(Some(&chunk)));
    assert_eq!(reopened.task_cost(), Ok(&costs));
    assert_eq!(
        reopened.admit(req, /*now_micros*/ 500),
        Ok(Some(receipt.clone()))
    );
    assert_eq!(reopened.commit(proposed, /*now_micros*/ 500), Ok(receipt));
    assert_eq!(
        reopened.admit(request(&reopened, "two"), /*now_micros*/ 20),
        Err(CellGenerationErrorV2::Pending)
    );
    let mut changed = chunk.clone();
    changed.bytes.push(0);
    assert_eq!(
        reopened.acknowledge(changed, [1; 32], cost()),
        Err(CellGenerationErrorV2::Conflict)
    );
    checked(reopened.acknowledge(chunk.clone(), [1; 32], cost()));
    let bytes = fixture.bytes();
    checked(reopened.acknowledge(chunk, [1; 32], cost()));
    assert_eq!(fixture.bytes(), bytes);
    let next = request(&reopened, "two");
    checked(reopened.admit(next.clone(), /*now_micros*/ 21));
    let mut final_proposal = proposal(&next);
    final_proposal.output_delta = b"tail".to_vec();
    final_proposal.disposition = CellGenerationDispositionV2::Stopped;
    checked(reopened.commit(final_proposal, /*now_micros*/ 25));
    assert_eq!(checked(reopened.snapshot()).prefix, "中🙂\ntail".as_bytes());
}

#[test]
fn cancellation_and_drain_retain_unknown_work_then_settle_without_output() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "cancel");
    let initial = checked(owner.snapshot()).state.clone();
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    checked(owner.cancel(checked(req.digest())));
    checked(owner.drain());
    assert_eq!(owner.is_drained(), Ok(false));
    assert_eq!(owner.resume(), Err(CellGenerationErrorV2::Pending));
    drop(owner);
    let mut owner = fixture.open();
    assert_eq!(owner.pending_request(), Ok(Some(&req)));
    let receipt = checked(owner.commit(proposal(&req), /*now_micros*/ 20));
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Cancelled);
    assert_eq!(checked(owner.snapshot()).state, initial);
    assert_eq!(owner.pending_output(), Ok(None));
    assert_eq!(checked(owner.task_cost()).entries(), receipt.cost.entries());
    assert_eq!(owner.is_drained(), Ok(true));
    checked(owner.resume());
}

#[test]
fn deadline_and_failed_receipts_preserve_cost_without_fabricating_state() {
    for disposition in [
        CellGenerationDispositionV2::Failed,
        CellGenerationDispositionV2::Rejected,
        CellGenerationDispositionV2::Cancelled,
        CellGenerationDispositionV2::Advanced,
    ] {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        let req = request(&owner, "terminal");
        checked(owner.admit(req.clone(), /*now_micros*/ 11));
        let mut result = proposal(&req);
        result.disposition = disposition;
        let time = if disposition == CellGenerationDispositionV2::Advanced {
            100
        } else {
            result.output_delta.clear();
            result.successor_state = req.predecessor.state.clone();
            20
        };
        checked(owner.commit(result, time));
        assert_eq!(checked(owner.snapshot()).state, req.predecessor.state);
        assert_eq!(owner.pending_output(), Ok(None));
        assert_eq!(owner.pending_request(), Ok(None));
        assert_eq!(checked(owner.task_cost()).entries().len(), 1);
    }
}

#[test]
fn whole_witnessed_suffix_loss_is_rejected_without_repairing_evidence() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "one");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    let prefix = fixture.bytes();
    checked(owner.commit(proposal(&req), /*now_micros*/ 20));
    drop(owner);
    checked(fs::write(fixture.0.join("journal"), &prefix));
    assert!(matches!(
        CellGenerationJournalV2::open(
            fixture.file("journal"),
            fixture.witness(),
            config(),
            /*max_records*/ 128
        ),
        Err(CellGenerationErrorV2::AcknowledgedHistoryMissing)
    ));
    assert_eq!(fixture.bytes(), prefix);
}

#[test]
fn learning_evolution_scope_and_predecessor_drift_never_reinitialize() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "one");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    checked(owner.commit(proposal(&req), /*now_micros*/ 20));
    drop(owner);
    let original = fixture.bytes();
    let mut learning = config();
    learning.manifest.learning = CellLearningBindingV2::Frozen { weights: [99; 32] };
    let mut evolution = config();
    evolution.manifest.evolution.lineage = [99; 32];
    let mut scope = config();
    scope.initial.scope.agent_id = "other".to_string();
    for mut changed in [learning, evolution, scope] {
        changed.initial.manifest_digest = checked(changed.manifest.digest());
        assert!(matches!(
            CellGenerationJournalV2::open(
                fixture.file("journal"),
                fixture.witness(),
                changed,
                /*max_records*/ 128
            ),
            Err(CellGenerationErrorV2::InvalidBinding)
        ));
        assert_eq!(fixture.bytes(), original);
    }
    assert_eq!(
        checked(fixture.open().snapshot()).prefix,
        "中🙂\n".as_bytes()
    );
}

#[test]
fn lost_witness_ack_requires_reconciliation_then_exposes_exact_committed_bytes() {
    let fixture = Fixture::new();
    let fail = Arc::new(AtomicBool::new(false));
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        FailOnce {
            inner: fixture.witness(),
            fail: Arc::clone(&fail),
        },
        config(),
        /*max_records*/ 128,
    ));
    let req = request(&owner, "one");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    let result = proposal(&req);
    fail.store(true, Ordering::SeqCst);
    assert_eq!(
        owner.commit(result.clone(), /*now_micros*/ 20),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    assert_eq!(
        owner.snapshot(),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    checked(owner.recover());
    let receipt = checked(checked(owner.lookup(&req)).ok_or("receipt"));
    assert_eq!(owner.commit(result, /*now_micros*/ 30), Ok(receipt));
    assert_eq!(
        checked(checked(owner.pending_output()).ok_or("chunk")).bytes,
        "中🙂\n".as_bytes()
    );
}

#[test]
fn torn_unwitnessed_commit_tail_restores_exact_pending_admission() {
    let fixture = Fixture::new();
    let fail = Arc::new(AtomicBool::new(false));
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        FailOnce {
            inner: fixture.witness(),
            fail: Arc::clone(&fail),
        },
        config(),
        /*max_records*/ 128,
    ));
    let req = request(&owner, "torn");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    let admitted = fixture.bytes();
    fail.store(true, Ordering::SeqCst);
    assert_eq!(
        owner.commit(proposal(&req), /*now_micros*/ 20),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    let full = fixture.bytes();
    drop(owner);
    let tail = full.len() - admitted.len();
    for retained in [1, 3, 4, tail / 2, tail - 1] {
        checked(fs::write(
            fixture.0.join("journal"),
            &full[..admitted.len() + retained],
        ));
        let mut reopened = fixture.open();
        assert_eq!(reopened.snapshot(), Ok(&req.predecessor));
        assert_eq!(reopened.pending_request(), Ok(Some(&req)));
        assert_eq!(reopened.pending_output(), Ok(None));
        assert_eq!(reopened.task_cost(), Ok(&cost()));
        assert_eq!(
            reopened.admit(req.clone(), /*now_micros*/ 30),
            Err(CellGenerationErrorV2::Pending)
        );
        assert_eq!(fixture.bytes(), admitted);
    }
}

#[test]
fn acknowledged_delivery_rejects_changed_bytes_ack_and_cost_after_reopen() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "one");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    checked(owner.commit(proposal(&req), /*now_micros*/ 20));
    let chunk = checked(checked(owner.pending_output()).cloned().ok_or("chunk"));
    checked(owner.acknowledge(chunk.clone(), [1; 32], cost()));
    drop(owner);
    let mut reopened = fixture.open();
    let original = fixture.bytes();
    let mut changed = chunk.clone();
    changed.bytes.push(0);
    assert_eq!(
        reopened.acknowledge(changed, [1; 32], cost()),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        reopened.acknowledge(chunk.clone(), [2; 32], cost()),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        reopened.acknowledge(
            chunk.clone(),
            [1; 32],
            charges("new-ack", CellCostStageV2::Communication, /*count*/ 1)
        ),
        Err(CellGenerationErrorV2::Conflict)
    );
    checked(reopened.acknowledge(chunk, [1; 32], cost()));
    assert_eq!(reopened.pending_output(), Ok(None));
    assert_eq!(fixture.bytes(), original);
}

#[test]
fn independent_process_second_writer_cannot_acquire_the_owner_journal() {
    const CONTENDER: &str = "HEPTA_GENERATION_TEST_CONTENDER_ROOT";
    if let Some(root) = std::env::var_os(CONTENDER) {
        let path = std::path::PathBuf::from(root);
        let journal = checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(path.join("journal")),
        );
        let witness_file = checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(path.join("contender-witness")),
        );
        let witness = checked(FileAnchorWitnessStore::open(
            witness_file,
            JournalScope {
                scope_digest: Digest32::of_bytes(b"scope"),
                objective_digest: Digest32::of_bytes(b"objective"),
            },
            checked(Generation::new(1)),
            /*max_records*/ 128,
        ));
        assert!(matches!(
            CellGenerationJournalV2::open(journal, witness, config(), /*max_records*/ 128),
            Err(CellGenerationErrorV2::Unavailable)
        ));
        return;
    }
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "held");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    let original = fixture.bytes();
    let child = checked(Command::new(checked(std::env::current_exe()))
        .args(["--exact", "cell_generation_journal::tests::independent_process_second_writer_cannot_acquire_the_owner_journal", "--nocapture"])
        .env(CONTENDER, &fixture.0).output());
    assert!(
        child.status.success(),
        "child stdout={} stderr={}",
        String::from_utf8_lossy(&child.stdout),
        String::from_utf8_lossy(&child.stderr)
    );
    assert!(String::from_utf8_lossy(&child.stdout).contains("1 passed"));
    assert_eq!(fixture.bytes(), original);
    drop(owner);
    assert_eq!(fixture.open().pending_request(), Ok(Some(&req)));
}

#[test]
fn incomplete_resumable_learning_closure_cannot_reopen_or_reinitialize() {
    let fixture = Fixture::new();
    drop(fixture.open());
    let original = fixture.bytes();
    for missing in 0..5 {
        let mut changed = config();
        if let CellLearningBindingV2::Resumable {
            weights,
            optimizer,
            rng,
            sampler,
            training_cursor,
        } = &mut changed.manifest.learning
        {
            let fields = [weights, optimizer, rng, sampler, training_cursor];
            *fields[missing] = [0; 32];
        }
        assert!(matches!(
            CellGenerationJournalV2::open(
                fixture.file("journal"),
                fixture.witness(),
                changed,
                /*max_records*/ 128
            ),
            Err(CellGenerationErrorV2::InvalidBinding)
        ));
        assert_eq!(fixture.bytes(), original);
    }
    let mut bytes = checked(serde_json::to_value(config()));
    checked(
        bytes["manifest"]["learning"]
            .as_object_mut()
            .ok_or("learning object"),
    )
    .remove("optimizer");
    assert!(serde_json::from_value::<CellGenerationConfigV2>(bytes).is_err());
    assert_eq!(checked(fixture.open().snapshot()), &config().initial);
}

#[test]
fn bounded_journal_reserves_cancellation_drain_settlement_and_delivery_ack() {
    let fixture = Fixture::new();
    let mut owner = fixture.open_with(config(), /*max_records*/ 7);
    let req = request(&owner, "cancel");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    let overhead = saturate_cost_records(&mut owner, "overhead", /*max_attempts*/ 7);
    let before = fixture.bytes();
    assert_eq!(
        owner.record_cost(charge("excess", CellCostStageV2::Persistence)),
        Err(CellGenerationErrorV2::Capacity)
    );
    checked(owner.record_cost(overhead));
    assert_eq!(fixture.bytes(), before);
    checked(owner.observe_dispatch_time(checked(req.digest()), /*observed_at_micros*/ 12));
    checked(owner.cancel(checked(req.digest())));
    checked(owner.drain());
    let receipt = checked(owner.commit(proposal(&req), /*now_micros*/ 20));
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Cancelled);
    assert_eq!(owner.is_drained(), Ok(true));
    drop(owner);
    assert_eq!(
        fixture.open_with(config(), /*max_records*/ 7).is_drained(),
        Ok(true)
    );

    let fixture = Fixture::new();
    let mut owner = fixture.open_with(config(), /*max_records*/ 7);
    let req = request(&owner, "deliver");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    checked(owner.observe_dispatch_time(checked(req.digest()), /*observed_at_micros*/ 12));
    checked(owner.commit(proposal(&req), /*now_micros*/ 20));
    let chunk = checked(checked(owner.pending_output()).cloned().ok_or("chunk"));
    saturate_cost_records(&mut owner, "outbox-overhead", /*max_attempts*/ 7);
    assert_eq!(
        owner.record_cost(charge("excess", CellCostStageV2::Persistence)),
        Err(CellGenerationErrorV2::Capacity)
    );
    checked(owner.drain());
    checked(owner.acknowledge(chunk.clone(), [1; 32], cost()));
    assert_eq!(owner.is_drained(), Ok(true));
    let final_bytes = fixture.bytes();
    checked(owner.acknowledge(chunk, [1; 32], cost()));
    assert_eq!(fixture.bytes(), final_bytes);
    drop(owner);
    assert_eq!(
        fixture.open_with(config(), /*max_records*/ 7).is_drained(),
        Ok(true)
    );
}

#[test]
fn unobserved_pending_work_never_becomes_fresh_admission_after_reopen() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "unknown");
    assert_eq!(owner.admit(req.clone(), /*now_micros*/ 11), Ok(None));
    let original = fixture.bytes();
    drop(owner);
    let mut reopened = fixture.open();
    assert_eq!(reopened.lookup(&req), Ok(None));
    for now in [12, 50, 99] {
        assert_eq!(
            reopened.admit(req.clone(), now),
            Err(CellGenerationErrorV2::Pending)
        );
        assert_eq!(
            reopened.admit(request(&reopened, "replacement"), now),
            Err(CellGenerationErrorV2::Pending)
        );
        checked(reopened.recover());
        assert_eq!(reopened.pending_request(), Ok(Some(&req)));
    }
    assert_eq!(
        reopened.admit(req.clone(), /*now_micros*/ 100),
        Err(CellGenerationErrorV2::Deadline)
    );
    assert_eq!(reopened.pending_output(), Ok(None));
    assert_eq!(fixture.bytes(), original);
    assert_eq!(reopened.snapshot(), Ok(&req.predecessor));
}

#[test]
fn full_committed_prefix_still_allows_cancelled_and_expired_cost_settlement() {
    for disposition in [
        CellGenerationDispositionV2::Cancelled,
        CellGenerationDispositionV2::DeadlineExceeded,
    ] {
        let fixture = Fixture::new();
        let mut cfg = config();
        cfg.manifest.max_prefix_bytes = cfg.manifest.max_delta_bytes;
        cfg.initial.manifest_digest = checked(cfg.manifest.digest());
        let mut owner = fixture.open_with(cfg, /*max_records*/ 128);
        let first = request(&owner, "fill");
        checked(owner.admit(first.clone(), /*now_micros*/ 11));
        let mut filled = proposal(&first);
        filled.output_delta = vec![b'x'; 256];
        checked(owner.commit(filled, /*now_micros*/ 20));
        let chunk = checked(checked(owner.pending_output()).cloned().ok_or("chunk"));
        checked(owner.acknowledge(chunk, [1; 32], cost()));
        let expected = checked(owner.snapshot()).clone();
        let req = request(&owner, "discard");
        checked(owner.admit(req.clone(), /*now_micros*/ 21));
        let mut result = proposal(&req);
        result.successor_state = vec![99];
        let time = if disposition == CellGenerationDispositionV2::Cancelled {
            checked(owner.cancel(checked(req.digest())));
            25
        } else {
            100
        };
        let receipt = checked(owner.commit(result, time));
        assert_eq!(receipt.disposition, disposition);
        assert_eq!(
            checked(owner.snapshot()),
            &CellRuntimeSnapshotV2 {
                revision: expected.revision + 1,
                ..expected
            }
        );
        assert_eq!(owner.pending_output(), Ok(None));
        assert_eq!(checked(owner.task_cost()).entries().len(), 2);
    }
}

#[test]
fn actual_admission_clock_floor_survives_reopen_and_rejects_early_settlement() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "late-admission");
    checked(owner.admit(req.clone(), /*now_micros*/ 90));
    let admitted = fixture.bytes();
    assert_eq!(
        owner.commit(proposal(&req), /*now_micros*/ 11),
        Err(CellGenerationErrorV2::Deadline)
    );
    assert_eq!(fixture.bytes(), admitted);
    drop(owner);
    let mut reopened = fixture.open();
    assert_eq!(
        reopened.commit(proposal(&req), /*now_micros*/ 89),
        Err(CellGenerationErrorV2::Deadline)
    );
    let receipt = checked(reopened.commit(proposal(&req), /*now_micros*/ 91));
    let chunk = checked(checked(reopened.pending_output()).cloned().ok_or("chunk"));
    checked(reopened.acknowledge(chunk, [1; 32], cost()));
    let next = request(&reopened, "next");
    let before = fixture.bytes();
    assert_eq!(
        reopened.admit(next.clone(), /*now_micros*/ 90),
        Err(CellGenerationErrorV2::Deadline)
    );
    assert_eq!(
        reopened.commit(proposal(&req), /*now_micros*/ 11),
        Ok(receipt)
    );
    assert_eq!(fixture.bytes(), before);
    assert_eq!(reopened.admit(next, /*now_micros*/ 92), Ok(None));
}

#[test]
fn task_cost_capacity_is_reserved_before_model_work_and_kept_for_acknowledgement() {
    let fixture = Fixture::new();
    let mut owner = fixture.open_with(config(), /*max_records*/ 1_024);
    for batch in 0..127 {
        let label = format!("historical-{batch}");
        let mut req = request(&owner, &label);
        req.admitted_at_micros = 10 + batch * 10;
        req.deadline_micros = req.admitted_at_micros + 100;
        checked(owner.admit(req.clone(), req.admitted_at_micros + 1));
        let mut result = proposal(&req);
        result.output_delta.clear();
        result.cost = charges(
            &label,
            CellCostStageV2::Training,
            if batch == 126 { 16 } else { 32 },
        );
        checked(owner.commit(result, req.admitted_at_micros + 2));
    }
    assert_eq!(checked(owner.task_cost()).entries().len(), 4_048);
    let mut req = request(&owner, "reserved");
    req.admitted_at_micros = 2_000;
    req.deadline_micros = 2_100;
    checked(owner.admit(req.clone(), /*now_micros*/ 2_001));
    let before = fixture.bytes();
    assert_eq!(
        owner.record_cost(charge("squeeze", CellCostStageV2::Persistence)),
        Err(CellGenerationErrorV2::Capacity)
    );
    let replay = checked(owner.task_cost()).entries()[0].clone();
    checked(owner.record_cost(replay));
    assert_eq!(fixture.bytes(), before);
    let mut result = proposal(&req);
    result.cost = charges(
        "reserved-work",
        CellCostStageV2::Inference,
        /*count*/ 32,
    );
    checked(owner.commit(result, /*now_micros*/ 2_002));
    let chunk = checked(checked(owner.pending_output()).cloned().ok_or("chunk"));
    assert_eq!(
        owner.record_cost(charge("squeeze-ack", CellCostStageV2::Persistence)),
        Err(CellGenerationErrorV2::Capacity)
    );
    checked(owner.acknowledge(
        chunk,
        [1; 32],
        charges(
            "delivery",
            CellCostStageV2::Communication,
            /*count*/ 16,
        ),
    ));
    assert_eq!(checked(owner.task_cost()).entries().len(), 4_096);
    let mut next = request(&owner, "no-capacity");
    next.admitted_at_micros = 2_010;
    next.deadline_micros = 2_100;
    assert_eq!(
        owner.admit(next, /*now_micros*/ 2_011),
        Err(CellGenerationErrorV2::Capacity)
    );
    checked(owner.drain());
    assert_eq!(owner.is_drained(), Ok(true));
}

#[test]
fn reopen_with_lower_capacity_rejects_before_repairing_reserved_pending_history() {
    let fixture = Fixture::new();
    let mut owner = fixture.open_with(config(), /*max_records*/ 10);
    let req = request(&owner, "reserved-reopen");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    saturate_cost_records(&mut owner, "reopen-overhead", /*max_attempts*/ 10);
    let recorded_costs = checked(owner.task_cost()).entries().len();
    let committed = fixture.bytes();
    drop(owner);
    let mut with_torn_tail = committed.clone();
    with_torn_tail.push(0);
    checked(fs::write(fixture.0.join("journal"), &with_torn_tail));
    assert!(matches!(
        CellGenerationJournalV2::open(
            fixture.file("journal"),
            fixture.witness(),
            config(),
            /*max_records*/ 6,
        ),
        Err(CellGenerationErrorV2::InvalidBinding)
    ));
    assert_eq!(fixture.bytes(), with_torn_tail);
    let mut reopened = fixture.open_with(config(), /*max_records*/ 10);
    assert_eq!(fixture.bytes(), committed);
    assert_eq!(reopened.pending_request(), Ok(Some(&req)));
    checked(reopened.observe_dispatch_time(checked(req.digest()), /*observed_at_micros*/ 12));
    checked(reopened.cancel(checked(req.digest())));
    checked(reopened.drain());
    checked(reopened.commit(proposal(&req), /*now_micros*/ 20));
    assert_eq!(reopened.is_drained(), Ok(true));
    assert_eq!(
        checked(reopened.task_cost()).entries().len(),
        recorded_costs + 1
    );
}

#[test]
fn precontact_clock_floor_is_durable_and_observation_does_not_allow_redispatch() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "precontact");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    let admitted = fixture.bytes();
    assert_eq!(
        owner.observe_dispatch_time([99; 32], /*observed_at_micros*/ 12),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        owner.observe_dispatch_time(checked(req.digest()), /*observed_at_micros*/ 100),
        Err(CellGenerationErrorV2::Deadline)
    );
    assert_eq!(fixture.bytes(), admitted);
    checked(owner.observe_dispatch_time(checked(req.digest()), /*observed_at_micros*/ 90));
    let observed = fixture.bytes();
    drop(owner);
    let mut reopened = fixture.open();
    assert_eq!(
        reopened.commit(proposal(&req), /*now_micros*/ 20),
        Err(CellGenerationErrorV2::Deadline)
    );
    assert_eq!(
        reopened.observe_dispatch_time(checked(req.digest()), /*observed_at_micros*/ 91),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        reopened.admit(req.clone(), /*now_micros*/ 91),
        Err(CellGenerationErrorV2::Pending)
    );
    assert_eq!(reopened.pending_request(), Ok(Some(&req)));
    assert_eq!(fixture.bytes(), observed);
    checked(reopened.commit(proposal(&req), /*now_micros*/ 91));
    assert_eq!(
        checked(checked(reopened.pending_output()).ok_or("chunk")).bytes,
        "中🙂\n".as_bytes()
    );
}
