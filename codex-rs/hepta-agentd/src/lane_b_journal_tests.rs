#![cfg(unix)]
use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Home(PathBuf);
impl Home {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "hepta-lifecycle-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).expect("new test home");
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700))
            .expect("private home");
        Self(path)
    }
    fn path(&self) -> PathBuf {
        self.0.join("runs.json")
    }
}
impl Drop for Home {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.1".into(),
        supervisor_generation: 2,
        agentd_generation: 3,
        configuration_digest: "1".repeat(64),
        ports_digest: "2".repeat(64),
        max_active_runs: 2,
    }
}
fn snapshot(id: &str) -> RunSnapshot {
    RunSnapshot {
        run_id: id.into(),
        request_digest: "3".repeat(64),
        objective_digest: "4".repeat(64),
        body_digest: "5".repeat(64),
        artifact_set_digest: "6".repeat(64),
        authority_epoch: 7,
        generation: 3,
        fence_digest: "9".repeat(64),
        deadline_ms: 10_000,
    }
}
fn attachment() -> ContextAttachment {
    let s = snapshot("run.1");
    ContextAttachment {
        run_id: s.run_id,
        request_digest: s.request_digest,
        objective_digest: s.objective_digest,
        body_digest: s.body_digest,
        artifact_set_digest: s.artifact_set_digest,
        authority_epoch: s.authority_epoch,
        generation: s.generation,
        fence_digest: s.fence_digest,
        deadline_ms: s.deadline_ms,
        context_digest: "7".repeat(64),
        compilation_receipt_digest: "8".repeat(64),
    }
}
fn create(home: &Home) -> AgentRunCoordinator {
    AgentRunCoordinator::open_journaled(composition(), &home.path(), JournalOpenMode::Create)
        .expect("create original owner")
}
fn reopen(home: &Home) -> AgentRunCoordinator {
    AgentRunCoordinator::open_journaled(composition(), &home.path(), JournalOpenMode::Reopen)
        .expect("reopen original owner")
}
fn attached(owner: &mut AgentRunCoordinator) -> RunReceipt {
    owner.start_run(100, snapshot("run.1")).expect("start");
    owner.attach_context(200, 1, attachment()).expect("attach")
}

#[test]
fn exact_retries_do_not_commit_new_transactions() {
    let home = Home::new();
    let mut owner = create(&home);
    let first = owner.start_run(100, snapshot("run.1")).unwrap();
    let sequence = owner.journal.as_ref().unwrap().sequence;
    let retry = owner.start_run(100, snapshot("run.1")).unwrap();
    assert!(retry.idempotent);
    assert_eq!(retry.revision, first.revision);
    assert_eq!(owner.journal.as_ref().unwrap().sequence, sequence);
    let context = owner.attach_context(200, 1, attachment()).unwrap();
    let sequence = owner.journal.as_ref().unwrap().sequence;
    assert!(
        owner
            .attach_context(200, 1, attachment())
            .unwrap()
            .idempotent
    );
    assert_eq!(owner.journal.as_ref().unwrap().sequence, sequence);
    let dispatch = owner
        .mark_dispatched(300, "run.1", context.revision)
        .unwrap();
    let sequence = owner.journal.as_ref().unwrap().sequence;
    assert!(
        owner
            .mark_dispatched(300, "run.1", dispatch.revision)
            .unwrap()
            .idempotent
    );
    assert_eq!(owner.journal.as_ref().unwrap().sequence, sequence);
}

#[test]
fn cancellation_and_pre_dispatch_recovery_preserve_original_receipts() {
    let home = Home::new();
    let mut owner = create(&home);
    owner.start_run(100, snapshot("run.1")).unwrap();
    let (_, cancelled) = owner.cancel_run(200, "run.1", 1, "stop").unwrap();
    assert_eq!(cancelled.phase, RunPhase::Cancelled);
    drop(owner);
    let mut owner = reopen(&home);
    assert_eq!(owner.run("run.1"), Some(cancelled.clone()));
    assert!(
        owner
            .cancel_run(300, "run.1", cancelled.revision, "stop")
            .unwrap()
            .1
            .idempotent
    );
}

