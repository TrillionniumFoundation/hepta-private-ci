//! One-shot late enrollment in the same retained Root session. The capability
//! never reaches the daemon; only trusted Root can supply original capabilities.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

use super::*;
use crate::authority_host_service::generation_publication::PublicationBootstrap;
use crate::authority_host_service::generation_publication::PURPOSE;
use crate::authority_host_service::generation_publication::SOCKET;

#[path = "authority_host_generation_publication_runtime.rs"]
mod runtime;
pub(super) use runtime::BoundPublication;
pub(super) use runtime::serve_optional;

const PREPARED: u8 = 0;
const ACTIVE: u8 = 1;
const CONSUMED: u8 = 2;
const CLOSED: u8 = 3;

struct Submission {
    inputs: crate::RootGenerationPublicationEnrollmentV1,
    acknowledgement: mpsc::SyncSender<Result<String, String>>,
}

pub(super) struct PublicationRuntime {
    receiver: Mutex<mpsc::Receiver<Submission>>,
    phase: Arc<AtomicU8>,
    socket: PathBuf,
}

/// A consumed original Root registration acknowledgement. The digest is a
/// data pin; it neither constructs a daemon CURRENT owner nor grants execution.
pub struct RootGenerationPublicationRegistrationV1 {
    binding: String,
}

impl RootGenerationPublicationRegistrationV1 {
    pub fn binding(&self) -> &str { &self.binding }
}

/// Held only by the original trusted Root host. It is not Clone/Serialize and
/// cannot accept a daemon wire payload. Use it once after the real decision,
/// then let the daemon connect its already sealed purpose route.
pub struct RootGenerationPublicationEnrollmentCapabilityV1 {
    sender: mpsc::SyncSender<Submission>,
    phase: Arc<AtomicU8>,
    root_pid: u32,
    boot_id: String,
    process_start_ticks: u64,
    lifetime: Duration,
}

impl RootGenerationPublicationEnrollmentCapabilityV1 {
    /// Register actual original owners in the concurrently serving same Root.
    /// Timeout consumes the capability; it never retries, re-signs or changes
    /// Reserve into Recover. Existing persisted state requires explicit recovery.
    pub fn register(
        self,
        inputs: crate::RootGenerationPublicationEnrollmentV1,
    ) -> io::Result<RootGenerationPublicationRegistrationV1> {
        crate::authority_host_service::generation_publication::original_root()?;
        if std::process::id() != self.root_pid
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim() != self.boot_id
            || root_start()? != self.process_start_ticks
            || self.phase.compare_exchange(ACTIVE, CONSUMED, Ordering::AcqRel, Ordering::Acquire).is_err()
        {
            return Err(io::Error::other("original live one-shot Root enrollment required"));
        }
        let (acknowledgement, receiver) = mpsc::sync_channel(1);
        self.sender.try_send(Submission { inputs, acknowledgement })
            .map_err(|_| io::Error::other("original publication enrollment channel unavailable"))?;
        let binding = receiver.recv_timeout(self.lifetime)
            .map_err(|_| io::Error::other("publication enrollment acknowledgement uncertain"))?
            .map_err(io::Error::other)?;
        if self.phase.load(Ordering::Acquire) != CONSUMED {
            return Err(io::Error::other("original publication session ended during enrollment"));
        }
        Ok(RootGenerationPublicationRegistrationV1 { binding })
    }
}

impl PreparedHostAuthoritySession {
    /// Enable only a fixed-purpose route from this session's actual learning
    /// backend. No CURRENT, consumer, trust or selection is supplied over IPC.
    /// The returned enrollment capability stays with the original Root host.
    pub fn enable_generation_publication(
        &mut self,
    ) -> io::Result<(
        RootGenerationPublicationEnrollmentCapabilityV1,
        crate::RootGenerationPublicationOfferV1,
    )> {
        crate::authority_host_service::generation_publication::original_root()?;
        if self.publication.is_some() {
            return Err(io::Error::other("original publication route already enabled"));
        }
        let learning = self.learning.as_ref()
            .ok_or_else(|| io::Error::other("original scoped learning owner required"))?;
        let (bundle, bootstrap) = self.service.with_learning_profile(
            &self.config, &self.registration, &self.owner_pidfd, &learning.profile,
            |initial, proof| {
                let scope = learning.profile.require_cell_scope(&initial)?;
                if learning.backend.frozen_scope_binding() != Some(scope.binding()) {
                    return Err(io::Error::other("actual learning scope differs from publication route"));
                }
                // A registered vacant checkpoint is legitimate before the
                // original learning client starts. Capture only its route;
                // late enrollment still requires the actual completed decision.
                let before = learning.backend.restore(&initial.request).map_err(io::Error::other)?;
                if let Some(snapshot) = &before {
                    scope.validate_snapshot(snapshot).map_err(io::Error::other)?;
                }
                let bundle = PublicationBootstrap {
                    purpose: PURPOSE.into(), learning_operation: initial.request.operation_id.to_string(),
                    root: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                        uid: 0, pid: std::process::id(), boot_id: self.registration.boot_id.clone(),
                        process_start_ticks: root_start()?,
                    },
                    consumer: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                        uid: self.config.peer_uid, pid: self.registration.peer_pid,
                        boot_id: self.registration.boot_id.clone(),
                        process_start_ticks: self.registration.process_start_ticks,
                    },
                    identity: self.registration.registered_identity.clone(),
                    initial: initial.head_digest.to_string(), scope: scope.binding().to_string(), writer: proof,
                    socket: self.config.sockets.observation.parent()
                        .ok_or_else(|| io::Error::other("original Root listener parent missing"))?.join(SOCKET),
                };
                let bootstrap = crate::authority_host_bootstrap_seal::seal_bytes(
                    &serde_json::to_vec(&bundle).map_err(io::Error::other)?,
                )?;
                if learning.backend.restore(&initial.request).map_err(io::Error::other)? != before {
                    return Err(io::Error::other("original learning changed during publication capture"));
                }
                Ok((bundle, bootstrap))
            },
        )?;
        let (sender, receiver) = mpsc::sync_channel(1);
        let phase = Arc::new(AtomicU8::new(PREPARED));
        self.publication = Some(PublicationRuntime {
            receiver: Mutex::new(receiver), phase: Arc::clone(&phase), socket: bundle.socket,
        });
        Ok((RootGenerationPublicationEnrollmentCapabilityV1 {
            sender, phase, root_pid: bundle.root.pid, boot_id: bundle.root.boot_id,
            process_start_ticks: bundle.root.process_start_ticks,
            lifetime: Duration::from_millis(self.config.lifetime_ms),
        }, crate::RootGenerationPublicationOfferV1 { bootstrap }))
    }
}

fn root_start() -> io::Result<u64> {
    std::fs::read_to_string("/proc/self/stat")?.rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok()).filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("actual Root incarnation missing"))
}
