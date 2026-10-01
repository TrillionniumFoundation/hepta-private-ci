//! Conservative host time shared by the immutable storage and shadow adapters.

use std::time::Instant;

use super::LearningOperatorPublicationErrorV1;

pub(crate) struct LearningOperatorUseClockV1 {
    last_raw_sample: u64,
    anchor_unix_micros: u64,
    anchor: Instant,
}

impl LearningOperatorUseClockV1 {
    pub(crate) fn new(now: u64) -> Self {
        Self {
            last_raw_sample: now,
            anchor_unix_micros: now,
            anchor: Instant::now(),
        }
    }

    pub(crate) fn observe(
        &mut self,
        sampled: u64,
    ) -> Result<u64, LearningOperatorPublicationErrorV1> {
        self.observe_at(sampled, Instant::now())
    }

    fn observe_at(
        &mut self,
        sampled: u64,
        observed_at: Instant,
    ) -> Result<u64, LearningOperatorPublicationErrorV1> {
        let reject = LearningOperatorPublicationErrorV1::Rejected;
        if sampled < self.last_raw_sample {
            return Err(reject("clock regression"));
        }
        let elapsed = observed_at
            .checked_duration_since(self.anchor)
            .ok_or_else(|| reject("clock regression"))?;
        let monotonic = u64::try_from(elapsed.as_micros())
            .ok()
            .and_then(|value| self.anchor_unix_micros.checked_add(value))
            .ok_or_else(|| reject("clock overflow"))?;
        self.last_raw_sample = sampled;
        if sampled > monotonic {
            self.anchor_unix_micros = sampled;
            self.anchor = observed_at;
        }
        // Preserve the anchor on equal/frozen samples so sub-microsecond
        // elapsed fragments accumulate instead of being repeatedly discarded.
        Ok(sampled.max(monotonic))
    }
}

#[cfg(test)]
#[path = "learning_operator_clock_tests.rs"]
mod tests;
