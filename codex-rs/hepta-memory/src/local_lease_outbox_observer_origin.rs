//! Persist observer origin separately from unrestricted ACK receipt strings.
//!
//! Event IDs are generated internally and included in the immutable event
//! digest. Legacy IDs remain readable, but cannot prove observer origin.

use super::LocalLeaseOutboxError;
use super::corrupt;
use super::journal_row_id;

pub(super) fn observer_event_id(lease_id: &str, sequence: u64) -> String {
    journal_row_id("observed-event", lease_id, sequence)
}

pub(super) fn is_observer_event(
    lease_id: &str,
    sequence: u64,
    event_id: &str,
    kind: &str,
    payload: &str,
) -> bool {
    event_id == observer_event_id(lease_id, sequence)
        && matches!(
            (kind, payload),
            ("reconcile_committed", "committed")
                | ("reconcile_rejected", "rejected")
                | ("reconcile_still_indeterminate", "still_indeterminate")
        )
}

pub(super) fn verify_observer_event_origin(
    lease_id: &str,
    sequence: u64,
    event_id: &str,
    kind: &str,
    payload: &str,
) -> Result<(), LocalLeaseOutboxError> {
    if event_id.starts_with("observed-event:")
        && !is_observer_event(lease_id, sequence, event_id, kind, payload)
    {
        return Err(corrupt(
            "observer event ID, kind or payload is not canonical",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "local_lease_outbox_observer_origin_tests.rs"]
mod tests;
