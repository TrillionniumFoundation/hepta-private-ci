#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fixed_histograms_and_resource_gauges_are_bounded_and_actionable() {
        let metrics = ArtifactOwnerOperationalMetricsV1::default();
        metrics.observe(
            ArtifactOwnerStageV1::PayloadWriteSync,
            Duration::from_micros(700),
        );
        metrics.observe(
            ArtifactOwnerStageV1::PayloadWriteSync,
            Duration::from_micros(4_000),
        );
        metrics.report_resource_usage(ArtifactOwnerResourceUsageV1 {
            observed_at: 20,
            pinned_bytes: 100,
            pending_erasure_bytes: 40,
            resident_bytes: 1_000,
            logical_payload_bytes: 200,
            durable_bytes_written: 500,
        });
        let snapshot = metrics.snapshot(
            25,
            OwnerOperationalGauges {
                recovery_since: Some(20),
                withdrawal_blocked_since: Some(23),
                drain_started_at: Some(22),
                drain_durable: true,
                ..OwnerOperationalGauges::default()
            },
        );
        assert_eq!(snapshot.oldest_pending_attempt_age_seconds, Some(5));
        assert_eq!(snapshot.withdrawal_blocked_duration_seconds, Some(2));
        assert_eq!(snapshot.write_amplification_ppm, Some(2_500_000));
        let stage = snapshot
            .stage_latency
            .iter()
            .find(|value| value.stage == ArtifactOwnerStageV1::PayloadWriteSync)
            .expect("stage exists");
        assert_eq!(stage.samples, 2);
        assert!(stage.p99_upper_bound_us >= 4_000);
        assert!(snapshot.response_json().contains("pendingErasureBytes"));
    }
}
