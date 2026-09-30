use super::*;
use pretty_assertions::assert_eq;

#[test]
fn counters_accumulate_saturate_and_keep_maximum_not_sum() {
    let mut window = TelemetryWindow::new();
    window.stats.claimed = u64::MAX;
    let mut first = OutboxDispatchStats {
        claimed: 1,
        transport_polls: 7,
        payload_digest_checks: 1,
        entered_authority_faults: 1,
        claim_to_first_poll_max_ms: 20,
        ..OutboxDispatchStats::default()
    };
    first.broker_latency.observe_ms(5);
    window.observe(&first, /*error*/ None);
    let mut second = OutboxDispatchStats {
        claimed: 2,
        transport_polls: 3,
        payload_digest_checks: 1,
        entered_authority_faults: 2,
        claim_to_first_poll_max_ms: 10,
        ..OutboxDispatchStats::default()
    };
    second.broker_latency.observe_ms(20);
    window.observe(&second, /*error*/ None);
    let mut expected = OutboxDispatchStats {
        claimed: u64::MAX,
        transport_polls: 10,
        payload_digest_checks: 2,
        entered_authority_faults: 3,
        claim_to_first_poll_max_ms: 20,
        ..OutboxDispatchStats::default()
    };
    expected.broker_latency.observe_ms(5);
    expected.broker_latency.observe_ms(20);
    assert_eq!(window.stats, expected);
}

#[test]
fn structured_failure_event_retains_entered_measurements_without_ids()
-> Result<(), Box<dyn std::error::Error>> {
    let mut window = TelemetryWindow::new();
    window.stats.entered_attempts = 1;
    window.stats.post_entry_failures = 1;
    window.stats.entered_persistence_faults = 1;
    window.stats.sqlite_latency.observe_ms(3);
    let event = window.event(Some(OutboxDispatchError::Store));
    assert_eq!(event["sender_status"], "store_unavailable");
    assert_eq!(event["counters"]["post_entry_failures"], 1);
    assert_eq!(event["counters"]["entered_persistence_faults"], 1);
    assert_eq!(event["counters"]["sqlite_latency"]["count"], 1);
    let object = event.as_object().ok_or("metrics object missing")?;
    assert_eq!(object.len(), 5);
    let counters = object["counters"].as_object().ok_or("counters missing")?;
    for (name, value) in counters {
        if name.ends_with("_latency") {
            assert!(
                value
                    .as_object()
                    .ok_or("histogram missing")?
                    .values()
                    .all(serde_json::Value::is_u64)
            );
        } else {
            assert!(value.is_u64() || value.is_boolean());
        }
    }
    Ok(())
}
