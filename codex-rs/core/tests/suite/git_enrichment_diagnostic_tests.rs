use codex_core::CodexThread;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::TurnAbortReason;
use core_test_support::wait_for_event;

#[derive(Debug, Default)]
struct ObservedEvents {
    total: u64,
    started: u64,
    errors: u64,
    aborted: u64,
    last_error_bytes: Option<usize>,
    last_error_has_info: bool,
    last_abort: Option<&'static str>,
    complete_has_error: Option<bool>,
    complete_error_bytes: Option<usize>,
}

// Delegate every wait and normal finish-owner observation to the original helper.
// The closure only records bounded diagnostics; it adds no deadline or await.
pub(super) async fn wait_for_ephemeral_turn(
    codex: &CodexThread,
    request_counts: impl Fn() -> (usize, Vec<usize>),
) {
    let mut observed = ObservedEvents::default();
    let mut reported_failures = 0;
    let report = |stage: &str, observed: &ObservedEvents| {
        let (connections, counts) = request_counts();
        format!(
            "ephemeral prewarm: stage={stage} events={observed:?} connections={connections} requests_first4={counts:?}"
        )
    };
    eprintln!("{}", report("before_original_wait", &observed));
    wait_for_event(codex, |event| {
        observed.total = observed.total.saturating_add(1);
        let failure = match event {
            EventMsg::TurnStarted(_) => {
                observed.started = observed.started.saturating_add(1);
                false
            }
            EventMsg::Error(error) => {
                observed.errors = observed.errors.saturating_add(1);
                observed.last_error_bytes = Some(error.message.len());
                observed.last_error_has_info = error.codex_error_info.is_some();
                true
            }
            EventMsg::TurnAborted(aborted) => {
                observed.aborted = observed.aborted.saturating_add(1);
                observed.last_abort = Some(match &aborted.reason {
                    TurnAbortReason::Interrupted => "interrupted",
                    TurnAbortReason::Replaced => "replaced",
                    TurnAbortReason::ReviewEnded => "review_ended",
                    TurnAbortReason::BudgetLimited => "budget_limited",
                });
                true
            }
            EventMsg::TurnComplete(completed) => {
                observed.complete_has_error = Some(completed.error.is_some());
                observed.complete_error_bytes =
                    completed.error.as_ref().map(|error| error.message.len());
                eprintln!("{}", report("turn_complete_received", &observed));
                return true;
            }
            _ => false,
        };
        if failure && reported_failures < 4 {
            reported_failures += 1;
            eprintln!("{}", report("error_or_abort_received", &observed));
        }
        false
    })
    .await;
    // Only categories, lengths, and counts are emitted, never error text,
    // model inputs, outputs, or thread IDs.
    eprintln!("{}", report("original_finish_observed", &observed));
}