#[test]
fn dispatched_and_cancelling_reopen_indeterminate_without_redispatch() {
    for cancel in [false, true] {
        let home = Home::new();
        let mut owner = create(&home);
        let context = attached(&mut owner);
        let dispatched = owner
            .mark_dispatched(300, "run.1", context.revision)
            .unwrap();
        let previous = if cancel {
            let (_, pending) = owner
                .cancel_run(400, "run.1", dispatched.revision, "stop")
                .unwrap();
            assert_eq!(
                owner.cancel_run(400, "run.1", pending.revision, "different"),
                Err(AgentRunError::Conflict)
            );
            pending
        } else {
            dispatched
        };
        drop(owner);
        let mut owner = reopen(&home);
        let recovered = owner.run("run.1").unwrap();
        assert_eq!(recovered.phase, RunPhase::Indeterminate);
        assert_eq!(recovered.revision, previous.revision + 1);
        assert_eq!(recovered.context_digest, previous.context_digest);
        assert_eq!(recovered.cancel_ack_deadline_ms, None);
        assert_eq!(
            owner.mark_dispatched(500, "run.1", recovered.revision),
            Err(AgentRunError::InvalidTransition)
        );
        drop(owner);
        assert_eq!(reopen(&home).run("run.1"), Some(recovered));
    }
}

#[test]
fn attached_reopens_without_losing_context_or_revising_it() {
    let home = Home::new();
    let mut owner = create(&home);
    let before = attached(&mut owner);
    drop(owner);
    assert_eq!(reopen(&home).run("run.1"), Some(before));
}

