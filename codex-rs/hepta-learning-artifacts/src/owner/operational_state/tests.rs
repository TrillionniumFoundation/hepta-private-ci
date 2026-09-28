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
}
