//! A test observation around the actual C readiness response. It preserves
//! every original byte and waits only inside the original 500 ms exchange
//! envelope so the production post-handler absolute deadline must reject it.

use super::*;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> OriginalCircuitLearningReadOwnerV1<C, S> {
    pub(crate) fn fixture_evaluated_next_use_deadline_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
        end: Instant,
        cross_end_after_original_read: bool,
        response_observed: Arc<AtomicBool>,
    ) -> Result<u64, Error> {
        self.serve_original_evaluated_next_use_profile(channel, end, |owner, bytes, request_id| {
            let original = owner.readiness_response(bytes, request_id)?;
            response_observed.store(true, Ordering::Release);
            if cross_end_after_original_read {
                while Instant::now() < end {
                    std::thread::yield_now();
                }
            }
            Ok(original)
        })
    }
}
