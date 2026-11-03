use super::*;
use pretty_assertions::assert_eq;

fn pending(index: usize) -> OperationView {
    OperationView {
        operation_id: format!("operation-{index:04}"),
        semantic_digest: "a".repeat(64),
        target_id: "runtime.agentd".to_owned(),
        state: OperationState::Pending,
        audit_trace_id: None,
        terminal_status: None,
        outcome_digest: None,
        generation: 1,
        displayed_revision: 1,
        created_at: 1000,
        updated_at: 1000,
    }
}

#[test]
fn recovery_rotation_reaches_tail_while_earlier_records_are_backed_off() {
    let mut schedule = RecoverySchedule::default();
    let operations: Vec<_> = (0..70).map(pending).collect();
    let first = schedule
        .select(&operations, /*now*/ 1000, /*limit*/ 32)
        .unwrap();
    assert_eq!(
        first,
        operations[..32]
            .iter()
            .map(|view| view.operation_id.clone())
            .collect::<Vec<_>>()
    );
    for id in &first {
        schedule
            .record(id, /*now*/ 1000, /*terminal*/ false)
            .unwrap();
    }
    let second = schedule
        .select(&operations, /*now*/ 1000, /*limit*/ 32)
        .unwrap();
    assert_eq!(
        second,
        operations[32..64]
            .iter()
            .map(|view| view.operation_id.clone())
            .collect::<Vec<_>>()
    );
    for id in &second {
        schedule
            .record(id, /*now*/ 1000, /*terminal*/ false)
            .unwrap();
    }
    let last = schedule
        .select(&operations, /*now*/ 1000, /*limit*/ 32)
        .unwrap();
    assert_eq!(
        last,
        operations[64..]
            .iter()
            .map(|view| view.operation_id.clone())
            .collect::<Vec<_>>()
    );
}

#[test]
fn recovery_backoff_is_exponential_bounded_and_pruned_on_completion_or_removal() {
    let mut schedule = RecoverySchedule::default();
    let operations = vec![pending(0)];
    let id = operations[0].operation_id.clone();
    let mut now = 1000;
    for delay in [1000, 2000, 4000, 8000, 16000, 32000, 60000, 60000] {
        schedule.record(&id, now, /*terminal*/ false).unwrap();
        assert_eq!(
            schedule.select(&operations, now + delay - 1, /*limit*/ 1),
            Ok(vec![])
        );
        assert_eq!(
            schedule.select(&operations, now + delay, /*limit*/ 1),
            Ok(vec![id.clone()])
        );
        now += delay;
    }
    schedule.record(&id, now, /*terminal*/ true).unwrap();
    assert_eq!(
        schedule.select(&operations, now, /*limit*/ 1),
        Ok(vec![id.clone()])
    );
    schedule.record(&id, now, /*terminal*/ false).unwrap();
    assert_eq!(schedule.select(&[], now, /*limit*/ 1), Ok(vec![]));
    assert!(schedule.backoff.is_empty());
}

#[test]
fn recovery_scheduler_has_hard_inventory_and_backoff_bounds() {
    let mut schedule = RecoverySchedule::default();
    let operations = vec![pending(0), pending(0)];
    assert_eq!(
        schedule.select(&operations, /*now*/ 1000, /*limit*/ 2),
        Err(ControlError::new(ErrorCode::InvalidInput))
    );
    for limit in [0, 129] {
        assert_eq!(
            schedule.select(&[], /*now*/ 1000, limit),
            Err(ControlError::new(ErrorCode::InvalidInput))
        );
    }
    assert_eq!(
        schedule.select(&vec![pending(0); 4097], /*now*/ 1000, /*limit*/ 1),
        Err(ControlError::new(ErrorCode::InvalidInput))
    );
    for index in 0..4096 {
        schedule
            .record(
                &format!("operation-{index}"),
                /*now*/ 1000,
                /*terminal*/ false,
            )
            .unwrap();
    }
    assert_eq!(
        schedule.record(
            "operation-overflow",
            /*now*/ 1000,
            /*terminal*/ false
        ),
        Err(ControlError::new(ErrorCode::PendingLimit))
    );
    assert_eq!(schedule.backoff.len(), 4096);
    assert_eq!(
        schedule.record("bad/id", /*now*/ 1000, /*terminal*/ false),
        Err(ControlError::new(ErrorCode::InvalidInput))
    );
}

#[test]
fn recovery_skips_inflight_entries_and_saturates_time_arithmetic() {
    let mut schedule = RecoverySchedule::default();
    let mut submitting = pending(0);
    submitting.state = OperationState::Submitting;
    assert_eq!(
        schedule.select(
            &[submitting, pending(1)],
            /*now*/ 1000,
            /*limit*/ 32
        ),
        Ok(vec!["operation-0001".to_owned()])
    );
    schedule
        .record("operation-0001", u64::MAX - 1, /*terminal*/ false)
        .unwrap();
    assert_eq!(
        schedule.select(&[pending(1)], u64::MAX - 1, /*limit*/ 32),
        Ok(vec![])
    );
    assert_eq!(
        schedule.select(&[pending(1)], u64::MAX, /*limit*/ 32),
        Ok(vec!["operation-0001".to_owned()])
    );
}

#[test]
fn session_renewal_does_not_spin_and_backoff_never_outlives_expiry() {
    let mut schedule = SessionSchedule::default();
    assert_eq!(
        schedule.delay_ms(/*expires*/ 300_000, /*now*/ 1000),
        239_000
    );
    assert_eq!(schedule.delay_ms(/*expires*/ 2000, /*now*/ 1000), 1000);
    assert_eq!(schedule.delay_ms(/*expires*/ 1001, /*now*/ 1000), 1);
    assert_eq!(schedule.delay_ms(/*expires*/ 1000, /*now*/ 1000), 0);
    for expected in [1000, 2000, 4000, 8000, 16000, 32000, 60000, 60000] {
        schedule.failed();
        assert_eq!(
            schedule.delay_ms(/*expires*/ 1_000_000, /*now*/ 1000),
            expected
        );
    }
    assert_eq!(schedule.delay_ms(/*expires*/ 1500, /*now*/ 1000), 500);
    schedule.succeeded();
    assert_eq!(
        schedule.delay_ms(/*expires*/ u64::MAX, /*now*/ 0),
        2_147_000_000
    );
}
