impl OwnerOperationalState {
    pub(super) fn begin_drain_volatile(&mut self, now: u64) {
        if matches!(self.drain, DrainState::Active) {
            self.drain = DrainState::VolatileRequested { since: now };
        }
    }

    pub(super) fn begin_drain_persist(&mut self, now: u64) {
        let since = match self.drain {
            DrainState::Active => now,
            DrainState::VolatileRequested { since }
            | DrainState::Persisting { since }
            | DrainState::DurableRequested { since }
            | DrainState::Unknown { since } => since,
        };
        self.drain = DrainState::Persisting { since };
    }

    pub(super) fn finish_drain_durable(&mut self) {
        let since = match self.drain {
            DrainState::Persisting { since }
            | DrainState::VolatileRequested { since }
            | DrainState::DurableRequested { since }
            | DrainState::Unknown { since } => since,
            DrainState::Active => 0,
        };
        self.drain = DrainState::DurableRequested { since };
    }

    pub(super) fn fail_drain_persist(&mut self, now: u64) {
        let since = match self.drain {
            DrainState::Persisting { since }
            | DrainState::VolatileRequested { since }
            | DrainState::DurableRequested { since }
            | DrainState::Unknown { since } => since,
            DrainState::Active => now,
        };
        self.drain = DrainState::Unknown { since };
    }

    pub(super) fn durable_drain_requested(&self) -> bool {
        matches!(self.drain, DrainState::DurableRequested { .. })
    }

    pub(super) fn is_drained(&self) -> bool {
        matches!(
            self.drain,
            DrainState::VolatileRequested { .. } | DrainState::DurableRequested { .. }
        ) && matches!(self.withdrawal, PersistenceState::Durable)
            && matches!(self.recovery, RecoveryState::Clear)
            && matches!(self.request_identity, RequestIdentityState::Clear)
    }

    pub(super) fn gauges(&self) -> OwnerOperationalGauges {
        OwnerOperationalGauges {
            recovery_since: match self.recovery {
                RecoveryState::Clear => None,
                RecoveryState::Required { since, .. } => Some(since),
            },
            request_identity_unknown_since: match self.request_identity {
                RequestIdentityState::Unknown { since, .. }
                | RequestIdentityState::Persisting { since, .. } => Some(since),
                RequestIdentityState::Clear => None,
            },
            withdrawal_blocked_since: match self.withdrawal {
                PersistenceState::Durable => None,
                PersistenceState::Persisting { since } | PersistenceState::Unknown { since } => {
                    Some(since)
                }
            },
            drain_started_at: match self.drain {
                DrainState::Active => None,
                DrainState::VolatileRequested { since }
                | DrainState::Persisting { since }
                | DrainState::DurableRequested { since }
                | DrainState::Unknown { since } => Some(since),
            },
            drain_durable: self.durable_drain_requested(),
        }
    }
}
