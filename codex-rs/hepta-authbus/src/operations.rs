use codex_hepta_types::AuthorityPosture;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExpiredReservationSweep {
    scanned: u32,
    expired: u32,
    indeterminate: u32,
    authority: AuthorityPosture,
}

impl ExpiredReservationSweep {
    pub(crate) fn new(scanned: u32, expired: u32, indeterminate: u32) -> Self {
        Self {
            scanned,
            expired,
            indeterminate,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    pub fn scanned(&self) -> u32 {
        self.scanned
    }

    pub fn expired(&self) -> u32 {
        self.expired
    }

    pub fn indeterminate(&self) -> u32 {
        self.indeterminate
    }

    pub fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusHealthSnapshot {
    pub active_reservations: u64,
    pub expired_active_reservations: u64,
    pub dispatch_attempted_reservations: u64,
    pub indeterminate_reservations: u64,
    pub oldest_active_expires_at_ms: Option<u64>,
    pub last_trusted_time_ms: Option<u64>,
    pub checkpoint_generation: Option<u64>,
    pub checkpoint_dirty: bool,
    pub recovery_required: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthBusSloThresholds {
    pub maximum_expired_active_reservations: u64,
    pub maximum_indeterminate_reservations: u64,
    pub maximum_active_reservations: u64,
    pub maximum_trusted_time_age_ms: u64,
}

impl Default for AuthBusSloThresholds {
    fn default() -> Self {
        Self {
            maximum_expired_active_reservations: 0,
            maximum_indeterminate_reservations: 0,
            maximum_active_reservations: 3_500,
            maximum_trusted_time_age_ms: 60_000,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum AuthBusAlertKind {
    RecoveryRequired,
    CheckpointDirty,
    ExpiredReservations,
    IndeterminateReservations,
    ReservationCapacity,
    TrustedTimeMissing,
    TrustedTimeStale,
}

impl AuthBusHealthSnapshot {
    pub fn alerts(
        &self,
        observed_at_ms: u64,
        thresholds: AuthBusSloThresholds,
    ) -> Vec<AuthBusAlertKind> {
        let mut alerts = Vec::new();
        if self.recovery_required {
            alerts.push(AuthBusAlertKind::RecoveryRequired);
        }
        if self.checkpoint_dirty {
            alerts.push(AuthBusAlertKind::CheckpointDirty);
        }
        if self.expired_active_reservations
            > thresholds.maximum_expired_active_reservations
        {
            alerts.push(AuthBusAlertKind::ExpiredReservations);
        }
        if self.indeterminate_reservations > thresholds.maximum_indeterminate_reservations {
            alerts.push(AuthBusAlertKind::IndeterminateReservations);
        }
        if self.active_reservations > thresholds.maximum_active_reservations {
            alerts.push(AuthBusAlertKind::ReservationCapacity);
        }
        match self.last_trusted_time_ms {
            None => alerts.push(AuthBusAlertKind::TrustedTimeMissing),
            Some(last)
                if observed_at_ms.saturating_sub(last)
                    > thresholds.maximum_trusted_time_age_ms =>
            {
                alerts.push(AuthBusAlertKind::TrustedTimeStale);
            }
            Some(_) => {}
        }
        alerts
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusMaintenanceReport {
    pub sweep: ExpiredReservationSweep,
    pub compacted_terminal_reservations: u32,
    pub health: AuthBusHealthSnapshot,
    pub alerts: Vec<AuthBusAlertKind>,
    pub authority: AuthorityPosture,
}
