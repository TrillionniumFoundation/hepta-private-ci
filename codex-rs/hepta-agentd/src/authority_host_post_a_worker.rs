//! A single Root-only installation in the existing historical serve scope.
//! The producer submits only after the complete retained-data postchecks.
//! Installation acknowledgement is not a learning or task outcome.

use std::io;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use super::post_a::PostALearningInstallation;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityService;
use crate::HostAuthorityServiceConfig;
use crate::authority_host_runtime::owner_alive;
use crate::authority_host_runtime::verify_pinned_process;
use crate::authority_host_service::generation_publication::original_root;

const PREPARED: u8 = 0;
const SERVING: u8 = 1;
const SUBMITTED: u8 = 2;
const INSTALLED: u8 = 3;
const CLOSED: u8 = 4;

struct InstallationGate {
    phase: AtomicU8,
    session_end: OnceLock<Instant>,
    root_pid: u32,
    boot_id: String,
    start: u64,
}

struct Submission {
    installation: PostALearningInstallation,
    end: Instant,
    acknowledgement: mpsc::SyncSender<()>,
}

struct OriginalInputs {
    learning_handoff: UnixDatagram,
    model_handoff: UnixDatagram,
    publication_handoff: Option<UnixDatagram>,
    independent_b_handoff: Option<UnixDatagram>,
    independent_source_handoff: Option<UnixDatagram>,
    root_pidfd: OwnedFd,
    receiver: mpsc::Receiver<Submission>,
}

pub(super) struct PostALearningWorker {
    inputs: Mutex<Option<OriginalInputs>>,
    gate: Arc<InstallationGate>,
}

pub(super) struct PostALearningSubmitter {
    sender: mpsc::SyncSender<Submission>,
    gate: Arc<InstallationGate>,
}

