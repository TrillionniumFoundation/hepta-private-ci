//! Required same-process consumer of one original Core hint. The result moves
//! to its retained owner; a read result is never a model-training receipt.
use super::*;

pub(crate) struct OriginalPairedTrainingDelivery {
    pub(crate) request: PairedPreparationRequest,
    pub(crate) result: Result<PairedTrainingReadResult, AgentdError>,
}

pub(crate) struct OriginalPairedTrainingConsumer {
    training: AgentdPairedTraining,
    request: oneshot::Receiver<PairedPreparationRequest>,
    reply: oneshot::Sender<OriginalPairedTrainingDelivery>,
}

impl OriginalPairedTrainingConsumer {
    pub(crate) fn new(
        training: AgentdPairedTraining,
        request: oneshot::Receiver<PairedPreparationRequest>,
    ) -> (Self, oneshot::Receiver<OriginalPairedTrainingDelivery>) {
        let (reply, response) = oneshot::channel();
        (
            Self {
                training,
                request,
                reply,
            },
            response,
        )
    }

    pub(crate) async fn run(mut self, cancellation: CancellationToken) -> Result<(), AgentdError> {
        let request = tokio::select! {
            biased;
            _ = cancellation.cancelled() => return Ok(()),
            _ = self.reply.closed() => return Err(invalid("original paired material owner closed")),
            request = &mut self.request => request.map_err(|_| invalid("original paired hint owner closed"))?,
        };
        // This task is distinct from the original Notes owner. Awaiting its
        // request inside that owner's event loop would deadlock the same lane.
        let result = tokio::select! {
            biased;
            _ = cancellation.cancelled() => return Ok(()),
            _ = self.reply.closed() => return Err(invalid("original paired material owner closed during read")),
            result = self.training.read_training(request.clone()) => result,
        };
        self.reply
            .send(OriginalPairedTrainingDelivery { request, result })
            .map_err(|_| invalid("original paired material owner closed before delivery"))?;
        // Required owners remain joined through runtime cancellation. No
        // second hint, new channel, replayed read or automatic retry is made.
        cancellation.cancelled().await;
        Ok(())
    }
}

#[cfg(test)]
#[path = "paired_training_consumer_tests.rs"]
mod tests;
