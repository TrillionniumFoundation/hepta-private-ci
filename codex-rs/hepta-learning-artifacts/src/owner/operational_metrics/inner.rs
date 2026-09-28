#[derive(Debug)]
struct MetricsInner {
    stages: BTreeMap<ArtifactOwnerStageV1, StageHistogram>,
    withdrawal_blocked_total: AtomicU64,
    recovery_reconciliation_failures: AtomicU64,
    request_identity_conflicts: AtomicU64,
    owner_context_conflicts: AtomicU64,
    withdrawal_frontier_conflicts: AtomicU64,
    capacity_rejections: AtomicU64,
    control_persistence_unknown: AtomicU64,
    resource_usage: Mutex<Option<ArtifactOwnerResourceUsageV1>>,
}

impl Default for MetricsInner {
    fn default() -> Self {
        Self {
            stages: ArtifactOwnerStageV1::ALL
                .into_iter()
                .map(|stage| (stage, StageHistogram::default()))
                .collect(),
            withdrawal_blocked_total: AtomicU64::new(0),
            recovery_reconciliation_failures: AtomicU64::new(0),
            request_identity_conflicts: AtomicU64::new(0),
            owner_context_conflicts: AtomicU64::new(0),
            withdrawal_frontier_conflicts: AtomicU64::new(0),
            capacity_rejections: AtomicU64::new(0),
            control_persistence_unknown: AtomicU64::new(0),
            resource_usage: Mutex::new(None),
        }
    }
}

