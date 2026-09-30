//! Fixed-memory recent timing windows. Percentiles describe the last 256
//! observations of each stage/class, never a lifetime or target-host SLO.

use serde::Serialize;
use std::collections::VecDeque;
use std::time::Duration;

const WINDOW: usize = 256;

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct NativeLatencySummary {
    pub observed: u64,
    pub samples: usize,
    pub p50_micros: u64,
    pub p95_micros: u64,
    pub p99_micros: u64,
    pub maximum_micros: u64,
}

#[derive(Clone, Default)]
pub(crate) struct LatencyWindow {
    observed: u64,
    samples: VecDeque<u64>,
}

impl LatencyWindow {
    pub(crate) fn observe(&mut self, elapsed: Duration) {
        if self.samples.len() == WINDOW {
            self.samples.pop_front();
        }
        self.samples
            .push_back(u64::try_from(elapsed.as_micros()).unwrap_or(u64::MAX));
        self.observed = self.observed.saturating_add(1);
    }

    pub(crate) fn summary(&self) -> NativeLatencySummary {
        let mut samples: Vec<_> = self.samples.iter().copied().collect();
        samples.sort_unstable();
        let percentile = |rank: usize| {
            if samples.is_empty() {
                0
            } else {
                samples[(samples.len() * rank).div_ceil(100) - 1]
            }
        };
        NativeLatencySummary {
            observed: self.observed,
            samples: samples.len(),
            p50_micros: percentile(50),
            p95_micros: percentile(95),
            p99_micros: percentile(99),
            maximum_micros: samples.last().copied().unwrap_or(0),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nearest_rank_percentiles_and_window_are_bounded() {
        let mut window = LatencyWindow::default();
        assert_eq!(window.summary(), NativeLatencySummary::default());
        for value in 1..=512 {
            window.observe(Duration::from_micros(value));
        }
        assert_eq!(
            window.summary(),
            NativeLatencySummary {
                observed: 512,
                samples: 256,
                p50_micros: 384,
                p95_micros: 500,
                p99_micros: 510,
                maximum_micros: 512,
            }
        );
    }
}
