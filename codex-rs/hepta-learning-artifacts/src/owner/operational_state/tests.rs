#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    #[test]
    fn typed_transitions_distinguish_reconcile_refresh_and_drain() {
        let mut state = OwnerOperationalState::new(false, None, 10);
        state.begin_withdrawal_persist(11);
        assert!(matches!(
            state.require_current_view(),
            Err(LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown)
        ));
        state.finish_withdrawal_persist();
        state.require_recovery(id("attempt"), 12);
        assert!(matches!(
            state.require_operation(&id("other")),
            Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
        ));
        state.begin_drain_volatile(13);
        assert!(matches!(
            state.require_publish(&id("attempt"), false),
            Err(LearningArtifactOwnerServiceError::Draining)
        ));
        assert!(state.require_publish(&id("attempt"), true).is_ok());
    }

    #[test]
    fn cancelled_identity_persist_does_not_poison_reads_or_future_publication() {
        let mut state = OwnerOperationalState::new(false, None, 20);
        let operation_id = id("capacity-rejected-attempt");
        state.begin_request_identity_persist(operation_id.clone(), 21);
        assert!(matches!(
            state.require_current_view(),
            Err(
                LearningArtifactOwnerServiceError::RequestIdentityDurabilityUnknown(blocked)
            ) if blocked == operation_id
        ));

        state.cancel_request_identity_persist();

        assert!(state.require_current_view().is_ok());
        assert!(state.require_publish(&operation_id, false).is_ok());
        assert!(state.require_operation(&id("other-attempt")).is_ok());
    }
}
