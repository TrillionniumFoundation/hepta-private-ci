//! A bounded catalog reader carries no lifecycle owner or admission authority.

use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_fleet::PreparedReleaseRead;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ReleaseReadPin;
use tokio::sync::Mutex;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

const WAIT_BUDGET: Duration = Duration::from_millis(250);

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum ReadPurpose {
    Validate,
    Prepare,
}

pub(super) enum ReadFact {
    Validated(ReleaseReadPin),
    Prepared(PreparedReleaseRead),
}

enum ReadJob {
    Validate {
        release_id: ReleaseId,
        purpose: ReadPurpose,
        reply: oneshot::Sender<Result<ReadFact, FleetRegistryError>>,
    },
    #[cfg(test)]
    Pause {
        started: oneshot::Sender<()>,
        resume: mpsc::Receiver<()>,
    },
}

pub(super) enum ReadResult {
    Ready(ReadFact),
    Busy,
    Stopped,
    Rejected(FleetRegistryError),
}

struct PendingRead {
    release_id: ReleaseId,
    purpose: ReadPurpose,
    response: oneshot::Receiver<Result<ReadFact, FleetRegistryError>>,
}

pub(super) struct ReleaseReads {
    // A timed-out request abandons admission, not the bounded physical read.
    // Its receiver carries progress only; final use rechecks the actual release.
    pending: Mutex<Option<PendingRead>>,
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
                        ReadJob::Validate {
                            release_id,
                            purpose,
                            reply,
                        } => {
                            let result = match purpose {
                                ReadPurpose::Validate => registry
                                    .prevalidate_release_for_launch(&release_id)
                                    .map(ReadFact::Validated),
                                ReadPurpose::Prepare => registry
                                    .prepare_release_for_launch(&release_id)
                                    .map(ReadFact::Prepared),
                            };
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
        Ok(Self {
            jobs,
            pending: Mutex::new(None),
        })
    }

    pub(super) async fn prevalidate(
        &self,
        release_id: ReleaseId,
        purpose: ReadPurpose,
        cancellation: &CancellationToken,
    ) -> ReadResult {
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => ReadResult::Stopped,
            result = tokio::time::timeout(WAIT_BUDGET, self.read(release_id, purpose)) =>
                result.unwrap_or(ReadResult::Busy),
        }
    }

    async fn read(&self, release_id: ReleaseId, purpose: ReadPurpose) -> ReadResult {
        // The same 250ms budget includes both lock acquisition and read wait.
        let mut pending = self.pending.lock().await;
        if let Some(read) = pending.as_mut()
            && (read.release_id != release_id || read.purpose != purpose)
        {
            // Do not queue another release behind a still-running read. A
            // completed result for a different release confers no authority.
            match read.response.try_recv() {
                Err(oneshot::error::TryRecvError::Empty) => return ReadResult::Busy,
                _ => {
                    pending.take();
                }
            }
        }
        if pending.is_none() {
            let (reply, response) = oneshot::channel();
            match self.jobs.try_send(ReadJob::Validate {
                release_id: release_id.clone(),
                purpose,
                reply,
            }) {
                Ok(()) => {
                    *pending = Some(PendingRead {
                        release_id,
                        purpose,
                        response,
                    });
                }
                Err(mpsc::TrySendError::Full(_)) => return ReadResult::Busy,
                Err(mpsc::TrySendError::Disconnected(_)) => return ReadResult::Stopped,
            }
        }
        let Some(read) = pending.as_mut() else {
            return ReadResult::Stopped;
        };
        // Await by mutable reference: cancellation/timeout cannot drop the
        // receiver and make every fresh request restart the same cold read.
        let result = (&mut read.response).await;
        pending.take();
        match result {
            Ok(Ok(pin)) => ReadResult::Ready(pin),
            Ok(Err(FleetRegistryError::ReleasePrevalidationRequired)) => ReadResult::Busy,
            Ok(Err(error)) => ReadResult::Rejected(error),
            Err(_) => ReadResult::Stopped,
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

#[cfg(test)]
#[path = "daemon_release_reads_tests.rs"]
mod tests;