#[test]
fn batch_overflow_does_not_partially_cancel_or_close_admissions() {
    let home = Home::new();
    let mut owner = create(&home);
    owner.start_run(100, snapshot("run.1")).unwrap();
    owner.start_run(100, snapshot("run.2")).unwrap();
    owner.runs.get_mut("run.2").unwrap().revision = u64::MAX;
    let before = owner.snapshot();
    let bytes = std::fs::read(home.path()).unwrap();
    assert_eq!(
        owner.begin_drain(200, "stop"),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(owner.snapshot(), before);
    assert_eq!(std::fs::read(home.path()).unwrap(), bytes);
}

#[test]
fn single_transition_overflow_does_not_install_partial_context() {
    let home = Home::new();
    let mut owner = create(&home);
    owner.start_run(100, snapshot("run.1")).unwrap();
    owner.runs.get_mut("run.1").unwrap().revision = u64::MAX;
    let before = owner.snapshot();
    assert_eq!(
        owner.attach_context(200, u64::MAX, attachment()),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(owner.snapshot(), before);
}

#[test]
fn failed_publication_preserves_runs_and_poisoning_requires_reopen() {
    for after_rename in [false, true] {
        let home = Home::new();
        let mut owner = create(&home);
        owner.start_run(100, snapshot("run.1")).unwrap();
        let before = owner.run("run.1");
        let journal = owner.journal.as_mut().unwrap();
        journal.fail_before_publish = !after_rename;
        journal.fail_after_publish = after_rename;
        assert_eq!(
            owner.cancel_run(200, "run.1", 1, "stop"),
            Err(AgentRunError::PersistenceUnavailable)
        );
        assert_eq!(owner.run("run.1"), before);
        assert!(!owner.admissions_open());
        assert_eq!(
            owner.cancel_run(200, "run.1", 1, "stop"),
            Err(AgentRunError::PersistenceUnavailable)
        );
        drop(owner);
        let owner = reopen(&home);
        assert_eq!(
            owner.run("run.1").unwrap().phase,
            if after_rename {
                RunPhase::Cancelled
            } else {
                RunPhase::Admitted
            }
        );
    }
}

#[test]
fn snapshot_replacement_reclaims_old_bytes_without_forgetting_retained_run() {
    let home = Home::new();
    let mut owner = create(&home);
    let retained = attached(&mut owner);
    owner.start_run(100, snapshot("run.2")).unwrap();
    let (_, cancelled) = owner.cancel_run(200, "run.2", 1, "stop").unwrap();
    let before = std::fs::metadata(home.path()).unwrap().len();
    let sequence = owner.journal.as_ref().unwrap().sequence;
    owner
        .remove_closed_run("run.2", cancelled.revision)
        .unwrap();
    assert!(std::fs::metadata(home.path()).unwrap().len() < before);
    assert_eq!(owner.journal.as_ref().unwrap().sequence, sequence + 1);
    drop(owner);
    let mut owner = reopen(&home);
    assert_eq!(owner.run("run.1"), Some(retained));
    assert!(
        owner
            .attach_context(200, 1, attachment())
            .unwrap()
            .idempotent
    );
    assert_eq!(owner.run("run.2"), None);
}

#[test]
fn second_writer_wrong_composition_and_missing_reopen_fail_closed() {
    let home = Home::new();
    assert!(
        AgentRunCoordinator::open_journaled(composition(), &home.path(), JournalOpenMode::Reopen)
            .is_err()
    );
    let owner = create(&home);
    assert!(
        AgentRunCoordinator::open_journaled(composition(), &home.path(), JournalOpenMode::Reopen)
            .is_err()
    );
    drop(owner);
    let mut wrong = composition();
    wrong.agent_id = "agent.2".into();
    assert!(
        AgentRunCoordinator::open_journaled(wrong, &home.path(), JournalOpenMode::Reopen).is_err()
    );
}

#[test]
fn checksum_corruption_is_not_treated_as_an_empty_owner() {
    let home = Home::new();
    let mut owner = create(&home);
    owner.start_run(100, snapshot("run.1")).unwrap();
    drop(owner);
    let bytes = std::fs::read_to_string(home.path())
        .unwrap()
        .replace("run.1", "run.2");
    std::fs::write(home.path(), bytes).unwrap();
    assert!(
        AgentRunCoordinator::open_journaled(composition(), &home.path(), JournalOpenMode::Reopen)
            .is_err()
    );
}

fn rewrite_valid_checksum(home: &Home, change: impl FnOnce(&mut Snapshot)) {
    use sha2::Digest;
    let mut document: Document =
        serde_json::from_slice(&std::fs::read(home.path()).unwrap()).unwrap();
    change(&mut document.snapshot);
    document.checksum = format!(
        "{:x}",
        sha2::Sha256::digest(
            serde_json::to_vec(&(2_u32, document.sequence, &document.snapshot)).unwrap()
        )
    );
    std::fs::write(home.path(), serde_json::to_vec(&document).unwrap()).unwrap();
}

#[test]
fn checksum_valid_unreachable_phase_and_capacity_states_are_rejected() {
    for mutation in 0..5 {
        let home = Home::new();
        let mut owner = create(&home);
        attached(&mut owner);
        drop(owner);
        rewrite_valid_checksum(&home, |state| {
            let record = state.runs.get_mut("run.1").unwrap();
            match mutation {
                0 => {
                    record.phase = RunPhase::Admitted;
                    record.revision = 1;
                }
                1 => {
                    record.cancel_reason = Some("not cancelled".into());
                }
                2 => {
                    record.phase = RunPhase::Cancelling;
                    record.cancel_ack_deadline_ms = Some(1000);
                }
                3 => {
                    record.phase = RunPhase::Cancelling;
                    record.cancel_reason = Some("stop".into());
                    record.cancel_ack_deadline_ms = Some(0);
                }
                4 => {
                    let mut extra = record.clone();
                    extra.snapshot.run_id = "run.2".into();
                    state.runs.insert("run.2".into(), extra.clone());
                    extra.snapshot.run_id = "run.3".into();
                    state.runs.insert("run.3".into(), extra);
                }
                _ => unreachable!(),
            }
        });
        assert!(
            AgentRunCoordinator::open_journaled(
                composition(),
                &home.path(),
                JournalOpenMode::Reopen
            )
            .is_err(),
            "mutation {mutation}"
        );
    }
}

#[test]
fn close_then_successful_empty_drain_persists_the_closed_latch() {
    let home = Home::new();
    let mut owner = create(&home);
    owner.close_admissions();
    assert_eq!(owner.begin_drain(200, "fenced"), Ok(0));
    drop(owner);
    assert!(!reopen(&home).admissions_open());
}

#[test]
fn create_never_overwrites_a_file_appearing_before_first_publication() {
    let home = Home::new();
    let (mut journal, _) = LifecycleJournal::open(&home.path(), JournalOpenMode::Create).unwrap();
    std::fs::write(home.path(), b"independent owner file").unwrap();
    let original = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    assert_eq!(
        journal.commit(original.snapshot()),
        Err(AgentRunError::PersistenceUnavailable)
    );
    assert_eq!(
        std::fs::read(home.path()).unwrap(),
        b"independent owner file"
    );
}

#[test]
fn writer_rejects_same_sequence_drift_without_claiming_restart_rollback_protection() {
    let home = Home::new();
    let mut owner = create(&home);
    rewrite_valid_checksum(&home, |state| state.accepting_runs = false);
    assert_eq!(
        owner.start_run(100, snapshot("run.1")),
        Err(AgentRunError::PersistenceUnavailable)
    );
    assert!(owner.run("run.1").is_none());
}

#[test]
fn unsafe_snapshot_inode_and_permissions_are_rejected() {
    for kind in 0..4 {
        let home = Home::new();
        let owner = create(&home);
        drop(owner);
        match kind {
            0 => {
                std::fs::set_permissions(home.path(), std::fs::Permissions::from_mode(0o644))
                    .unwrap();
            }
            1 => {
                std::fs::hard_link(home.path(), home.0.join("alias")).unwrap();
            }
            2 => {
                std::fs::rename(home.path(), home.0.join("actual")).unwrap();
                std::os::unix::fs::symlink(home.0.join("actual"), home.path()).unwrap();
            }
            3 => {
                std::fs::remove_file(home.path()).unwrap();
                assert!(
                    std::process::Command::new("mkfifo")
                        .arg(home.path())
                        .status()
                        .unwrap()
                        .success()
                );
            }
            _ => unreachable!(),
        }
        assert!(
            AgentRunCoordinator::open_journaled(
                composition(),
                &home.path(),
                JournalOpenMode::Reopen
            )
            .is_err(),
            "kind {kind}"
        );
    }
}

#[test]
fn maximum_retained_shape_leaves_room_for_durable_cancellation() {
    let home = Home::new();
    let mut config = composition();
    config.max_active_runs = 256;
    let mut owner =
        AgentRunCoordinator::open_journaled(config, &home.path(), JournalOpenMode::Create).unwrap();
    let reason = "\u{1}".repeat(MAX_CANCEL_REASON_BYTES);
    // Reachable worst-size fixture: 256 attached active records and 768 already
    // cancelled records. Every cancellation reason requires JSON escaping.
    for index in 0..MAX_RETAINED_RUNS {
        let id = format!("{}{:010}", "r".repeat(118), index);
        let closed = index >= 256;
        owner.runs.insert(
            id.clone(),
            RunRecord {
                snapshot: snapshot(&id),
                revision: if closed { 3 } else { 2 },
                phase: if closed {
                    RunPhase::Cancelled
                } else {
                    RunPhase::ContextAttached
                },
                context_digest: Some("7".repeat(64)),
                compilation_receipt_digest: Some("8".repeat(64)),
                cancel_reason: closed.then(|| reason.clone()),
                cancel_ack_deadline_ms: None,
            },
        );
    }
    assert_eq!(owner.begin_drain(200, &reason), Ok(0));
    assert!(std::fs::metadata(home.path()).unwrap().len() < 8 * 1024 * 1024);
    let expected = owner.snapshot();
    drop(owner);
    let mut config = composition();
    config.max_active_runs = 256;
    let owner =
        AgentRunCoordinator::open_journaled(config, &home.path(), JournalOpenMode::Reopen).unwrap();
    assert_eq!(owner.snapshot(), expected);
    assert!(!owner.admissions_open());
}

#[test]
fn standalone_admission_close_survives_reopen() {
    let home = Home::new();
    let mut owner = create(&home);
    owner.close_admissions();
    drop(owner);
    assert!(!reopen(&home).admissions_open());
}

#[test]
fn cancellation_timeout_matches_original_owner_even_when_request_is_rejected() {
    let home = Home::new();
    let mut durable = create(&home);
    let mut original = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    for owner in [&mut durable, &mut original] {
        let context = attached(owner);
        let dispatch = owner
            .mark_dispatched(300, "run.1", context.revision)
            .unwrap();
        let (_, pending) = owner
            .cancel_run(400, "run.1", dispatch.revision, "stop")
            .unwrap();
        assert_eq!(
            owner.cancel_run(3400, "run.1", pending.revision, "stop"),
            Err(AgentRunError::InvalidTransition)
        );
    }
    assert_eq!(durable.run("run.1"), original.run("run.1"));
    drop(durable);
    assert_eq!(reopen(&home).run("run.1"), original.run("run.1"));
}

#[test]
fn failed_standalone_close_fences_local_owner_without_claiming_durable_success() {
    for after_publish in [false, true] {
        let home = Home::new();
        let mut owner = create(&home);
        let journal = owner.journal.as_mut().unwrap();
        journal.fail_before_publish = !after_publish;
        journal.fail_after_publish = after_publish;
        owner.close_admissions();
        assert!(!owner.admissions_open());
        assert!(owner.journal.as_ref().unwrap().poisoned);
        assert_eq!(
            owner.start_run(100, snapshot("run.1")),
            Err(AgentRunError::PersistenceUnavailable)
        );
        drop(owner);
        assert_eq!(reopen(&home).admissions_open(), !after_publish);
    }
}

#[test]
fn rejected_timeout_requests_do_not_commit_partial_or_unvalidated_changes() {
    let home = Home::new();
    let mut owner = create(&home);
    let context = attached(&mut owner);
    let dispatch = owner
        .mark_dispatched(300, "run.1", context.revision)
        .unwrap();
    let (_, pending) = owner
        .cancel_run(400, "run.1", dispatch.revision, "stop")
        .unwrap();
    let before = owner.snapshot();
    let bytes = std::fs::read(home.path()).unwrap();
    assert_eq!(
        owner.cancel_run(3400, "run.1", pending.revision - 1, "stop"),
        Err(AgentRunError::StaleRevision)
    );
    assert_eq!(
        owner.cancel_run(3400, "run.1", pending.revision, ""),
        Err(AgentRunError::InvalidCancelReason)
    );
    assert_eq!(owner.snapshot(), before);
    assert_eq!(std::fs::read(home.path()).unwrap(), bytes);
    owner.runs.get_mut("run.1").unwrap().revision = u64::MAX;
    let before = owner.snapshot();
    assert_eq!(
        owner.cancel_run(3400, "run.1", u64::MAX, "stop"),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(owner.snapshot(), before);
    assert_eq!(std::fs::read(home.path()).unwrap(), bytes);
}

#[path = "lane_b_instance_tests.rs"]
mod instance_tests;
