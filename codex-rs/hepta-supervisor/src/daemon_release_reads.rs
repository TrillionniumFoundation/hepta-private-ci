//! A bounded catalog reader carries no lifecycle owner or admission authority.

use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_fleet::ReleaseId;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

const WAIT_BUDGET: Duration = Duration::from_millis(250);

enum ReadJob {
    Validate {
        release_id: ReleaseId,
        reply: oneshot::Sender<Result<(), FleetRegistryError>>,
    },
    #[cfg(test)]
    Pause {
        started: oneshot::Sender<()>,
        resume: mpsc::Receiver<()>,
    },
}

pub(super) enum ReadResult {
    Validated,
    Busy,
    Stopped,
    Rejected(FleetRegistryError),
}

pub(super) struct ReleaseReads {
    jobs: mpsc::SyncSender<ReadJob>,
}

impl ReleaseReads {
    pub(super) fn new(
        registry: FleetRegistry,
        cancellation: CancellationToken,
    ) -> std::io::Result<Self> {
        // One reader and at most one queued read, even after a client times out.
        let (jobs, receiver) = mpsc::sync_channel::<ReadJob>(1);
        std::thread::Builder::new()
            .name("hepta-release-reader".into())
            .spawn(move || {
                while !cancellation.is_cancelled() {
                    let job = match receiver.recv_timeout(Duration::from_millis(100)) {
                        Ok(job) => job,
                        Err(mpsc::RecvTimeoutError::Timeout) => continue,
                        Err(mpsc::RecvTimeoutError::Disconnected) => break,
                    };
                    if cancellation.is_cancelled() {
                        break;
                    }
                    match job {
                        ReadJob::Validate { release_id, reply } => {
                            let result = registry.prevalidate_release(&release_id);
                            let _ = reply.send(result);
                        }
                        #[cfg(test)]
                        ReadJob::Pause { started, resume } => {
                            let _ = started.send(());
                            let _ = resume.recv_timeout(Duration::from_secs(5));
                        }
                    }
                }
            })?;
        // The thread retains only a read-only registry/cache and cancellation.
        // It cannot keep the sole writer lock alive during a cold disk read or
        // make Tokio runtime shutdown wait for its blocking-pool completion.
        Ok(Self { jobs })
    }

    pub(super) async fn prevalidate(
        &self,
        release_id: ReleaseId,
        cancellation: &CancellationToken,
    ) -> ReadResult {
        let (reply, response) = oneshot::channel();
        match self.jobs.try_send(ReadJob::Validate { release_id, reply }) {
            Ok(()) => {}
            Err(mpsc::TrySendError::Full(_)) => return ReadResult::Busy,
            Err(mpsc::TrySendError::Disconnected(_)) => return ReadResult::Stopped,
        }
        tokio::select! {
            _ = cancellation.cancelled() => ReadResult::Stopped,
            result = tokio::time::timeout(WAIT_BUDGET, response) => match result {
                Ok(Ok(Ok(()))) => ReadResult::Validated,
                Ok(Ok(Err(error))) => ReadResult::Rejected(error),
                Ok(Err(_)) => ReadResult::Stopped,
                Err(_) => ReadResult::Busy,
            },
        }
    }

    #[cfg(test)]
    pub(super) async fn pause(&self) -> Result<mpsc::Sender<()>, Box<dyn std::error::Error>> {
        let (started, acknowledgement) = oneshot::channel();
        let (resume, wait) = mpsc::channel();
        self.jobs
            .try_send(ReadJob::Pause {
                started,
                resume: wait,
            })
            .map_err(|_| "read worker was unavailable")?;
        tokio::time::timeout(Duration::from_secs(1), acknowledgement).await??;
        Ok(resume)
    }
}
