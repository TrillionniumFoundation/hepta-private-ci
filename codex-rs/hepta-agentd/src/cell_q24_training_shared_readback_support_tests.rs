//! Scheduling and observation of the actual original Trainer command handler.
//! Every response is produced by command_response and forwarded unchanged.
//! This same-process test transport does not exercise public peer admission.

use std::sync::Arc;
use std::sync::Condvar;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use tokio::sync::oneshot;

use super::wire;
use crate::OriginalCellQ24TrainingCommandErrorV1 as Error;
use crate::OriginalCellQ24TrainingCommandOwnerV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct OriginalFrame {
    pub(crate) request_id: u64,
    pub(crate) completed: bool,
}

struct Release {
    released: Mutex<bool>,
    changed: Condvar,
}

impl Release {
    fn release(&self) {
        // Releasing a test scheduling latch cannot claim a command result.
        let mut released = self
            .released
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        *released = true;
        self.changed.notify_all();
    }
}

struct PendingPause {
    entered: oneshot::Sender<u64>,
    release: Arc<Release>,
}

struct State {
    frames: Mutex<Vec<OriginalFrame>>,
    pending: Mutex<Option<PendingPause>>,
    active_release: Mutex<Option<Arc<Release>>>,
    armed_once: AtomicBool,
    scheduling_failed: AtomicBool,
}

/// This control holds no stream, signing key, original receipt or client.
#[derive(Clone)]
pub(crate) struct ReadbackControl {
    state: Arc<State>,
}

pub(crate) struct OriginalResponsePause {
    entered: Option<oneshot::Receiver<u64>>,
    release: Arc<Release>,
}

impl OriginalResponsePause {
    pub(crate) async fn entered(&mut self) -> anyhow::Result<u64> {
        self.entered
            .take()
            .ok_or_else(|| anyhow::anyhow!("one original response observation"))?
            .await
            .map_err(|_| anyhow::anyhow!("original response pause not reached"))
    }

    pub(crate) fn release(&self) {
        self.release.release();
    }
}

impl Drop for OriginalResponsePause {
    fn drop(&mut self) {
        self.release.release();
    }
}

impl ReadbackControl {
    pub(crate) fn pause_after_next_original_response(
        &self,
    ) -> anyhow::Result<OriginalResponsePause> {
        anyhow::ensure!(
            !self.state.armed_once.swap(true, Ordering::AcqRel),
            "one scheduling fault per original peer"
        );
        let (entered, receive) = oneshot::channel();
        let release = Arc::new(Release {
            released: Mutex::new(false),
            changed: Condvar::new(),
        });
        *self
            .state
            .active_release
            .lock()
            .map_err(|_| anyhow::anyhow!("original scheduling release lock"))? =
            Some(Arc::clone(&release));
        let mut pending = self
            .state
            .pending
            .lock()
            .map_err(|_| anyhow::anyhow!("original scheduling arm lock"))?;
        anyhow::ensure!(pending.is_none(), "no earlier original pause");
        *pending = Some(PendingPause {
            entered,
            release: Arc::clone(&release),
        });
        Ok(OriginalResponsePause {
            entered: Some(receive),
            release,
        })
    }

    pub(crate) fn frames(&self) -> anyhow::Result<Vec<OriginalFrame>> {
        Ok(self
            .state
            .frames
            .lock()
            .map_err(|_| anyhow::anyhow!("original frame observation lock"))?
            .clone())
    }

    pub(crate) fn scheduling_failed(&self) -> bool {
        self.state.scheduling_failed.load(Ordering::Acquire)
    }

    pub(crate) fn release_all(&self) {
        if let Ok(mut pending) = self.state.pending.lock() {
            pending.take();
        }
        if let Ok(release) = self.state.active_release.lock()
            && let Some(release) = release.as_ref()
        {
            release.release();
        }
    }

    fn after_original_response(&self, request_id: u64, bytes: &[u8]) -> anyhow::Result<()> {
        let response: wire::Response = serde_json::from_slice(bytes)?;
        self.state
            .frames
            .lock()
            .map_err(|_| anyhow::anyhow!("original frame observation lock"))?
            .push(OriginalFrame {
                request_id,
                completed: matches!(response.result, wire::CommandResult::Completed { .. }),
            });
        let pause = self
            .state
            .pending
            .lock()
            .map_err(|_| anyhow::anyhow!("original scheduling arm lock"))?
            .take();
        if let Some(pause) = pause {
            pause
                .entered
                .send(request_id)
                .map_err(|_| anyhow::anyhow!("original response observer disappeared"))?;
            let released = pause
                .release
                .released
                .lock()
                .map_err(|_| anyhow::anyhow!("original scheduling release lock"))?;
            // Fault scheduling has a bounded unwind path. This does not change
            // the original channel's timeout, absolute lifetime or frame limit.
            let (released, _) = pause
                .release
                .changed
                .wait_timeout_while(released, Duration::from_secs(5), |released| !*released)
                .map_err(|_| anyhow::anyhow!("original scheduling wait lock"))?;
            anyhow::ensure!(*released, "original response pause timed out");
        }
        Ok(())
    }
}

pub(crate) fn serve<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>,
    mut channel: HostAuthorityPeerChannel,
) -> (ReadbackControl, JoinHandle<Result<u64, Error>>) {
    let control = ReadbackControl {
        state: Arc::new(State {
            frames: Mutex::new(Vec::new()),
            pending: Mutex::new(None),
            active_release: Mutex::new(None),
            armed_once: AtomicBool::new(false),
            scheduling_failed: AtomicBool::new(false),
        }),
    };
    let observed = control.clone();
    let thread = std::thread::spawn(move || {
        // The original service's 128-request loop and error behavior remain.
        let mut next_request_id = 1_u64;
        for count in 0..128_u64 {
            let exchanged = channel.exchange(|bytes| {
                let response = owner
                    .command_response(bytes, next_request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if observed
                    .after_original_response(next_request_id, &response)
                    .is_err()
                {
                    observed
                        .state
                        .scheduling_failed
                        .store(true, Ordering::Release);
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                Ok(response)
            })?;
            if !exchanged {
                return Ok(count);
            }
            next_request_id = next_request_id
                .checked_add(1)
                .ok_or(Error::Binding("Trainer request id overflow"))?;
        }
        Err(Error::Unavailable)
    });
    (control, thread)
}