pub(super) fn prepare(
    learning_handoff: UnixDatagram,
    model_handoff: UnixDatagram,
    root_pidfd: OwnedFd,
    publication_handoff: Option<UnixDatagram>,
    independent_b_handoff: Option<UnixDatagram>,
    independent_source_handoff: Option<UnixDatagram>,
) -> io::Result<(PostALearningSubmitter, PostALearningWorker)> {
    original_root()?;
    let gate = Arc::new(InstallationGate {
        phase: AtomicU8::new(PREPARED),
        session_end: OnceLock::new(),
        root_pid: std::process::id(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .to_owned(),
        start: root_start()?,
    });
    let (sender, receiver) = mpsc::sync_channel(/*bound*/ 1);
    Ok((
        PostALearningSubmitter {
            sender,
            gate: Arc::clone(&gate),
        },
        PostALearningWorker {
            inputs: Mutex::new(Some(OriginalInputs {
                learning_handoff,
                model_handoff,
                publication_handoff,
                independent_b_handoff,
                independent_source_handoff,
                root_pidfd,
                receiver,
            })),
            gate,
        },
    ))
}

impl PostALearningWorker {
    pub(super) fn original_session_end(&self, request_end: Instant) -> io::Result<Instant> {
        let end = *self
            .gate
            .session_end
            .get()
            .ok_or_else(|| io::Error::other("original post-A worker is not serving"))?;
        self.gate.require_original(end)?;
        if request_end > end || self.gate.phase.load(Ordering::Acquire) != SERVING {
            return Err(io::Error::other("original post-A serving interval differs"));
        }
        Ok(end)
    }
}

impl InstallationGate {
    fn require_original(&self, end: Instant) -> io::Result<()> {
        original_root()?;
        if std::process::id() != self.root_pid
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim() != self.boot_id
            || root_start()? != self.start
            || self.phase.load(Ordering::Acquire) == CLOSED
            || Instant::now() >= end
        {
            return Err(io::Error::other("original post-A Root session unavailable"));
        }
        Ok(())
    }
}

impl PostALearningSubmitter {
    pub(super) fn submit(
        self,
        installation: PostALearningInstallation,
        request_end: Instant,
    ) -> io::Result<()> {
        let result = (|| {
            let end = request_end.min(
                *self
                    .gate
                    .session_end
                    .get()
                    .ok_or_else(|| io::Error::other("original post-A worker is not serving"))?,
            );
            self.gate.require_original(end)?;
            self.gate
                .phase
                .compare_exchange(SERVING, SUBMITTED, Ordering::AcqRel, Ordering::Acquire)
                .map_err(|_| io::Error::other("original post-A installation already consumed"))?;
            let (acknowledgement, receiver) = mpsc::sync_channel(/*bound*/ 1);
            self.sender
                .try_send(Submission {
                    installation,
                    end,
                    acknowledgement,
                })
                .map_err(|_| {
                    io::Error::other("original post-A installation channel unavailable")
                })?;
            let remaining = end
                .checked_duration_since(Instant::now())
                .filter(|duration| !duration.is_zero())
                .ok_or_else(|| io::Error::other("original post-A request expired"))?;
            receiver.recv_timeout(remaining).map_err(|_| {
                io::Error::other("original post-A installation acknowledgement uncertain")
            })?;
            self.gate.require_original(end)?;
            if self.gate.phase.load(Ordering::Acquire) != INSTALLED {
                return Err(io::Error::other("original post-A installation was closed"));
            }
            Ok(())
        })();
        if result.is_err() {
            self.gate.phase.store(CLOSED, Ordering::Release);
        }
        result
    }
}

pub(super) fn serve_optional(
    worker: Option<&PostALearningWorker>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    session_end: Instant,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(worker) = worker else {
        return original();
    };
    worker.gate.require_original(session_end)?;
    owner_alive(owner, session_end)?;
    worker
        .gate
        .session_end
        .set(session_end)
        .map_err(|_| io::Error::other("original post-A end already installed"))?;
    let inputs = worker
        .inputs
        .lock()
        .map_err(|_| io::Error::other("original post-A input slot poisoned"))?
        .take()
        .ok_or_else(|| io::Error::other("original post-A inputs already consumed"))?;
    worker
        .gate
        .phase
        .compare_exchange(PREPARED, SERVING, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| io::Error::other("original post-A worker already consumed"))?;
    std::thread::scope(|scope| {
        let running = scope.spawn(|| {
            let result = run_installation(
                inputs,
                &worker.gate,
                service,
                config,
                registration,
                owner,
                session_end,
            );
            if result.is_err() {
                worker.gate.phase.store(CLOSED, Ordering::Release);
            }
            result
        });
        let result = original();
        worker.gate.phase.store(CLOSED, Ordering::Release);
        let installed = running
            .join()
            .map_err(|_| io::Error::other("original post-A worker panicked"))?;
        result.and(installed)
    })
}

fn run_installation(
    inputs: OriginalInputs,
    gate: &InstallationGate,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    session_end: Instant,
) -> io::Result<()> {
    let submission = loop {
        if gate.phase.load(Ordering::Acquire) == CLOSED {
            return Ok(());
        }
        gate.require_original(session_end)?;
        owner_alive(owner, session_end)?;
        match inputs.receiver.try_recv() {
            Ok(submission) => break submission,
            Err(mpsc::TryRecvError::Empty) => std::thread::sleep(Duration::from_millis(5)),
            Err(mpsc::TryRecvError::Disconnected) => return Ok(()),
        }
    };
    let end = submission.end.min(session_end);
    gate.require_original(end)?;
    verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
    let PostALearningInstallation {
        learning,
        learning_bootstrap,
        model_offer,
        publication,
        publication_offer,
        publication_deployment,
        frozen_scope,
        independent_b,
    } = submission.installation;
    if learning.q24_model.is_none()
        || learning
            .backend
            .frozen_scope_binding()
            .map(|scope| scope.to_string())
            .as_deref()
            != Some(frozen_scope.as_str())
    {
        return Err(io::Error::other(
            "original post-A frozen learning or Model owner differs",
        ));
    }
    if publication.is_some() != publication_offer.is_some()
        || publication.is_some() != publication_deployment.is_some()
        || publication.is_some() != inputs.publication_handoff.is_some()
    {
        return Err(io::Error::other(
            "original post-A publication inputs differ",
        ));
    }
    if independent_b.is_some() != inputs.independent_b_handoff.is_some()
        || independent_b.is_some() != inputs.independent_source_handoff.is_some()
    {
        return Err(io::Error::other(
            "original independent B installation inputs differ",
        ));
    }
    let bound = super::super::learning::BoundLearning::bind(learning, config, publication)?;
    let (independent_b, independent_b_offer, independent_source_offer) = match independent_b {
        Some(mut prepared) => {
            let source_offer = crate::authority_host_runtime::PreparedRootIndependentBEvaluationV1::take_original_source_offer(&mut prepared)?;
            let (runtime, offer) = crate::authority_host_runtime::PreparedRootIndependentBEvaluationV1::into_original_parts(prepared);
            let original = super::super::learning::BoundLearning::bind_original_independent_b(
                &bound, runtime, config,
            )?;
            (Some(original), Some(offer), Some(source_offer))
        }
        None => (None, None, None),
    };
    gate.require_original(end)?;
    owner_alive(owner, end)?;
    let timeout = Duration::from_millis(config.timeout_ms);
    let remaining = || {
        end.checked_duration_since(Instant::now())
            .filter(|duration| !duration.is_zero())
            .map(|duration| duration.min(timeout))
            .ok_or_else(|| io::Error::other("original post-A handoff deadline elapsed"))
    };
    if let (Some(handoff), Some(offer)) =
        (inputs.independent_source_handoff, independent_source_offer)
    {
        crate::send_root_independent_b_source_handoff(
            handoff,
            offer,
            &inputs.root_pidfd,
            remaining()?,
        )
        .map_err(io::Error::other)?;
        gate.require_original(end)?;
        owner_alive(owner, end)?;
    }
    crate::send_root_learning_handoff(
        inputs.learning_handoff,
        &learning_bootstrap,
        &inputs.root_pidfd,
        remaining()?,
    )
    .map_err(io::Error::other)?;
    gate.require_original(end)?;
    owner_alive(owner, end)?;
    crate::send_root_q24_model_factory_handoff(
        inputs.model_handoff,
        model_offer,
        &inputs.root_pidfd,
        remaining()?,
    )
    .map_err(io::Error::other)?;
    gate.require_original(end)?;
    owner_alive(owner, end)?;
    if let (Some(handoff), Some(offer)) = (inputs.publication_handoff, publication_offer) {
        crate::send_root_generation_publication_handoff(
            handoff,
            offer,
            &inputs.root_pidfd,
            remaining()?,
        )
        .map_err(io::Error::other)?;
    }
    if let (Some(handoff), Some(offer)) = (inputs.independent_b_handoff, independent_b_offer) {
        crate::send_root_independent_b_evaluation_handoff(
            handoff,
            offer,
            &inputs.root_pidfd,
            remaining()?,
        )
        .map_err(io::Error::other)?;
    }
    gate.require_original(end)?;
    verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
    gate.phase
        .compare_exchange(SUBMITTED, INSTALLED, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| {
            io::Error::other("original post-A installation closed before acknowledgement")
        })?;
    submission
        .acknowledgement
        .try_send(())
        .map_err(|_| io::Error::other("original post-A installation acknowledgement lost"))?;
    gate.require_original(end)?;
    publication::serve_original_material(publication_deployment, gate, || {
        crate::authority_host_runtime::serve_independent_b_until(
            independent_b.as_ref(),
            service,
            config,
            registration,
            owner,
            session_end,
            || {
                super::super::learning::serve_optional_until(
                    Some(&bound),
                    service,
                    config,
                    registration,
                    owner,
                    session_end,
                    || {
                        while gate.phase.load(Ordering::Acquire) != CLOSED {
                            gate.require_original(session_end)?;
                            owner_alive(owner, session_end)?;
                            std::thread::sleep(Duration::from_millis(5));
                        }
                        Ok(())
                    },
                )
            },
        )
    })
}

#[path = "authority_host_post_a_publication_worker.rs"]
mod publication;

fn root_start() -> io::Result<u64> {
    std::fs::read_to_string("/proc/self/stat")?
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("original Root process incarnation missing"))
}
