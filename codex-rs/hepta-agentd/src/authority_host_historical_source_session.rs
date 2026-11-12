//! Finite in-process Root capture beside the original Initial service.
//! Inputs are fixed before serving; the one-shot request contains only an ACK
//! channel. No daemon wire can choose source files, observations or a new owner.

use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::time::Instant;

use super::*;
use crate::authority_host_runtime::owner_alive;
use crate::authority_host_runtime::verify_pinned_process;
use crate::authority_host_service::generation_initial::RegisteredGenerationInitial;
use crate::authority_host_service::generation_initial::historical_source_pin::RetainedRootHistoricalSourceInputsV1;
use crate::authority_host_service::generation_initial::historical_source_pin::RootHistoricalSourceInputsV1;
use codex_hepta_types::Digest32;

const ACKNOWLEDGED: u8 = 4;

struct Submission {
    acknowledgement: mpsc::SyncSender<Result<Digest32, String>>,
}

#[derive(Clone)]
struct RootLifetime {
    pid: u32,
    boot: String,
    start: u64,
}

impl RootLifetime {
    fn require_current(&self) -> io::Result<()> {
        crate::authority_host_service::generation_initial::original_root()?;
        if std::process::id() != self.pid
            || super::root_start()? != self.start
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim() != self.boot
        {
            return Err(io::Error::other(
                "same original Root source-capture process required",
            ));
        }
        Ok(())
    }
}

/// Root's acknowledgement of one protected data pin, not a historical grant.
pub struct RootHistoricalSourceCaptureReceiptV1 {
    pin: Digest32,
}

impl RootHistoricalSourceCaptureReceiptV1 {
    pub fn pin_digest(&self) -> Digest32 {
        self.pin
    }
}

/// This Root-created capability never crosses the daemon handoff. An attempted
/// capture consumes it, including busy files, deadlines and uncertain replies.
pub struct RootHistoricalSourceCaptureCapabilityV1 {
    sender: mpsc::SyncSender<Submission>,
    phase: Arc<AtomicU8>,
    root: RootLifetime,
    end: Arc<OnceLock<Instant>>,
}

impl RootHistoricalSourceCaptureCapabilityV1 {
    pub fn capture(self) -> io::Result<RootHistoricalSourceCaptureReceiptV1> {
        self.root.require_current()?;
        let end = *self
            .end
            .get()
            .ok_or_else(|| io::Error::other("original source capture has not started"))?;
        self.phase
            .compare_exchange(ACTIVE, CONSUMED, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| io::Error::other("original one-shot source capture is not active"))?;
        let result = (|| {
            let remaining = end
                .checked_duration_since(Instant::now())
                .filter(|remaining| !remaining.is_zero())
                .ok_or_else(|| io::Error::other("original source capture expired"))?;
            let (acknowledgement, receiver) = mpsc::sync_channel(1);
            self.sender
                .try_send(Submission { acknowledgement })
                .map_err(|_| io::Error::other("original source capture channel unavailable"))?;
            let pin = receiver
                .recv_timeout(remaining)
                .map_err(|_| io::Error::other("source capture acknowledgement uncertain"))?
                .map_err(io::Error::other)?;
            self.root.require_current()?;
            if Instant::now() >= end {
                return Err(io::Error::other(
                    "source acknowledgement arrived after deadline",
                ));
            }
            self.phase
                .compare_exchange(CONSUMED, ACKNOWLEDGED, Ordering::AcqRel, Ordering::Acquire)
                .map_err(|_| {
                    io::Error::other("original source capture ended during acknowledgement")
                })?;
            Ok(RootHistoricalSourceCaptureReceiptV1 { pin })
        })();
        if result.is_err() {
            self.phase.store(CLOSED, Ordering::Release);
        }
        result
    }
}

pub(super) struct HistoricalSourceRuntime {
    receiver: Mutex<mpsc::Receiver<Submission>>,
    inputs: Mutex<Option<RetainedRootHistoricalSourceInputsV1>>,
    phase: Arc<AtomicU8>,
    root: RootLifetime,
    end: Arc<OnceLock<Instant>>,
}

pub(super) struct SourceCaptureContext<'a> {
    pub(super) service: &'a HostAuthorityService,
    pub(super) config: &'a HostAuthorityServiceConfig,
    pub(super) registration: &'a HostAuthorityRegistration,
    pub(super) owner: &'a OwnedFd,
    pub(super) slot: &'a RegisteredGenerationInitial,
    pub(super) stopping: &'a AtomicBool,
    pub(super) end: Instant,
}

