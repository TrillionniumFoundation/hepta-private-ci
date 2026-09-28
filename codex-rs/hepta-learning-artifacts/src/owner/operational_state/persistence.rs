impl OwnerOperationalState {
    pub(super) fn begin_request_identity_persist(
        &mut self,
        operation_id: StableId,
        now: u64,
    ) {
        self.request_identity = RequestIdentityState::Persisting {
            operation_id,
            since: now,
        };
    }

    pub(super) fn finish_request_identity_persist(&mut self) {
        self.request_identity = RequestIdentityState::Clear;
    }

    pub(super) fn cancel_request_identity_persist(&mut self) {
        self.request_identity = RequestIdentityState::Clear;
    }

    pub(super) fn fail_request_identity_persist(
        &mut self,
        operation_id: StableId,
        now: u64,
    ) {
        self.request_identity = RequestIdentityState::Unknown {
            operation_id,
            since: now,
        };
    }

    pub(super) fn begin_withdrawal_persist(&mut self, now: u64) {
        self.withdrawal = PersistenceState::Persisting { since: now };
    }

    pub(super) fn finish_withdrawal_persist(&mut self) {
        self.withdrawal = PersistenceState::Durable;
    }

    pub(super) fn fail_withdrawal_persist(&mut self, now: u64) {
        let since = match self.withdrawal {
            PersistenceState::Persisting { since } | PersistenceState::Unknown { since } => since,
            PersistenceState::Durable => now,
        };
        self.withdrawal = PersistenceState::Unknown { since };
    }

    pub(super) fn withdrawal_is_durable(&self) -> bool {
        matches!(self.withdrawal, PersistenceState::Durable)
    }

}
