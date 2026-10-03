use super::*;
use crate::plasticity_runtime::input_context::permits_refresh;

#[test]
fn fresh_reservation_allows_context_but_original_pending_and_completed_g_do_not() {
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let permit = rounds
        .reserve(
            StableId::new("goal.context").expect("id"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("actual reservation");
    let current = rounds.current_status().expect("view").expect("round");
    assert!(permits_refresh(&current, &permit));
    let request = request(&permit);
    rounds
        .begin(&permit, &request, 1001)
        .expect("actual model intent");
    let pending = rounds.current_status().expect("view").expect("round");
    assert!(!permits_refresh(&pending, &permit));
    rounds
        .complete(&permit, &request, &assessment(&request))
        .expect("actual terminal");
    let completed = rounds.current_status().expect("view").expect("round");
    assert!(!permits_refresh(&completed, &permit));
}

#[test]
fn terminal_candidate_with_actual_pending_stage_keeps_context_until_original_task_retires() {
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let permit = rounds
        .reserve(
            StableId::new("goal.context").expect("id"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("reserve");
    let request = request(&permit);
    rounds.begin(&permit, &request, 1001).expect("begin");
    rounds
        .complete(&permit, &request, &assessment(&request))
        .expect("terminal G");
    let record = rejected(&mut rounds, b"candidate.context");
    rounds
        .record_phase(&record)
        .expect("original candidate terminal");
    let terminal = rounds.current_status().expect("view").expect("round");
    assert!(permits_refresh(&terminal, &permit));
    let mut pending = terminal.clone();
    pending.has_pending_model_requests = true;
    assert!(!permits_refresh(&pending, &permit));
    assert_eq!(rounds.current_status().expect("unchanged"), Some(terminal));
}
