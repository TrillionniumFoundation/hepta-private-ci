//! Observe only after the Version handler produced the actual C response.
//! Yielding narrows the test deadline within the original 500 ms envelope;
//! no response, owner, clock value or successful freshness result is supplied.

use super::*;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> OriginalCircuitLearningReadOwnerV1<C, S> {
    pub(crate) fn fixture_observe_original_next_use_response(
        &self,
        end: Instant,
        cross_end_after_original_read: bool,
        response_observed: Arc<AtomicBool>,
    ) {
        response_observed.store(true, Ordering::Release);
        if cross_end_after_original_read {
            while Instant::now() < end {
                std::thread::yield_now();
            }
        }
    }
}
