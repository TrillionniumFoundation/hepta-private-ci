//! Bounded native read request on the existing required original-turn owner.
use super::material_client::AgentdPairedMaterialClient;
use super::material_client::PairedTrainingReadResult;
use super::*;

pub struct AgentdPairedTraining {
    sender: mpsc::Sender<PendingTraining>,
    registration: PairedPreparationRegistration,
}

impl AgentdPairedTraining {
    pub async fn read_training(
        &self,
        request: PairedPreparationRequest,
    ) -> Result<PairedTrainingReadResult, AgentdError> {
        request.identity(&self.registration)?;
        let delivery = request.original.delivery_id;
        let deadline = Instant::now() + DEADLINE;
        let (reply, response) = oneshot::channel();
        self.sender
            .try_send(PendingTraining {
                request,
                deadline,
                reply,
                preparing: Arc::new(AtomicBool::new(false)),
            })
            .map_err(|_| invalid("original paired training owner is closed or occupied"))?;
        match tokio::time::timeout_at(deadline, response).await {
            Ok(Ok(value)) => value,
            _ => Ok(PairedTrainingReadResult::Unknown {
                original_delivery: delivery,
            }),
        }
    }
}

pub(crate) struct TrainingLane {
    pub(crate) receiver: mpsc::Receiver<PendingTraining>,
    pub(crate) journal: PreparationJournal,
    client: AgentdPairedMaterialClient,
}

impl TrainingLane {
    pub(crate) fn attach(
        journal: &PreparationJournal,
        client: AgentdPairedMaterialClient,
    ) -> Result<(AgentdPairedTraining, Self), AgentdError> {
        if client.registration != journal.registration {
            return Err(invalid(
                "original paired training client and journal registration differ",
            ));
        }
        let (sender, receiver) = mpsc::channel(1);
        let handle = AgentdPairedTraining {
            sender,
            registration: journal.registration.clone(),
        };
        Ok((
            handle,
            Self {
                receiver,
                journal: PreparationJournal {
                    writer: Arc::clone(&journal.writer),
                    registration: journal.registration.clone(),
                    route: journal.route.clone(),
                },
                client,
            },
        ))
    }

    pub(crate) async fn read_verified(
        &self,
        request: &PairedPreparationRequest,
        verified: &VerifiedPairedTurn,
        preparing: &AtomicBool,
    ) -> Result<PairedTrainingReadResult, AgentdError> {
        match self
            .journal
            .prepare_original_continuation(request, verified, preparing)
            .await?
        {
            PreparedOriginal::Fresh { continuation, .. } => {
                self.client.read_original(continuation).await
            }
            PreparedOriginal::Retained(_) => Ok(PairedTrainingReadResult::RetainedReadOnly {
                original_delivery: request.original.delivery_id,
            }),
        }
    }
}

pub(crate) struct PendingTraining {
    pub(crate) request: PairedPreparationRequest,
    deadline: Instant,
    reply: oneshot::Sender<Result<PairedTrainingReadResult, AgentdError>>,
    pub(crate) preparing: Arc<AtomicBool>,
}

impl PendingTraining {
    pub(crate) async fn complete_on_owner(
        mut self,
        cancellation: &CancellationToken,
        read: impl std::future::Future<Output = Result<PairedTrainingReadResult, AgentdError>>,
    ) {
        if self.reply.is_closed() {
            return;
        }
        let result = if cancellation.is_cancelled() || Instant::now() >= self.deadline {
            Err(invalid("original paired training owner ended or expired"))
        } else {
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => Err(invalid("original paired training owner cancelled")),
                _ = self.reply.closed() => return,
                value = tokio::time::timeout_at(self.deadline, read) => value.unwrap_or_else(|_| Err(invalid("original paired training deadline elapsed"))),
            }
        };
        let result =
            if cancellation.is_cancelled() || Instant::now() >= self.deadline || result.is_err() {
                if self.preparing.load(Ordering::SeqCst) {
                    Ok(PairedTrainingReadResult::Unknown {
                        original_delivery: self.request.original.delivery_id,
                    })
                } else {
                    result.and_then(|_| {
                        Err(invalid(
                            "original paired training owner ended before preparation",
                        ))
                    })
                }
            } else {
                result
            };
        let _ = self.reply.send(result);
    }
}

#[cfg(test)]
#[path = "paired_training_tests.rs"]
mod tests;
