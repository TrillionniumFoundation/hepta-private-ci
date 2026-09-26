//! Bounded observability for the canonical intelligence product profile.
//!
//! Metrics are diagnostic facts only. They grant no authority and are not a
//! substitute for durable Decision/Outcome receipts or qualification evidence.

use std::collections::BTreeMap;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence::CanonicalPortFailureClassV1;
use codex_hepta_intelligence::CanonicalStageV1;
use codex_hepta_types::Digest32;

const MAX_REJECTION_REASONS: usize = 32;

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct IntelligenceStageMetricsV1 {
    pub calls: u64,
    pub failures: u64,
    pub timeouts: u64,
    pub total_micros: u64,
    pub maximum_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceObservabilitySnapshotV1 {
    pub capability_profile_digest: Digest32,
    pub authority_manifest_revision: u64,
    pub active_workers: u64,
    pub late_workers: u64,
    pub worker_saturation: u64,
    pub currentness_rejections: u64,
    pub provider_installed: bool,
    pub provider_pending: u64,
    pub learning_outbox_backlog: u64,
    pub stages: BTreeMap<CanonicalStageV1, IntelligenceStageMetricsV1>,
    pub rejection_reasons: BTreeMap<String, u64>,
}

#[derive(Debug)]
pub struct AgentdIntelligenceObservabilityV1 {
    capability_profile_digest: Digest32,
    authority_manifest_revision: AtomicU64,
    active_workers: AtomicU64,
    late_workers: AtomicU64,
    worker_saturation: AtomicU64,
    currentness_rejections: AtomicU64,
    provider_installed: AtomicU64,
    provider_pending: AtomicU64,
    learning_outbox_backlog: AtomicU64,
    stages: Mutex<BTreeMap<CanonicalStageV1, IntelligenceStageMetricsV1>>,
    rejection_reasons: Mutex<BTreeMap<String, u64>>,
}

impl AgentdIntelligenceObservabilityV1 {
    pub fn new(capability_profile_digest: Digest32) -> Result<Self, &'static str> {
        if capability_profile_digest.is_zero() {
            return Err("canonical intelligence capability profile digest must be non-zero");
        }
        Ok(Self {
            capability_profile_digest,
            authority_manifest_revision: AtomicU64::new(0),
            active_workers: AtomicU64::new(0),
            late_workers: AtomicU64::new(0),
            worker_saturation: AtomicU64::new(0),
            currentness_rejections: AtomicU64::new(0),
            provider_installed: AtomicU64::new(0),
            provider_pending: AtomicU64::new(0),
            learning_outbox_backlog: AtomicU64::new(0),
            stages: Mutex::new(BTreeMap::new()),
            rejection_reasons: Mutex::new(BTreeMap::new()),
        })
    }

    #[must_use]
    pub const fn capability_profile_digest(&self) -> Digest32 {
        self.capability_profile_digest
    }

    pub fn set_authority_manifest_revision(&self, revision: u64) {
        self.authority_manifest_revision
            .store(revision, Ordering::Relaxed);
    }

    pub fn set_provider_state(&self, installed: bool, pending: usize) {
        self.provider_installed
            .store(u64::from(installed), Ordering::Relaxed);
        self.provider_pending.store(
            u64::try_from(pending).unwrap_or(u64::MAX),
            Ordering::Relaxed,
        );
    }

    pub fn set_learning_outbox_backlog(&self, backlog: usize) {
        self.learning_outbox_backlog.store(
            u64::try_from(backlog).unwrap_or(u64::MAX),
            Ordering::Relaxed,
        );
    }

    pub fn worker_started(&self) {
        self.active_workers.fetch_add(1, Ordering::Relaxed);
    }

    pub fn worker_finished(&self) {
        let _ = self
            .active_workers
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                Some(value.saturating_sub(1))
            });
    }

    pub fn worker_saturated(&self) {
        self.worker_saturation.fetch_add(1, Ordering::Relaxed);
    }

    pub fn late_worker_started(&self) {
        self.late_workers.fetch_add(1, Ordering::Relaxed);
    }

    pub fn late_worker_finished(&self) {
        let _ = self
            .late_workers
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                Some(value.saturating_sub(1))
            });
    }

    pub fn observe_stage(
        &self,
        stage: CanonicalStageV1,
        elapsed_micros: u64,
        failure: Option<CanonicalPortFailureClassV1>,
    ) {
        let Ok(mut stages) = self.stages.lock() else {
            return;
        };
        let metrics = stages.entry(stage).or_default();
        metrics.calls = metrics.calls.saturating_add(1);
        metrics.total_micros = metrics.total_micros.saturating_add(elapsed_micros);
        metrics.maximum_micros = metrics.maximum_micros.max(elapsed_micros);
        if let Some(failure) = failure {
            metrics.failures = metrics.failures.saturating_add(1);
            if failure == CanonicalPortFailureClassV1::TimedOut {
                metrics.timeouts = metrics.timeouts.saturating_add(1);
            }
        }
    }

    pub fn reject_currentness(&self, reason: &str) {
        self.currentness_rejections.fetch_add(1, Ordering::Relaxed);
        let Ok(mut reasons) = self.rejection_reasons.lock() else {
            return;
        };
        let normalized: String = reason.chars().take(96).collect();
        if !reasons.contains_key(&normalized) && reasons.len() >= MAX_REJECTION_REASONS {
            *reasons.entry("other".to_string()).or_default() += 1;
            return;
        }
        let count = reasons.entry(normalized).or_default();
        *count = count.saturating_add(1);
    }

    #[must_use]
    pub fn snapshot(&self) -> AgentdIntelligenceObservabilitySnapshotV1 {
        AgentdIntelligenceObservabilitySnapshotV1 {
            capability_profile_digest: self.capability_profile_digest,
            authority_manifest_revision: self.authority_manifest_revision.load(Ordering::Relaxed),
            active_workers: self.active_workers.load(Ordering::Relaxed),
            late_workers: self.late_workers.load(Ordering::Relaxed),
            worker_saturation: self.worker_saturation.load(Ordering::Relaxed),
            currentness_rejections: self.currentness_rejections.load(Ordering::Relaxed),
            provider_installed: self.provider_installed.load(Ordering::Relaxed) != 0,
            provider_pending: self.provider_pending.load(Ordering::Relaxed),
            learning_outbox_backlog: self.learning_outbox_backlog.load(Ordering::Relaxed),
            stages: self
                .stages
                .lock()
                .map(|value| value.clone())
                .unwrap_or_default(),
            rejection_reasons: self
                .rejection_reasons
                .lock()
                .map(|value| value.clone())
                .unwrap_or_default(),
        }
    }
}
