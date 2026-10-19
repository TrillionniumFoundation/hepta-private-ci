//! Bounded process-local observations, never authorization or acceptance.
//! Durations include failing/cancelled operations. Nested phases overlap and
//! must not be summed; percentiles describe the last 256 samples per phase.
use std::collections::VecDeque;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

const WINDOW: usize = 256;

#[derive(Clone, Copy)]
#[repr(usize)]
pub(crate) enum Phase {
    CompileSerialize,
    StagePublication,
    RequestPreparation,
    TokenizerColdConfiguration,
    TokenizerWarmConfiguration,
    TokenizerArtifacts,
    TokenizerProcess,
    RegistryWait,
    FinalProof,
    PreSendPersistence,
    TerminalPersistence,
    StoreEncoding,
    StoreFileSync,
    StoreDirectorySync,
    StoreOpen,
    LiveAttemptCompletion,
    RecoveredReconciliation,
}

const PHASE_NAMES: [&str; 17] = [
    "compile_serialize",
    "stage_publication",
    "request_preparation",
    "tokenizer_cold_configuration",
    "tokenizer_warm_configuration",
    "tokenizer_artifacts",
    "tokenizer_process",
    "registry_wait",
    "final_proof",
    "pre_send_persistence",
    "terminal_persistence",
    "store_encoding",
    "store_file_sync",
    "store_directory_sync",
    "store_open",
    "live_attempt_completion",
    "recovered_reconciliation",
];

#[derive(Default)]
struct Samples {
    count: u64,
    total_micros: u64,
    maximum_micros: u64,
    recent: VecDeque<u64>,
}

pub(crate) struct Metrics {
    samples: Mutex<[Samples; PHASE_NAMES.len()]>,
    dropped: AtomicU64,
}

impl Default for Metrics {
    fn default() -> Self {
        Self {
            samples: Mutex::new(std::array::from_fn(|_| Samples::default())),
            dropped: AtomicU64::new(0),
        }
    }
}

impl Metrics {
    pub(crate) fn measure(&self, phase: Phase) -> Measurement<'_> {
        Measurement {
            metrics: self,
            phase,
            started: Instant::now(),
        }
    }

    pub(crate) fn record(&self, phase: Phase, elapsed: Duration) {
        let Ok(mut samples) = self.samples.lock() else {
            let _ = self
                .dropped
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                    Some(value.saturating_add(1))
                });
            return;
        };
        let micros = u64::try_from(elapsed.as_micros()).unwrap_or(u64::MAX);
        let sample = &mut samples[phase as usize];
        sample.count = sample.count.saturating_add(1);
        sample.total_micros = sample.total_micros.saturating_add(micros);
        sample.maximum_micros = sample.maximum_micros.max(micros);
        if sample.recent.len() == WINDOW {
            sample.recent.pop_front();
        }
        sample.recent.push_back(micros);
    }

    pub(crate) fn snapshot(&self) -> serde_json::Value {
        let Ok(samples) = self.samples.lock() else {
            return serde_json::json!({"available": false, "reason": "metrics_poisoned"});
        };
        let phases: serde_json::Map<String, serde_json::Value> = PHASE_NAMES
            .iter()
            .zip(samples.iter())
            .map(|(name, sample)| {
                let mut sorted = sample.recent.iter().copied().collect::<Vec<_>>();
                sorted.sort_unstable();
                let percentile = |percent: usize| {
                    if sorted.is_empty() {
                        None
                    } else {
                        Some(sorted[(sorted.len() * percent).div_ceil(100) - 1])
                    }
                };
                ((*name).to_owned(), serde_json::json!({
                    "count": sample.count,
                    "total_micros_saturating": sample.total_micros,
                    "maximum_micros": if sample.count == 0 { None } else { Some(sample.maximum_micros) },
                    "retained_samples": sorted.len(),
                    "p50_micros": percentile(50),
                    "p95_micros": percentile(95),
                    "p99_micros": percentile(99),
                }))
            })
            .collect();
        serde_json::json!({
            "available": true,
            "scope": "process_local_attempted_phases_including_errors_and_cancellation",
            "percentile_window": WINDOW,
            "nested_phases_overlap": true,
            "dropped_observations": self.dropped.load(Ordering::Relaxed),
            "observations": phases,
        })
    }
}

pub(crate) struct Measurement<'a> {
    metrics: &'a Metrics,
    phase: Phase,
    started: Instant,
}

impl Drop for Measurement<'_> {
    fn drop(&mut self) {
        self.metrics.record(self.phase, self.started.elapsed());
    }
}

#[cfg(test)]
#[path = "metrics_tests.rs"]
mod tests;
