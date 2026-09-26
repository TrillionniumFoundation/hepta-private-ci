//! Stable failure disposition shared by the scheduler host and qualification.
//!
//! Classification does not grant retry authority. The durable occurrence,
//! provider identity and final-use contracts still decide whether work can be
//! retried; `Reconcile` explicitly forbids blind redispatch.

use crate::AutomationError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationFailureDisposition {
    FailStop,
    Retry,
    Isolate,
    Reconcile,
}

#[must_use]
pub const fn classify_automation_error(error: &AutomationError) -> AutomationFailureDisposition {
    match error {
        AutomationError::AccessDenied | AutomationError::TimerFenced | AutomationError::Corrupt => {
            AutomationFailureDisposition::FailStop
        }
        AutomationError::Unavailable | AutomationError::Dispatch => {
            AutomationFailureDisposition::Retry
        }
        AutomationError::Invalid | AutomationError::Conflict => {
            AutomationFailureDisposition::Isolate
        }
        AutomationError::DispatchUnknown => AutomationFailureDisposition::Reconcile,
    }
}

/// Bounded host retry delay. Attempt 1 starts at 250 ms and the delay caps at
/// four seconds; it never applies to an unknown provider outcome.
#[must_use]
pub const fn bounded_automation_retry_delay_ms(consecutive_attempt: u8) -> u64 {
    match consecutive_attempt {
        0 | 1 => 250,
        2 => 500,
        3 => 1_000,
        4 => 2_000,
        _ => 4_000,
    }
}
