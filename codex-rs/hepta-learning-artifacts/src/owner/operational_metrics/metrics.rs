#[derive(Clone, Debug, Default)]
pub struct ArtifactOwnerOperationalMetricsV1 {
    inner: Arc<MetricsInner>,
}

impl ArtifactOwnerOperationalMetricsV1 {
    pub fn observe(&self, stage: ArtifactOwnerStageV1, duration: Duration) {
        if let Some(histogram) = self.inner.stages.get(&stage) {
            histogram.observe(duration);
        }
    }

    pub fn measure<T, E>(
        &self,
        stage: ArtifactOwnerStageV1,
        operation: impl FnOnce() -> Result<T, E>,
    ) -> Result<T, E> {
        let started = Instant::now();
        let result = operation();
        self.observe(stage, started.elapsed());
        result
    }

    pub fn increment_withdrawal_blocked(&self) {
        self.inner
            .withdrawal_blocked_total
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn increment_recovery_reconciliation_failure(&self) {
        self.inner
            .recovery_reconciliation_failures
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn increment_request_identity_conflict(&self) {
        self.inner
            .request_identity_conflicts
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn increment_owner_context_conflict(&self) {
        self.inner
            .owner_context_conflicts
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn increment_withdrawal_frontier_conflict(&self) {
        self.inner
            .withdrawal_frontier_conflicts
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn increment_capacity_rejection(&self) {
        self.inner
            .capacity_rejections
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn increment_control_persistence_unknown(&self) {
        self.inner
            .control_persistence_unknown
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn report_resource_usage(&self, usage: ArtifactOwnerResourceUsageV1) {
        if let Ok(mut current) = self.inner.resource_usage.lock() {
            if current
                .as_ref()
                .is_none_or(|existing| usage.observed_at >= existing.observed_at)
            {
                *current = Some(usage);
            }
        }
    }

    pub(super) fn snapshot(
        &self,
        now: u64,
        gauges: OwnerOperationalGauges,
    ) -> ArtifactOwnerOperationalSnapshotV1 {
        let oldest_since = [gauges.recovery_since, gauges.request_identity_unknown_since]
            .into_iter()
            .flatten()
            .min();
        let resource_usage = self
            .inner
            .resource_usage
            .lock()
            .ok()
            .and_then(|value| *value);
        let write_amplification_ppm = resource_usage.and_then(|usage| {
            (usage.logical_payload_bytes != 0).then(|| {
                usage
                    .durable_bytes_written
                    .saturating_mul(1_000_000)
                    / usage.logical_payload_bytes
            })
        });
        ArtifactOwnerOperationalSnapshotV1 {
            observed_at: now,
            oldest_pending_attempt_age_seconds: oldest_since.map(|since| now.saturating_sub(since)),
            withdrawal_blocked_total: self
                .inner
                .withdrawal_blocked_total
                .load(Ordering::Relaxed),
            withdrawal_blocked_duration_seconds: gauges
                .withdrawal_blocked_since
                .map(|since| now.saturating_sub(since)),
            drain_duration_seconds: gauges
                .drain_started_at
                .map(|since| now.saturating_sub(since)),
            drain_durable: gauges.drain_durable,
            recovery_reconciliation_failures: self
                .inner
                .recovery_reconciliation_failures
                .load(Ordering::Relaxed),
            request_identity_conflicts: self
                .inner
                .request_identity_conflicts
                .load(Ordering::Relaxed),
            owner_context_conflicts: self
                .inner
                .owner_context_conflicts
                .load(Ordering::Relaxed),
            withdrawal_frontier_conflicts: self
                .inner
                .withdrawal_frontier_conflicts
                .load(Ordering::Relaxed),
            capacity_rejections: self.inner.capacity_rejections.load(Ordering::Relaxed),
            control_persistence_unknown: self
                .inner
                .control_persistence_unknown
                .load(Ordering::Relaxed),
            resource_usage,
            write_amplification_ppm,
            stage_latency: ArtifactOwnerStageV1::ALL
                .into_iter()
                .filter_map(|stage| self.inner.stages.get(&stage).map(|value| value.snapshot(stage)))
                .collect(),
        }
    }
}

