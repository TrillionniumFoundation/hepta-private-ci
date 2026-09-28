impl OwnerOperationalState {
    pub(super) fn recovery_required(&self) -> Option<&StableId> {
        match &self.recovery {
            RecoveryState::Clear => None,
            RecoveryState::Required { operation_id, .. } => Some(operation_id),
        }
    }

    pub(super) fn require_recovery(&mut self, operation_id: StableId, now: u64) {
        match &self.recovery {
            RecoveryState::Required {
                operation_id: current,
                ..
            } if current == &operation_id => {}
            _ => {
                self.recovery = RecoveryState::Required {
                    operation_id,
                    since: now,
                };
            }
        }
    }

    pub(super) fn clear_recovery(&mut self, operation_id: &StableId) {
        if matches!(
            &self.recovery,
            RecoveryState::Required {
                operation_id: current,
                ..
            } if current == operation_id
        ) {
            self.recovery = RecoveryState::Clear;
        }
    }

}
