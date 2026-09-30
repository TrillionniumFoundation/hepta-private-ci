//! Stable Prometheus projection for owner and retention observations.
//!
//! Export is pure and bounded. Unknown retention and quarantine values use
//! explicit `*_known` gauges and are never silently converted to zero.

use std::error::Error as StdError;
use std::fmt;
use std::fmt::Write as _;

use codex_hepta_types::Digest32;

use super::ArtifactOwnerOperationalMetricsV1;

const CONTENT_TYPE: &str = "text/plain; version=0.0.4; charset=utf-8";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerPrometheusObservationV1 {
    observed_at: u64,
    quarantine_items: Option<u64>,
    quarantine_observation_digest: Option<Digest32>,
}

impl ArtifactOwnerPrometheusObservationV1 {
    pub fn new(
        observed_at: u64,
        quarantine_items: Option<u64>,
        quarantine_observation_digest: Option<Digest32>,
    ) -> Result<Self, ArtifactOwnerPrometheusErrorV1> {
        if observed_at == 0
            || quarantine_items.is_some() != quarantine_observation_digest.is_some()
            || quarantine_observation_digest.is_some_and(Digest32::is_zero)
        {
            return Err(ArtifactOwnerPrometheusErrorV1::InvalidObservation);
        }
        Ok(Self {
            observed_at,
            quarantine_items,
            quarantine_observation_digest,
        })
    }

    #[must_use]
    pub const fn observed_at(&self) -> u64 {
        self.observed_at
    }

    #[must_use]
    pub const fn quarantine_items(&self) -> Option<u64> {
        self.quarantine_items
    }

    #[must_use]
    pub const fn quarantine_observation_digest(&self) -> Option<Digest32> {
        self.quarantine_observation_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerPrometheusSnapshotV1 {
    body: String,
}

impl ArtifactOwnerPrometheusSnapshotV1 {
    #[must_use]
    pub const fn content_type(&self) -> &'static str {
        CONTENT_TYPE
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.body
    }

    #[must_use]
    pub fn into_bytes(self) -> Vec<u8> {
        self.body.into_bytes()
    }
}

#[must_use]
pub fn render_artifact_owner_prometheus_v1(
    operations: &ArtifactOwnerOperationalMetricsV1,
    observation: ArtifactOwnerPrometheusObservationV1,
) -> ArtifactOwnerPrometheusSnapshotV1 {
    let commands = operations.base;
    let mut body = String::with_capacity(4096);
    counter(
        &mut body,
        "hepta_learning_artifact_owner_requests_received_total",
        commands.requests_received,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_requests_authenticated_total",
        commands.requests_authenticated,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_authentication_failures_total",
        commands.authentication_failures,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_exact_replays_total",
        commands.exact_replays,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_replay_conflicts_total",
        commands.replay_conflicts,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_publications_succeeded_total",
        commands.publications_succeeded,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_publications_failed_total",
        commands.publications_failed,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_recovery_publications_succeeded_total",
        commands.recovery_publications_succeeded,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_withdrawal_frontiers_installed_total",
        commands.withdrawal_frontiers_installed,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_authz_reloads_total",
        commands.authz_reloads,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_backups_succeeded_total",
        commands.backups_succeeded,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_command_failures_total",
        commands.command_failures,
    );

    gauge(
        &mut body,
        "hepta_learning_artifact_owner_observed_at_seconds",
        observation.observed_at,
    );
    optional_gauge(
        &mut body,
        "hepta_learning_artifact_owner_oldest_pending_attempt_age_seconds",
        operations.oldest_pending_attempt_age_seconds,
    );
    optional_gauge(
        &mut body,
        "hepta_learning_artifact_owner_drain_age_seconds",
        operations.drain_age_seconds,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_recovery_failures_total",
        operations.recovery_reconciliation_failures,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_withdrawal_blocks_total",
        operations.withdrawal_blocks,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_identity_conflicts_total",
        operations.identity_conflicts,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_stale_owner_failures_total",
        operations.stale_owner_rejections,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_persistence_unknown_failures_total",
        operations.persistence_unknown,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_capacity_failures_total",
        operations.capacity_rejections,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_observability_failures_total",
        operations.observability_failures,
    );

    let pinned_bytes = operations.retention.map(|value| value.pinned_bytes);
    let pending_erasure_bytes = operations
        .retention
        .map(|value| value.pending_physical_erase_bytes);
    optional_gauge(
        &mut body,
        "hepta_learning_artifact_owner_pinned_bytes",
        pinned_bytes,
    );
    optional_gauge(
        &mut body,
        "hepta_learning_artifact_owner_pending_physical_erasure_bytes",
        pending_erasure_bytes,
    );
    gauge(
        &mut body,
        "hepta_learning_artifact_owner_retention_observation_known",
        u64::from(operations.retention.is_some()),
    );
    optional_gauge(
        &mut body,
        "hepta_learning_artifact_owner_quarantine_items",
        observation.quarantine_items,
    );

    ArtifactOwnerPrometheusSnapshotV1 { body }
}

fn counter(body: &mut String, name: &str, value: u64) {
    let _ = writeln!(body, "# TYPE {name} counter");
    let _ = writeln!(body, "{name} {value}");
}

fn gauge(body: &mut String, name: &str, value: u64) {
    let _ = writeln!(body, "# TYPE {name} gauge");
    let _ = writeln!(body, "{name} {value}");
}

fn optional_gauge(body: &mut String, name: &str, value: Option<u64>) {
    let known = format!("{name}_known");
    gauge(body, &known, u64::from(value.is_some()));
    if let Some(value) = value {
        gauge(body, name, value);
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerPrometheusErrorV1 {
    InvalidObservation,
}

impl fmt::Display for ArtifactOwnerPrometheusErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOwnerPrometheusErrorV1 {}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::*;
    use crate::owner::ArtifactOwnerMetricsV1;

    #[test]
    fn unknown_retention_values_are_not_exported_as_zero() {
        let operations = ArtifactOwnerOperationalMetricsV1 {
            base: ArtifactOwnerMetricsV1::default(),
            oldest_pending_attempt_age_seconds: Some(7),
            drain_age_seconds: None,
            recovery_reconciliation_failures: 2,
            withdrawal_blocks: 3,
            identity_conflicts: 4,
            stale_owner_rejections: 5,
            persistence_unknown: 6,
            capacity_rejections: 7,
            observability_failures: 8,
            retention: None,
            stage_summaries: BTreeMap::new(),
        };
        let observation = ArtifactOwnerPrometheusObservationV1::new(
            20,
            Some(11),
            Some(Digest32::of_bytes(b"quarantine")),
        )
        .expect("valid observation");
        let snapshot = render_artifact_owner_prometheus_v1(&operations, observation);
        assert!(snapshot
            .as_str()
            .contains("hepta_learning_artifact_owner_pinned_bytes_known 0"));
        assert!(!snapshot
            .as_str()
            .contains("hepta_learning_artifact_owner_pinned_bytes 0"));
        assert!(snapshot
            .as_str()
            .contains("hepta_learning_artifact_owner_quarantine_items 11"));
        assert_eq!(
            snapshot.content_type(),
            "text/plain; version=0.0.4; charset=utf-8"
        );
    }

    #[test]
    fn quarantine_value_requires_a_digest_bound_observation() {
        assert_eq!(
            ArtifactOwnerPrometheusObservationV1::new(20, Some(1), None),
            Err(ArtifactOwnerPrometheusErrorV1::InvalidObservation)
        );
    }
}
