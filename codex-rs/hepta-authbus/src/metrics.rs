//! Bounded, label-free Prometheus exposition from a single committed snapshot.
//! The supervisor supplies transport health; this module never invents an `up`
//! signal or exports identifiers, paths, claims, keys, signatures, or payloads.

use std::fmt::Write as _;

use crate::AuthBusOperationalSnapshot;

impl AuthBusOperationalSnapshot {
    /// Render one coherent snapshot. The exporter must publish this response
    /// atomically, retain observed_at_ms unchanged, and report transport failure
    /// separately. Re-serving an old snapshot cannot refresh its observation time.
    pub fn prometheus_text(&self) -> Result<String, std::fmt::Error> {
        let values = [
            ("hepta_authbus_observed_at_ms", self.observed_at_ms),
            ("hepta_authbus_checkpoint_generation", self.checkpoint_generation),
            ("hepta_authbus_checkpoint_dirty", u64::from(self.checkpoint_dirty)),
            ("hepta_authbus_recovery_required", u64::from(self.recovery_required)),
            ("hepta_authbus_active_reservations", self.active_reservations),
            ("hepta_authbus_expired_active_reservations", self.expired_active_reservations),
            ("hepta_authbus_indeterminate_reservations", self.indeterminate_reservations),
            ("hepta_authbus_oldest_active_reservation_age_ms", self.oldest_active_reservation_age_ms),
            ("hepta_authbus_quota_available", self.quota_available),
            ("hepta_authbus_quota_reserved", self.quota_reserved),
            ("hepta_authbus_quota_consumed", self.quota_consumed),
            ("hepta_authbus_quota_utilization_basis_points", self.quota_utilization_basis_points),
            ("hepta_authbus_active_issuer_epochs", self.active_issuer_epochs),
            ("hepta_authbus_revoked_issuer_epochs", self.revoked_issuer_epochs),
            ("hepta_authbus_retired_issuer_epochs", self.retired_issuer_epochs),
        ];
        let mut text = String::with_capacity(4096);
        for (name, value) in values {
            writeln!(&mut text, "# HELP {name} AuthBus committed snapshot gauge.")?;
            writeln!(&mut text, "# TYPE {name} gauge")?;
            writeln!(&mut text, "{name} {value}")?;
        }
        Ok(text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> AuthBusOperationalSnapshot {
        AuthBusOperationalSnapshot {
            observed_at_ms: 1_700_000_000_000,
            checkpoint_generation: 7,
            checkpoint_dirty: true,
            recovery_required: false,
            active_reservations: 9,
            expired_active_reservations: 2,
            indeterminate_reservations: 3,
            oldest_active_reservation_age_ms: 12_000,
            quota_available: 70,
            quota_reserved: 20,
            quota_consumed: 10,
            quota_utilization_basis_points: 3_000,
            active_issuer_epochs: 4,
            revoked_issuer_epochs: 5,
            retired_issuer_epochs: 6,
        }
    }

    #[test]
    fn exports_all_gauges_without_identity_labels() {
        let text = fixture().prometheus_text().expect("snapshot exposition");
        assert_eq!(text.lines().filter(|line| line.starts_with("# TYPE ")).count(), 15);
        assert_eq!(text.lines().filter(|line| !line.starts_with('#')).count(), 15);
        assert!(text.contains("hepta_authbus_checkpoint_dirty 1\n"));
        assert!(text.contains("hepta_authbus_recovery_required 0\n"));
        assert!(text.contains("hepta_authbus_quota_reserved 20\n"));
        assert!(!text.contains('{'));
        assert!(!text.contains("up "));
    }

    #[test]
    fn rendering_an_old_snapshot_does_not_refresh_its_observation_time() {
        let snapshot = fixture();
        assert_eq!(snapshot.prometheus_text().expect("first render"), snapshot.prometheus_text().expect("second render"));
        assert!(snapshot.prometheus_text().expect("render").contains("hepta_authbus_observed_at_ms 1700000000000\n"));
    }
}