impl PreparedHostAuthoritySession {
    /// Fix the original files before releasing A. The caller retains this cap
    /// until A has released its Source writer but still holds its process/session.
    pub fn enable_initial_source_capture(
        &mut self,
        inputs: RootHistoricalSourceInputsV1,
    ) -> io::Result<RootHistoricalSourceCaptureCapabilityV1> {
        crate::authority_host_service::generation_initial::original_root()?;
        let initial = self
            .initial_publication
            .as_mut()
            .ok_or_else(|| io::Error::other("original Initial route required"))?;
        if initial.source_capture.is_some() || initial.phase.load(Ordering::Acquire) != PREPARED {
            return Err(io::Error::other(
                "original source capture already enabled or serving",
            ));
        }
        let mut retained = None;
        self.service.with_initial_publication_context(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            |_| {
                retained = Some(inputs.retain_original(
                    &self.registration.registered_identity.identity()?,
                    &initial.deployment.target,
                    self.config.peer_uid,
                    self.config.peer_gid,
                )?);
                Ok(())
            },
        )?;
        let root = RootLifetime {
            pid: std::process::id(),
            boot: self.registration.boot_id.clone(),
            start: super::root_start()?,
        };
        root.require_current()?;
        let (sender, receiver) = mpsc::sync_channel(1);
        let phase = Arc::new(AtomicU8::new(PREPARED));
        let end = Arc::new(OnceLock::new());
        initial.source_capture = Some(HistoricalSourceRuntime {
            receiver: Mutex::new(receiver),
            inputs: Mutex::new(retained),
            phase: Arc::clone(&phase),
            root: root.clone(),
            end: Arc::clone(&end),
        });
        Ok(RootHistoricalSourceCaptureCapabilityV1 {
            sender,
            phase,
            root,
            end,
        })
    }
}

impl HistoricalSourceRuntime {
    pub(super) fn serve(&self, context: SourceCaptureContext<'_>) -> io::Result<()> {
        self.root.require_current()?;
        self.end
            .set(context.end)
            .map_err(|_| io::Error::other("original source capture deadline already fixed"))?;
        self.phase
            .compare_exchange(PREPARED, ACTIVE, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| io::Error::other("original source capture already consumed"))?;
        let receiver = self
            .receiver
            .try_lock()
            .map_err(|_| io::Error::other("source receiver busy"))?;
        let submission = loop {
            if context.stopping.load(Ordering::Acquire) {
                return Ok(());
            }
            if self.phase.load(Ordering::Acquire) == CLOSED {
                return Err(io::Error::other("original source capture closed"));
            }
            owner_alive(context.owner, context.end)?;
            match receiver.try_recv() {
                Ok(submission) => break submission,
                Err(mpsc::TryRecvError::Empty) => std::thread::sleep(Duration::from_millis(5)),
                Err(mpsc::TryRecvError::Disconnected) => return Ok(()),
            }
        };
        let outcome = (|| {
            if self.phase.load(Ordering::Acquire) != CONSUMED {
                return Err(io::Error::other(
                    "original source request is no longer active",
                ));
            }
            let inputs = self
                .inputs
                .lock()
                .map_err(|_| io::Error::other("source inputs poisoned"))?
                .take()
                .ok_or_else(|| io::Error::other("original source inputs consumed"))?;
            let pin = context.service.capture_initial_source_pin(
                context.slot,
                context.config,
                context.registration,
                context.owner,
                inputs,
            )?;
            let delivered = (|| {
                let digest = pin.readback_digest()?;
                self.root.require_current()?;
                verify_pinned_process(
                    context.registration,
                    context.config.peer_uid,
                    context.config.peer_gid,
                    context.owner,
                    context.end,
                )?;
                if context.stopping.load(Ordering::Acquire)
                    || self.phase.load(Ordering::Acquire) != CONSUMED
                {
                    return Err(io::Error::other(
                        "original source capture closed before acknowledgement",
                    ));
                }
                submission
                    .acknowledgement
                    .try_send(Ok(digest))
                    .map_err(|_| {
                        io::Error::other("original source capture acknowledgement lost")
                    })?;
                loop {
                    match self.phase.load(Ordering::Acquire) {
                        ACKNOWLEDGED => return Ok(()),
                        CONSUMED => {}
                        _ => return Err(io::Error::other("source acknowledgement not consumed")),
                    }
                    let live = self.root.require_current().and_then(|()| {
                        if context.stopping.load(Ordering::Acquire) {
                            return Err(io::Error::other("source capture session ended"));
                        }
                        owner_alive(context.owner, context.end)
                    });
                    if let Err(error) = live {
                        if self.phase.compare_exchange(
                            CONSUMED,
                            CLOSED,
                            Ordering::AcqRel,
                            Ordering::Acquire,
                        ) == Err(ACKNOWLEDGED)
                        {
                            return Ok(());
                        }
                        return Err(error);
                    }
                    std::thread::sleep(Duration::from_millis(5));
                }
            })();
            if delivered.is_err() {
                pin.fence()?;
            }
            delivered
        })();
        if let Err(error) = &outcome {
            let _ = submission.acknowledgement.try_send(Err(error.to_string()));
            self.close();
        }
        outcome
    }

    pub(super) fn close(&self) {
        let _ = self
            .phase
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |phase| {
                (phase != ACKNOWLEDGED).then_some(CLOSED)
            });
    }
}

impl Drop for HistoricalSourceRuntime {
    fn drop(&mut self) {
        self.close();
    }
}

pub(super) fn serve_optional(
    source: Option<&HistoricalSourceRuntime>,
    context: SourceCaptureContext<'_>,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(source) = source else {
        return original();
    };
    std::thread::scope(|scope| {
        let capture = scope.spawn(|| source.serve(context));
        let served = original();
        source.close();
        let captured = capture
            .join()
            .map_err(|_| io::Error::other("original source capture worker panicked"))?;
        served.and(captured)
    })
}

#[cfg(test)]
#[path = "authority_host_historical_source_session_tests.rs"]
mod tests;
