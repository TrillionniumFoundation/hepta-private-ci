//! One task owns one original physical subscription. Consumer select/timer
//! cancellation never drops an event after its original callback was received.
use super::*;

pub struct AgentdTextEvents {
    shared: Arc<Shared>,
    observations: tokio::sync::mpsc::Receiver<Result<AgentdTextObservation, TextSessionError>>,
    stop: Option<tokio::sync::oneshot::Sender<()>>,
    task: Option<tokio::task::JoinHandle<Result<(), TextSessionError>>>,
}

impl AgentdTextEvents {
    pub(in super::super) fn start(client: RemoteAppServerClient, shared: Arc<Shared>) -> Self {
        // Backpressure retains at most one projected observation plus the one
        // original event being read. The original transport keeps its own cap.
        let (output, observations) = tokio::sync::mpsc::channel(1);
        let (stop, mut stopped) = tokio::sync::oneshot::channel();
        let mut reader = TextEventReader {
            client,
            shared: shared.clone(),
            ended: false,
        };
        let task = tokio::spawn(async move {
            loop {
                // Only explicit shutdown/connection replacement or dropping
                // this subscription cancels a callback/preview already read.
                let result = tokio::select! {
                    _ = &mut stopped => break,
                    result = reader.next_observation() => result,
                };
                let (observation, terminal) = match result {
                    Ok(Some(observation)) => (Ok(observation), false),
                    Ok(None) => break,
                    Err(error) => (Err(error), true),
                };
                let delivered = tokio::select! {
                    _ = &mut stopped => break,
                    delivered = output.send(observation) => delivered,
                };
                if delivered.is_err() || terminal {
                    break;
                }
            }
            reader.shutdown().await
        });
        Self {
            shared,
            observations,
            stop: Some(stop),
            task: Some(task),
        }
    }

    /// Cancellation-safe receive. The single producer task keeps ownership of
    /// in-progress original approval preview/readback across caller polls.
    pub async fn next_observation(
        &mut self,
    ) -> Result<Option<AgentdTextObservation>, TextSessionError> {
        loop {
            drop(self.shared.current()?);
            match self.observations.recv().await {
                Some(Ok(observation)) => {
                    // History may have installed a full snapshot after this
                    // event was projected or while its bounded send waited.
                    // Never append these old deltas/started items over it.
                    let state = self.shared.current()?;
                    if let AgentdTextObservation::Notification(event) = &observation
                        && state.snapshot_turns.contains_key(&event.turn_id)
                    {
                        continue;
                    }
                    return Ok(Some(observation));
                }
                Some(Err(error)) => return Err(error),
                None => {
                    self.shared.state()?.fenced = true;
                    return Ok(None);
                }
            }
        }
    }

    pub async fn next(&mut self) -> Result<Option<AgentdTextEvent>, TextSessionError> {
        loop {
            match self.next_observation().await? {
                Some(AgentdTextObservation::Notification(event)) => return Ok(Some(event)),
                Some(AgentdTextObservation::Approval(_)) => {}
                None => return Ok(None),
            }
        }
    }

    pub async fn shutdown(mut self) -> Result<(), TextSessionError> {
        self.shared.state()?.fenced = true;
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        let Some(mut task) = self.task.take() else {
            return Ok(());
        };
        match tokio::time::timeout(REQUEST_TIMEOUT + Duration::from_secs(1), &mut task).await {
            Ok(result) => result.map_err(unavailable)?,
            Err(error) => {
                task.abort();
                let _ = task.await;
                Err(unavailable(error))
            }
        }
    }
}

impl Drop for AgentdTextEvents {
    fn drop(&mut self) {
        // Do not abort the producer during ordinary polling. Closing this
        // subscription explicitly signals it to shut down its original client.
        if let Ok(mut state) = self.shared.state() {
            state.fenced = true;
        }
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
    }
}
