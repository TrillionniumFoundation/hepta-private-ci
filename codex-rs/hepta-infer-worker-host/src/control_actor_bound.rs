//! Additive bound reservation entrypoint on the existing unique writer.
use super::*;

impl NativeJournalWriterHandle {
    /// Enqueue the opaque preimage proof without retaining source plaintext.
    /// A lost response remains an uncertain acknowledgement, not a new permit.
    pub async fn reserve_bound(
        &self,
        request: NativeRequest,
        maximum_in_flight: usize,
        proof: NativeBoundSourceProof,
    ) -> ActorResult<NativeRunRecord> {
        let (reply, response) = oneshot::channel();
        self.send(Command::ReserveBound {
            request,
            maximum_in_flight,
            proof,
            reply,
        })?;
        self.receive(response).await
    }
}

#[cfg(test)]
#[path = "control_actor_bound_tests.rs"]
mod tests;
