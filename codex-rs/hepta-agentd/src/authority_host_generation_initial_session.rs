//! One-shot initial enrollment in the same retained Root session. The capability
//! never reaches the daemon; only trusted Root can supply original capabilities.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

use super::*;
use crate::authority_host_service::generation_initial::PURPOSE;
use crate::authority_host_service::generation_initial::InitialBootstrap;
use crate::authority_host_service::generation_initial::SOCKET;

#[path = "authority_host_generation_initial_runtime.rs"]
mod runtime;
pub(super) use runtime::BoundInitial;
pub(super) use runtime::serve_optional;

const PREPARED: u8 = 0;
const ACTIVE: u8 = 1;
const CONSUMED: u8 = 2;
const CLOSED: u8 = 3;

struct Submission {
    inputs: crate::RootGenerationInitialEnrollmentV1,
    acknowledgement: mpsc::SyncSender<Result<String, String>>,
}

pub(super) struct InitialRuntime {
    receiver: Mutex<mpsc::Receiver<Submission>>,
    phase: Arc<AtomicU8>,
    socket: PathBuf,
    deployment: crate::HostGenerationInitialDeploymentV1,
}

/// A consumed original Root registration acknowledgement. The digest is a
/// data pin; it neither constructs a daemon CURRENT owner nor grants execution.
pub struct RootGenerationInitialRegistrationV1 {
    binding: String,
}

impl RootGenerationInitialRegistrationV1 {
    pub fn binding(&self) -> &str {
        &self.binding
    }
}

/// Held only by the original trusted Root host. It is not Clone/Serialize and
/// cannot accept a daemon wire payload. Use it after the original consumer
/// has opened its real nonce owners, then connect the sealed initial route.
pub struct RootGenerationInitialEnrollmentCapabilityV1 {
    sender: mpsc::SyncSender<Submission>,
    phase: Arc<AtomicU8>,
    root_pid: u32,
    boot_id: String,
    process_start_ticks: u64,
    lifetime: Duration,
}

impl RootGenerationInitialEnrollmentCapabilityV1 {
    /// Register actual original owners in the concurrently serving same Root.
    /// Timeout consumes the capability; it never retries, re-signs or changes
    /// Reserve into Recover. Existing persisted state requires explicit recovery.
    pub fn register(
        self,
        inputs: crate::RootGenerationInitialEnrollmentV1,
    ) -> io::Result<RootGenerationInitialRegistrationV1> {
        crate::authority_host_service::generation_initial::original_root()?;
        if std::process::id() != self.root_pid
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim() != self.boot_id
            || root_start()? != self.process_start_ticks
            || self
                .phase
                .compare_exchange(ACTIVE, CONSUMED, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
        {
            return Err(io::Error::other(
                "original live one-shot Root enrollment required",
            ));
        }
        let (acknowledgement, receiver) = mpsc::sync_channel(1);
        self.sender
            .try_send(Submission {
                inputs,
                acknowledgement,
            })
            .map_err(|_| io::Error::other("original initial enrollment channel unavailable"))?;
        let binding = receiver
            .recv_timeout(self.lifetime)
            .map_err(|_| io::Error::other("initial enrollment acknowledgement uncertain"))?
            .map_err(io::Error::other)?;
        if self.phase.load(Ordering::Acquire) != CONSUMED {
            return Err(io::Error::other(
                "original initial session ended during enrollment",
            ));
        }
        Ok(RootGenerationInitialRegistrationV1 { binding })
    }
}

impl PreparedHostAuthoritySession {
    /// Enable one independent initial-purpose route before A exists. The Root
    /// host retains the enrollment capability and supplies actual capabilities
    /// after the original consumer has opened its two nonce owners.
    pub fn enable_generation_initial(
        &mut self,
        deployment: crate::HostGenerationInitialDeploymentV1,
    ) -> io::Result<(
        RootGenerationInitialEnrollmentCapabilityV1,
        crate::RootGenerationInitialOfferV1,
    )> {
        crate::authority_host_service::generation_initial::original_root()?;
        if self.initial_publication.is_some() {
            return Err(io::Error::other("original initial route already enabled"));
        }
        let mut captured = None;
        self.service.with_initial_publication_context(
            &self.config, &self.registration, &self.owner_pidfd, |proof| {
                codex_hepta_types::StableId::new(&deployment.operation).map_err(io::Error::other)?;
                deployment.target.digest().map_err(io::Error::other)?;
                if deployment.target.scope().agent_id
                    != self.registration.registered_identity.identity()?.agent_id.as_str()
                {
                    return Err(io::Error::other("initial deployment differs from original agent"));
                }
                let bundle = InitialBootstrap {
                    purpose: PURPOSE.into(),
                    deployment,
                    root: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                        uid: 0, pid: std::process::id(),
                        boot_id: self.registration.boot_id.clone(),
                        process_start_ticks: root_start()?,
                    },
                    consumer: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                        uid: self.config.peer_uid, pid: self.registration.peer_pid,
                        boot_id: self.registration.boot_id.clone(),
                        process_start_ticks: self.registration.process_start_ticks,
                    },
                    identity: self.registration.registered_identity.clone(),
                    writer: proof,
                    socket: self.config.sockets.observation.parent()
                        .ok_or_else(|| io::Error::other("original Root listener parent missing"))?
                        .join(SOCKET),
                };
                let bootstrap = crate::authority_host_bootstrap_seal::seal_bytes(
                    &serde_json::to_vec(&bundle).map_err(io::Error::other)?,
                )?;
                captured = Some((bundle, bootstrap));
                Ok(())
            },
        )?;
        let (bundle, bootstrap) = captured
            .ok_or_else(|| io::Error::other("original initial route capture missing"))?;
        let (sender, receiver) = mpsc::sync_channel(1);
        let phase = Arc::new(AtomicU8::new(PREPARED));
        self.initial_publication = Some(InitialRuntime {
            receiver: Mutex::new(receiver),
            phase: Arc::clone(&phase),
            socket: bundle.socket,
            deployment: bundle.deployment,
        });
        Ok((
            RootGenerationInitialEnrollmentCapabilityV1 {
                sender, phase, root_pid: bundle.root.pid, boot_id: bundle.root.boot_id,
                process_start_ticks: bundle.root.process_start_ticks,
                lifetime: Duration::from_millis(self.config.lifetime_ms),
            },
            crate::RootGenerationInitialOfferV1 { bootstrap },
        ))
    }
}

impl InitialRuntime {
    pub(super) fn path(&self) -> &Path { &self.socket }
}

fn root_start() -> io::Result<u64> {
    std::fs::read_to_string("/proc/self/stat")?
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("actual Root incarnation missing"))
}
