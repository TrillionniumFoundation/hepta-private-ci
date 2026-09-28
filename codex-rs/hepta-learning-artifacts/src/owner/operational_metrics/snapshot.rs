#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactOwnerResourceUsageV1 {
    pub observed_at: u64,
    pub pinned_bytes: u64,
    pub pending_erasure_bytes: u64,
    pub resident_bytes: u64,
    pub logical_payload_bytes: u64,
    pub durable_bytes_written: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerStageLatencyV1 {
    pub stage: ArtifactOwnerStageV1,
    pub samples: u64,
    pub p50_upper_bound_us: u64,
    pub p95_upper_bound_us: u64,
    pub p99_upper_bound_us: u64,
    pub max_us: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerOperationalSnapshotV1 {
    pub observed_at: u64,
    pub oldest_pending_attempt_age_seconds: Option<u64>,
    pub withdrawal_blocked_total: u64,
    pub withdrawal_blocked_duration_seconds: Option<u64>,
    pub drain_duration_seconds: Option<u64>,
    pub drain_durable: bool,
    pub recovery_reconciliation_failures: u64,
    pub request_identity_conflicts: u64,
    pub owner_context_conflicts: u64,
    pub withdrawal_frontier_conflicts: u64,
    pub capacity_rejections: u64,
    pub control_persistence_unknown: u64,
    pub resource_usage: Option<ArtifactOwnerResourceUsageV1>,
    pub write_amplification_ppm: Option<u64>,
    pub stage_latency: Vec<ArtifactOwnerStageLatencyV1>,
}

impl ArtifactOwnerOperationalSnapshotV1 {
    #[must_use]
    pub fn response_json(&self) -> String {
        let mut stages = String::new();
        for (index, value) in self.stage_latency.iter().enumerate() {
            if index != 0 {
                stages.push(',');
            }
            stages.push_str(&format!(
                concat!(
                    "{{\"stage\":\"{}\",\"samples\":{},",
                    "\"p50UpperBoundUs\":{},\"p95UpperBoundUs\":{},",
                    "\"p99UpperBoundUs\":{},\"maxUs\":{}}}"
                ),
                value.stage.as_str(),
                value.samples,
                value.p50_upper_bound_us,
                value.p95_upper_bound_us,
                value.p99_upper_bound_us,
                value.max_us,
            ));
        }
        let optional = |value: Option<u64>| {
            value.map_or_else(|| "null".to_owned(), |value| value.to_string())
        };
        let resource = self.resource_usage.map_or_else(
            || "null".to_owned(),
            |value| {
                format!(
                    concat!(
                        "{{\"observedAt\":{},\"pinnedBytes\":{},",
                        "\"pendingErasureBytes\":{},\"residentBytes\":{},",
                        "\"logicalPayloadBytes\":{},\"durableBytesWritten\":{}}}"
                    ),
                    value.observed_at,
                    value.pinned_bytes,
                    value.pending_erasure_bytes,
                    value.resident_bytes,
                    value.logical_payload_bytes,
                    value.durable_bytes_written,
                )
            },
        );
        format!(
            concat!(
                "{{\"schema\":\"hepta.learning-artifacts.operational-metrics.v1\",",
                "\"observedAt\":{},\"oldestPendingAttemptAgeSeconds\":{},",
                "\"withdrawalBlockedTotal\":{},\"withdrawalBlockedDurationSeconds\":{},",
                "\"drainDurationSeconds\":{},\"drainDurable\":{},",
                "\"recoveryReconciliationFailures\":{},",
                "\"requestIdentityConflicts\":{},\"ownerContextConflicts\":{},",
                "\"withdrawalFrontierConflicts\":{},\"capacityRejections\":{},",
                "\"controlPersistenceUnknown\":{},\"resourceUsage\":{},",
                "\"writeAmplificationPpm\":{},\"stageLatency\":[{}]}}"
            ),
            self.observed_at,
            optional(self.oldest_pending_attempt_age_seconds),
            self.withdrawal_blocked_total,
            optional(self.withdrawal_blocked_duration_seconds),
            optional(self.drain_duration_seconds),
            self.drain_durable,
            self.recovery_reconciliation_failures,
            self.request_identity_conflicts,
            self.owner_context_conflicts,
            self.withdrawal_frontier_conflicts,
            self.capacity_rejections,
            self.control_persistence_unknown,
            resource,
            optional(self.write_amplification_ppm),
            stages,
        )
    }
}

