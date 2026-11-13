use super::classify_destination_absence;
use codex_hepta_automation::AutomationError;
use codex_hepta_operations::ReconciliationOutcome;

#[test]
fn validation_and_access_error_labels_do_not_prove_absence() {
    for error in [AutomationError::Invalid, AutomationError::AccessDenied] {
        let (outcome, _) = classify_destination_absence(&error);
        assert_eq!(outcome, ReconciliationOutcome::Quarantined);
    }
}

#[test]
fn uncertain_owner_paths_are_quarantined_and_have_reason_bound_evidence() {
    let errors = [
        AutomationError::Invalid,
        AutomationError::AccessDenied,
        AutomationError::Conflict,
        AutomationError::Corrupt,
        AutomationError::TimerFenced,
        AutomationError::Unavailable,
        AutomationError::Dispatch,
        AutomationError::DispatchUnknown,
    ];
    let mut digests = std::collections::BTreeSet::new();
    for error in errors {
        let (outcome, digest) = classify_destination_absence(&error);
        assert_eq!(outcome, ReconciliationOutcome::Quarantined);
        assert!(!digest.is_zero());
        assert!(digests.insert(digest));
    }
}
