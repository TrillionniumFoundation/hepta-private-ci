struct StageHistogram {
    buckets: [AtomicU64; BUCKETS_US.len()],
    samples: AtomicU64,
    max_us: AtomicU64,
}

impl Default for StageHistogram {
    fn default() -> Self {
        Self {
            buckets: array::from_fn(|_| AtomicU64::new(0)),
            samples: AtomicU64::new(0),
            max_us: AtomicU64::new(0),
        }
    }
}

impl fmt::Debug for StageHistogram {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("StageHistogram")
            .field("samples", &self.samples.load(Ordering::Relaxed))
            .field("max_us", &self.max_us.load(Ordering::Relaxed))
            .finish_non_exhaustive()
    }
}

impl StageHistogram {
    fn observe(&self, duration: Duration) {
        let micros = u64::try_from(duration.as_micros()).unwrap_or(u64::MAX);
        let bucket = BUCKETS_US
            .iter()
            .position(|upper| micros <= *upper)
            .unwrap_or(BUCKETS_US.len() - 1);
        self.buckets[bucket].fetch_add(1, Ordering::Relaxed);
        self.samples.fetch_add(1, Ordering::Relaxed);
        self.max_us.fetch_max(micros, Ordering::Relaxed);
    }

    fn snapshot(&self, stage: ArtifactOwnerStageV1) -> ArtifactOwnerStageLatencyV1 {
        let samples = self.samples.load(Ordering::Relaxed);
        ArtifactOwnerStageLatencyV1 {
            stage,
            samples,
            p50_upper_bound_us: self.percentile(samples, 50),
            p95_upper_bound_us: self.percentile(samples, 95),
            p99_upper_bound_us: self.percentile(samples, 99),
            max_us: self.max_us.load(Ordering::Relaxed),
        }
    }

    fn percentile(&self, samples: u64, percent: u64) -> u64 {
        if samples == 0 {
            return 0;
        }
        let target = samples.saturating_mul(percent).saturating_add(99) / 100;
        let mut cumulative = 0_u64;
        for (index, bucket) in self.buckets.iter().enumerate() {
            cumulative = cumulative.saturating_add(bucket.load(Ordering::Relaxed));
            if cumulative >= target {
                return BUCKETS_US[index];
            }
        }
        u64::MAX
    }
}

