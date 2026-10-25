use super::super::super::instance::InstanceMutation;
use super::super::super::instance::InstanceReceipt;
use super::*;

fn protected(home: &Home, mode: JournalOpenMode) -> Result<AgentRunCoordinator, AgentRunError> {
    AgentRunCoordinator::open_instance_journaled(composition(), &home.path(), mode)
}
fn start(
    owner: &mut AgentRunCoordinator,
    operation: &str,
) -> Result<InstanceReceipt, AgentRunError> {
    owner.start_instance(/*now_ms*/ 100, operation, snapshot("run.1"))
}

#[test]
fn create_retry_release_and_recreate_never_alias_or_resurrect() {
    let home = Home::new();
    let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
    let first = start(&mut owner, "create.1").unwrap();
    let retry = start(&mut owner, "create.1").unwrap();
    assert_eq!(retry.handle, first.handle);
    assert!(retry.receipt.idempotent);
    assert_eq!(
        owner.start_run(/*now_ms*/ 100, snapshot("run.1")),
        Err(AgentRunError::InstanceRequired)
    );
    let (_, cancelled) = owner
        .cancel_instance(&first.handle, /*now_ms*/ 110, "stop")
        .unwrap();
    let (_, released) = owner
        .mutate_instance(
            &cancelled.handle,
            /*now_ms*/ 0,
            InstanceMutation::Release,
        )
        .unwrap();
    assert!(released.released);
    let second = start(&mut owner, "create.2").unwrap();
    assert_ne!(second.handle.key, first.handle.key);
    assert_eq!(second.handle.revision, first.handle.revision);
    assert_eq!(
        owner.cancel_instance(&first.handle, /*now_ms*/ 120, "stale"),
        Err(AgentRunError::StaleInstance)
    );
    let replay = start(&mut owner, "create.1").unwrap();
    assert!(replay.released && replay.receipt.idempotent);
    assert_eq!(replay.handle.key, first.handle.key);
    assert_eq!(
        owner.reconcile_instance(&second.handle.key).unwrap(),
        second
    );
}

#[test]
fn reopen_rotates_activation_without_replacing_stable_instance() {
    let home = Home::new();
    let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
    let first = start(&mut owner, "create.1").unwrap();
    drop(owner);
    let mut owner = protected(&home, JournalOpenMode::Reopen).unwrap();
    let recovered = owner.reconcile_instance(&first.handle.key).unwrap();
    assert_eq!(recovered.handle.key, first.handle.key);
    assert_eq!(recovered.receipt, first.receipt);
    assert_eq!(recovered.handle.activation, first.handle.activation + 1);
    assert_eq!(
        owner.cancel_instance(&first.handle, /*now_ms*/ 120, "old activation"),
        Err(AgentRunError::StaleActivation)
    );
    assert!(
        owner
            .cancel_instance(&recovered.handle, /*now_ms*/ 120, "new activation")
            .is_ok()
    );
    assert_eq!(
        AgentRunCoordinator::open_journaled(composition(), &home.path(), JournalOpenMode::Reopen)
            .unwrap_err(),
        AgentRunError::PersistenceUnavailable
    );
    drop(owner);
    assert!(matches!(
        AgentRunCoordinator::open_journaled(composition(), &home.path(), JournalOpenMode::Reopen),
        Err(AgentRunError::InstanceRequired)
    ));
}

#[test]
fn uncertain_allocation_never_retries_from_live_stale_memory() {
    for after_publish in [false, true] {
        let home = Home::new();
        let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
        owner.journal.as_mut().unwrap().fail_before_publish = !after_publish;
        owner.journal.as_mut().unwrap().fail_after_publish = after_publish;
        assert_eq!(
            owner.start_instance(/*now_ms*/ 100, "create.1", snapshot("run.1")),
            Err(AgentRunError::PersistenceUnavailable)
        );
        assert!(owner.run("run.1").is_none());
        assert_eq!(
            owner.start_instance(/*now_ms*/ 100, "create.2", snapshot("run.1")),
            Err(AgentRunError::PersistenceUnavailable)
        );
        drop(owner);
        let mut owner = protected(&home, JournalOpenMode::Reopen).unwrap();
        let recovered = start(&mut owner, "create.1").unwrap();
        assert_eq!(recovered.handle.key.sequence, 1);
        assert_eq!(recovered.receipt.idempotent, after_publish);
    }
}

