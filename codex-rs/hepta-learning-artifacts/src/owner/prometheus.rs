//! Stable Prometheus projection for owner and retention observations.
//!
//! Export is pure and bounded. Unknown retention values are represented by a
//! separate `*_known` gauge and are never silently converted to zero.

use std::fmt::Write as _;

use super::ArtifactOwnerMetricsV1;
use super::ArtifactOwnerOperationalMetricsV1;

const CONTENT_TYPE: &str = "text/plain; version=0.0.4; charset=utf-8";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerPrometheusSnapshotV1 {
    body: String,
}

impl ArtifactOwnerPrometheusSnapshotV1 {
    #[must_use]
    pub fn content_type(&self) -> &'static str {
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
    commands: ArtifactOwnerMetricsV1,
    operations: &ArtifactOwnerOperationalMetricsV1,
) -> ArtifactOwnerPrometheusSnapshotV1 {
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
        "hepta_learning_artifact_owner_started_at_seconds",
        operations.started_at,
    );
    gauge(
        &mut body,
        "hepta_learning_artifact_owner_observed_at_seconds",
        operations.observed_at,
    );
    gauge(
        &mut body,
        "hepta_learning_artifact_owner_pending_attempts",
        operations.pending_attempts as u64,
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
        operations.recovery_failures,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_withdrawal_blocks_total",
        operations.withdrawal_blocks,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_withdrawal_block_seconds_total",
        operations.withdrawal_block_seconds,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_identity_conflicts_total",
        operations.identity_conflicts,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_stale_owner_failures_total",
        operations.stale_owner_failures,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_persistence_unknown_failures_total",
        operations.persistence_unknown_failures,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_capacity_failures_total",
        operations.capacity_failures,
    );
    counter(
        &mut body,
        "hepta_learning_artifact_owner_observability_failures_total",
        operations.observability_failures,
    );
    optional_gauge(
        &mut body,
        "hepta_learning_artifact_owner_pinned_bytes",
        operations.pinned_bytes,
    );
    optional_gauge(
        &mut body,
        "hepta_learning_artifact_owner_pending_physical_erasure_bytes",
        operations.pending_physical_erasure_bytes,
    );
    gauge(
        &mut body,
        "hepta_learning_artifact_owner_retention_observation_known",
        u64::from(operations.retention_observation_digest.is_some()),
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

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;

    use super::*;

    #[test]
    fn unknown_retention_values_are_not_exported_as_zero() {
        let snapshot = render_artifact_owner_prometheus_v1(
            ArtifactOwnerMetricsV1::default(),
            &ArtifactOwnerOperationalMetricsV1 {
                started_at: 10,
                observed_at: 20,
                pending_attempts: 1,
                oldest_pending_attempt_age_seconds: Some(7),
                drain_age_seconds: None,
                recovery_failures: 2,
                withdrawal_blocks: 3,
                withdrawal_block_seconds: 4,
                identity_conflicts: 5,
                stale_owner_failures: 6,
                persistence_unknown_failures: 7,
                capacity_failures: 8,
                observability_failures: 9,
                pinned_bytes: None,
                pending_physical_erasure_bytes: Some(11),
                retention_observation_digest: Some(Digest32::of_bytes(b"retention")),
            },
        );
        assert!(snapshot
            .as_str()
            .contains("hepta_learning_artifact_owner_pinned_bytes_known 0"));
        assert!(!snapshot
            .as_str()
            .contains("hepta_learning_artifact_owner_pinned_bytes 0"));
        assert!(snapshot.as_str().contains(
            "hepta_learning_artifact_owner_pending_physical_erasure_bytes 11"
        ));
        assert_eq!(
            snapshot.content_type(),
            "text/plain; version=0.0.4; charset=utf-8"
        );
    }
}
