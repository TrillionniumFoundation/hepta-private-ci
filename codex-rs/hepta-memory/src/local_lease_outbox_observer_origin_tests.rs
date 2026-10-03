use super::*;

#[test]
fn observer_origin_rejects_wrong_identity_kind_and_payload_without_reinterpreting_legacy() {
    for lease_id in ["origin:lease".to_string(), "x".repeat(512)] {
        for sequence in [1, u64::MAX] {
            for (kind, payload) in [
                ("reconcile_committed", "committed"),
                ("reconcile_rejected", "rejected"),
                ("reconcile_still_indeterminate", "still_indeterminate"),
            ] {
                let observed = observer_event_id(&lease_id, sequence);
                assert!(observed.len() <= 512);
                assert!(is_observer_event(
                    &lease_id, sequence, &observed, kind, payload
                ));
                verify_observer_event_origin(&lease_id, sequence, &observed, kind, payload)
                    .expect("canonical observer origin");
                let legacy = journal_row_id("event", &lease_id, sequence);
                assert!(!is_observer_event(
                    &lease_id, sequence, &legacy, kind, payload
                ));
                verify_observer_event_origin(&lease_id, sequence, &legacy, kind, payload)
                    .expect("legacy IDs remain readable");
                let wrong_terminal_kind = if kind == "reconcile_committed" {
                    "reconcile_rejected"
                } else {
                    "reconcile_committed"
                };
                for (read_lease, read_sequence, read_kind, read_payload) in [
                    ("other:lease", sequence, kind, payload),
                    (lease_id.as_str(), sequence ^ 2, kind, payload),
                    (lease_id.as_str(), sequence, "admitted", payload),
                    (lease_id.as_str(), sequence, "indeterminate", payload),
                    (lease_id.as_str(), sequence, wrong_terminal_kind, payload),
                    (lease_id.as_str(), sequence, kind, "actual target receipt"),
                ] {
                    assert!(matches!(
                        verify_observer_event_origin(
                            read_lease,
                            read_sequence,
                            &observed,
                            read_kind,
                            read_payload,
                        ),
                        Err(LocalLeaseOutboxError::Corrupt(_))
                    ));
                }
            }
        }
    }
}