#[test]
fn invalid_start_and_wrong_snapshot_do_not_consume_identity() {
    let home = Home::new();
    let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
    let mut invalid = snapshot("run.1");
    invalid.deadline_ms = 99;
    assert!(
        owner
            .start_instance(/*now_ms*/ 100, "create.1", invalid)
            .is_err()
    );
    let first = start(&mut owner, "create.1").unwrap();
    assert_eq!(first.handle.key.sequence, 1);
    let mut different = snapshot("run.1");
    different.request_digest = "e".repeat(64);
    assert_eq!(
        owner.start_instance(/*now_ms*/ 100, "create.1", different),
        Err(AgentRunError::Conflict)
    );
    let mut forged = first.handle.clone();
    forged.key.lineage = "f".repeat(64);
    assert_eq!(
        owner.cancel_instance(&forged, /*now_ms*/ 110, "forged"),
        Err(AgentRunError::StaleInstance)
    );
    assert_eq!(owner.reconcile_instance(&first.handle.key).unwrap(), first);
}

#[test]
fn protected_cancel_preserves_completed_timeout_but_not_invalid_errors() {
    let home = Home::new();
    let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
    let first = start(&mut owner, "create.1").unwrap();
    let (_, attached) = owner
        .mutate_instance(
            &first.handle,
            /*now_ms*/ 110,
            InstanceMutation::Attach(Box::new(attachment())),
        )
        .unwrap();
    let (_, dispatched) = owner
        .mutate_instance(
            &attached.handle,
            /*now_ms*/ 120,
            InstanceMutation::Dispatch,
        )
        .unwrap();
    let (_, cancelled) = owner
        .cancel_instance(&dispatched.handle, /*now_ms*/ 130, "cancel")
        .unwrap();
    assert_eq!(
        owner.cancel_instance(&cancelled.handle, /*now_ms*/ 4_000, ""),
        Err(AgentRunError::InvalidCancelReason)
    );
    assert_eq!(
        owner.reconcile_instance(&cancelled.handle.key).unwrap(),
        cancelled
    );
    assert_eq!(
        owner.cancel_instance(&cancelled.handle, /*now_ms*/ 4_000, "cancel"),
        Err(AgentRunError::InvalidTransition)
    );
    let uncertain = owner.reconcile_instance(&cancelled.handle.key).unwrap();
    assert_eq!(uncertain.receipt.phase, RunPhase::Indeterminate);
    assert_eq!(uncertain.handle.revision, cancelled.handle.revision + 1);
    drop(owner);
    let mut owner = protected(&home, JournalOpenMode::Reopen).unwrap();
    let recovered = owner.reconcile_instance(&uncertain.handle.key).unwrap();
    assert_eq!(recovered.receipt, uncertain.receipt);
    let (terminal, bound) = owner
        .mutate_instance(
            &recovered.handle,
            /*now_ms*/ 0,
            InstanceMutation::Observe {
                phase: RunPhase::Cancelled,
                terminal_observed: true,
            },
        )
        .unwrap();
    assert_eq!(terminal.phase, RunPhase::Cancelled);
    assert_eq!(terminal, bound.receipt);
}

#[test]
fn checksum_valid_missing_history_and_activation_overflow_are_rejected() {
    for change in [
        "history",
        "activation",
        "mode",
        "issued_zero",
        "issued_future",
    ] {
        let home = Home::new();
        let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
        start(&mut owner, "create.1").unwrap();
        drop(owner);
        rewrite_valid_checksum(&home, |snapshot| {
            let mut value = serde_json::to_value(&snapshot.instances).unwrap();
            match change {
                "history" => value["operations"] = serde_json::json!({}),
                "activation" => value["activation"] = serde_json::json!(u64::MAX),
                "mode" => value = serde_json::Value::Null,
                "issued_zero" => {
                    value["operations"]["create.1"]["issued_activation"] = serde_json::json!(0)
                }
                "issued_future" => {
                    value["operations"]["create.1"]["issued_activation"] = serde_json::json!(2)
                }
                _ => unreachable!(),
            }
            snapshot.instances = serde_json::from_value(value).unwrap();
        });
        assert!(
            AgentRunCoordinator::open_instance_journaled(
                composition(),
                &home.path(),
                JournalOpenMode::Reopen
            )
            .is_err()
        );
    }
}

