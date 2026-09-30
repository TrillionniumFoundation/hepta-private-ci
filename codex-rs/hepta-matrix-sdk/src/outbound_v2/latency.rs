use std::time::Duration;

/// Fixed, cumulative and identity-free latency buckets. The boundaries are
/// deliberately closed and bounded so the production metric cannot acquire
/// room, transaction, user or other high-cardinality labels.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, serde::Serialize)]
pub struct LatencyHistogram {
    pub count: u64,
    pub sum_ms: u64,
    pub max_ms: u64,
    pub le_1_ms: u64,
    pub le_5_ms: u64,
    pub le_10_ms: u64,
    pub le_25_ms: u64,
    pub le_50_ms: u64,
    pub le_100_ms: u64,
    pub le_250_ms: u64,
    pub le_500_ms: u64,
    pub le_1000_ms: u64,
}

impl LatencyHistogram {
    pub(crate) fn observe_duration(&mut self, duration: Duration) {
        let milliseconds = u64::try_from(duration.as_millis()).unwrap_or(u64::MAX);
        self.observe_ms(milliseconds);
    }

    pub(crate) fn observe_ms(&mut self, milliseconds: u64) {
        self.count = self.count.saturating_add(1);
        self.sum_ms = self.sum_ms.saturating_add(milliseconds);
        self.max_ms = self.max_ms.max(milliseconds);
        if milliseconds <= 1 {
            self.le_1_ms = self.le_1_ms.saturating_add(1);
        }
        if milliseconds <= 5 {
            self.le_5_ms = self.le_5_ms.saturating_add(1);
        }
        if milliseconds <= 10 {
            self.le_10_ms = self.le_10_ms.saturating_add(1);
        }
        if milliseconds <= 25 {
            self.le_25_ms = self.le_25_ms.saturating_add(1);
        }
        if milliseconds <= 50 {
            self.le_50_ms = self.le_50_ms.saturating_add(1);
        }
        if milliseconds <= 100 {
            self.le_100_ms = self.le_100_ms.saturating_add(1);
        }
        if milliseconds <= 250 {
            self.le_250_ms = self.le_250_ms.saturating_add(1);
        }
        if milliseconds <= 500 {
            self.le_500_ms = self.le_500_ms.saturating_add(1);
        }
        if milliseconds <= 1_000 {
            self.le_1000_ms = self.le_1000_ms.saturating_add(1);
        }
    }

    pub(crate) fn merge(&mut self, other: Self) {
        self.count = self.count.saturating_add(other.count);
        self.sum_ms = self.sum_ms.saturating_add(other.sum_ms);
        self.max_ms = self.max_ms.max(other.max_ms);
        self.le_1_ms = self.le_1_ms.saturating_add(other.le_1_ms);
        self.le_5_ms = self.le_5_ms.saturating_add(other.le_5_ms);
        self.le_10_ms = self.le_10_ms.saturating_add(other.le_10_ms);
        self.le_25_ms = self.le_25_ms.saturating_add(other.le_25_ms);
        self.le_50_ms = self.le_50_ms.saturating_add(other.le_50_ms);
        self.le_100_ms = self.le_100_ms.saturating_add(other.le_100_ms);
        self.le_250_ms = self.le_250_ms.saturating_add(other.le_250_ms);
        self.le_500_ms = self.le_500_ms.saturating_add(other.le_500_ms);
        self.le_1000_ms = self.le_1000_ms.saturating_add(other.le_1000_ms);
    }
}

#[cfg(test)]
mod tests {
    use super::LatencyHistogram;

    #[test]
    fn buckets_are_cumulative_bounded_and_merge_saturates() {
        let mut histogram = LatencyHistogram::default();
        histogram.observe_ms(5);
        histogram.observe_ms(251);
        assert_eq!(histogram.count, 2);
        assert_eq!(histogram.sum_ms, 256);
        assert_eq!(histogram.max_ms, 251);
        assert_eq!(histogram.le_1_ms, 0);
        assert_eq!(histogram.le_5_ms, 1);
        assert_eq!(histogram.le_250_ms, 1);
        assert_eq!(histogram.le_500_ms, 2);
        let mut aggregate = LatencyHistogram {
            count: u64::MAX,
            ..LatencyHistogram::default()
        };
        aggregate.merge(histogram);
        assert_eq!(aggregate.count, u64::MAX);
        assert_eq!(aggregate.max_ms, 251);
    }
}