#[test]
fn bounded_creation_history_rejects_new_work_without_evicting_replay() {
    let home = Home::new();
    let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
    let first = start(&mut owner, "create.1").unwrap();
    let (_, cancelled) = owner
        .cancel_instance(&first.handle, /*now_ms*/ 110, "stop")
        .unwrap();
    owner
        .mutate_instance(
            &cancelled.handle,
            /*now_ms*/ 0,
            InstanceMutation::Release,
        )
        .unwrap();
    drop(owner);
    rewrite_valid_checksum(&home, |snapshot| {
        let mut book = serde_json::to_value(&snapshot.instances).unwrap();
        let original = book["operations"]["create.1"].clone();
        let mut operations = serde_json::Map::new();
        for sequence in 1..=1_024_u64 {
            let mut entry = original.clone();
            entry["sequence"] = serde_json::json!(sequence);
            operations.insert(format!("create.{sequence}"), entry);
        }
        book["operations"] = serde_json::Value::Object(operations);
        book["allocated"] = serde_json::json!(1_024_u64);
        snapshot.instances = serde_json::from_value(book).unwrap();
    });
    let mut owner = protected(&home, JournalOpenMode::Reopen).unwrap();
    assert_eq!(
        owner.start_instance(/*now_ms*/ 100, "create.1025", snapshot("run.1")),
        Err(AgentRunError::CapacityExceeded)
    );
    let old = start(&mut owner, "create.1").unwrap();
    assert!(old.released && old.receipt.idempotent);
    assert_eq!(old.handle.key, first.handle.key);
}

#[test]
fn every_legacy_record_mutator_rejects_populated_protected_owner() {
    let home = Home::new();
    let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
    let first = start(&mut owner, "create.1").unwrap();
    assert_eq!(
        owner.attach_context(
            /*now_ms*/ 110,
            /*expected_revision*/ 1,
            attachment()
        ),
        Err(AgentRunError::InstanceRequired)
    );
    assert_eq!(
        owner.mark_dispatched(/*now_ms*/ 120, "run.1", /*expected_revision*/ 1),
        Err(AgentRunError::InstanceRequired)
    );
    assert_eq!(
        owner.cancel_run(
            /*now_ms*/ 120, "run.1", /*expected_revision*/ 1, "legacy"
        ),
        Err(AgentRunError::InstanceRequired)
    );
    assert_eq!(
        owner.observe_terminal(
            "run.1",
            /*expected_revision*/ 1,
            RunPhase::Cancelled,
            /*terminal_observed*/ true
        ),
        Err(AgentRunError::InstanceRequired)
    );
    assert_eq!(
        owner.remove_closed_run("run.1", /*expected_revision*/ 1),
        Err(AgentRunError::InstanceRequired)
    );
    assert_eq!(
        owner.recover_indeterminate(RunRecovery {
            snapshot: snapshot("run.1"),
            revision: 1,
            context_digest: "7".repeat(64),
            compilation_receipt_digest: "8".repeat(64),
            cancel_reason: None
        }),
        Err(AgentRunError::InstanceRequired)
    );
    assert_eq!(owner.reconcile_instance(&first.handle.key).unwrap(), first);
}

#[test]
fn legacy_qualification_schema_is_not_silently_upgraded() {
    let home = Home::new();
    drop(protected(&home, JournalOpenMode::Create).unwrap());
    use sha2::Digest;
    let document: Document = serde_json::from_slice(&std::fs::read(home.path()).unwrap()).unwrap();
    // Reconstruct the exact old field order and schema-1 checksum domain,
    // including the absence of identity metadata, not a corrupted schema-2 file.
    let snapshot_json = format!(
        "{{\"composition\":{},\"runs\":{},\"accepting_runs\":{}}}",
        serde_json::to_string(&document.snapshot.composition).unwrap(),
        serde_json::to_string(&document.snapshot.runs).unwrap(),
        document.snapshot.accepting_runs,
    );
    let checksum = format!(
        "{:x}",
        sha2::Sha256::digest(format!("[1,{},{}]", document.sequence, snapshot_json).as_bytes())
    );
    let old_document = format!(
        "{{\"schema\":1,\"sequence\":{},\"snapshot\":{},\"checksum\":\"{}\"}}",
        document.sequence, snapshot_json, checksum
    );
    std::fs::write(home.path(), old_document).unwrap();
    assert!(
        AgentRunCoordinator::open_instance_journaled(
            composition(),
            &home.path(),
            JournalOpenMode::Reopen
        )
        .is_err()
    );
}

#[test]
fn activation_reopen_lost_ack_never_exposes_or_revives_old_handle() {
    for fault in [RecoveryFault::BeforePublish, RecoveryFault::AfterPublish] {
        let home = Home::new();
        let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
        let old = start(&mut owner, "create.1").unwrap();
        drop(owner);
        assert!(matches!(
            AgentRunCoordinator::open_journaled_with_recovery_fault(
                composition(),
                &home.path(),
                JournalOpenMode::Reopen,
                super::super::super::instance::InstanceMode::Protected,
                fault,
            ),
            Err(AgentRunError::PersistenceUnavailable)
        ));
        let document: serde_json::Value =
            serde_json::from_slice(&std::fs::read(home.path()).unwrap()).unwrap();
        let expected =
            old.handle.activation + u64::from(matches!(fault, RecoveryFault::AfterPublish));
        assert_eq!(
            document["snapshot"]["instances"]["activation"],
            serde_json::json!(expected)
        );
        let mut owner = protected(&home, JournalOpenMode::Reopen).unwrap();
        let reconciled = owner.reconcile_instance(&old.handle.key).unwrap();
        assert_eq!(reconciled.handle.activation, expected + 1);
        assert_eq!(reconciled.handle.key, old.handle.key);
        assert_eq!(
            owner.cancel_instance(&old.handle, /*now_ms*/ 120, "stale"),
            Err(AgentRunError::StaleActivation)
        );
    }
}

#[test]
fn lost_create_reply_recovers_key_without_refreshing_control_activation() {
    let home = Home::new();
    let mut owner = protected(&home, JournalOpenMode::Create).unwrap();
    owner.journal.as_mut().unwrap().fail_after_publish = true;
    assert_eq!(
        owner.start_instance(/*now_ms*/ 100, "create.1", snapshot("run.1")),
        Err(AgentRunError::PersistenceUnavailable)
    );
    drop(owner);
    let mut owner = protected(&home, JournalOpenMode::Reopen).unwrap();
    let replay = start(&mut owner, "create.1").unwrap();
    assert!(replay.receipt.idempotent);
    let current = owner.reconcile_instance(&replay.handle.key).unwrap();
    assert_eq!(current.handle.key, replay.handle.key);
    assert_eq!(current.handle.activation, replay.handle.activation + 1);
    assert_eq!(current.handle.revision, replay.handle.revision);
    assert_eq!(
        owner.cancel_instance(&replay.handle, /*now_ms*/ 120, "retry"),
        Err(AgentRunError::StaleActivation)
    );
    let (_, cancelled) = owner
        .cancel_instance(&current.handle, /*now_ms*/ 120, "reconciled")
        .unwrap();
    owner
        .mutate_instance(
            &cancelled.handle,
            /*now_ms*/ 0,
            InstanceMutation::Release,
        )
        .unwrap();
    drop(owner);
    let mut owner = protected(&home, JournalOpenMode::Reopen).unwrap();
    let retired = start(&mut owner, "create.1").unwrap();
    assert!(retired.released && retired.receipt.idempotent);
    assert_eq!(retired.handle.activation, replay.handle.activation);
    assert_eq!(retired.handle.key, replay.handle.key);
    assert!(owner.run("run.1").is_none());
}
