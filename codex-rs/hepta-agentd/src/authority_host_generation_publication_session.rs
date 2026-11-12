//! One-shot late enrollment in the same retained Root session. The capability
//! never reaches the daemon; only trusted Root can supply original capabilities.

use std::os::fd::OwnedFd;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use super::*;
use crate::authority_host_service::generation_publication::PublicationBootstrap;
use crate::authority_host_service::generation_publication::PublicationVersion;

#[path = "authority_host_generation_publication_runtime.rs"]
mod runtime;
pub(super) use runtime::BoundPublication;
pub(super) use runtime::serve_optional;
pub(super) use runtime::serve_optional_until;

#[path = "authority_host_publication_deployment.rs"]
pub(super) mod deployment;
pub use deployment::RootGenerationPublicationDeploymentSessionV1;
pub use deployment::RootGenerationPublicationDeploymentV1;

#[path = "authority_host_original_publication_route.rs"]
mod original_route;
pub(super) use original_route::prepare_original_publication_route;

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
    version: PublicationVersion,
}

/// A consumed original Root registration acknowledgement. The digest is a
/// data pin; it neither constructs a daemon CURRENT owner nor grants execution.
pub struct RootGenerationPublicationRegistrationV1 {
    binding: String,
}

impl RootGenerationPublicationRegistrationV1 {
    pub fn binding(&self) -> &str {
        &self.binding
    }
}

/// Held only by the original trusted Root host. It is not Clone/Serialize and
/// cannot accept a daemon wire payload. Use it once after the real decision,
/// then let the daemon connect its already sealed purpose route.
pub struct RootGenerationPublicationEnrollmentCapabilityV1 {
    sender: mpsc::SyncSender<Submission>,
    phase: Arc<AtomicU8>,
    root_pid: u32,
    consumer_uid: u32,
    boot_id: String,
    process_start_ticks: u64,
    lifetime: Duration,
    original_end: Option<Instant>,
    version: PublicationVersion,
}

impl RootGenerationPublicationEnrollmentCapabilityV1 {
    fn operation_end(&self) -> io::Result<Instant> {
        let end = match self.original_end {
            Some(end) => end,
            None => Instant::now()
                .checked_add(self.lifetime)
                .ok_or_else(|| io::Error::other("original publication deadline overflow"))?,
        };
        if Instant::now() >= end {
            return Err(io::Error::other("original publication deadline elapsed"));
        }
        Ok(end)
    }

    /// Register actual original owners in the concurrently serving same Root.
    /// Timeout consumes the capability; it never retries, re-signs or changes
    /// Reserve into Recover. Existing persisted state requires explicit recovery.
    pub fn register(
        self,
        inputs: crate::RootGenerationPublicationEnrollmentV1,
    ) -> io::Result<RootGenerationPublicationRegistrationV1> {
        crate::authority_host_service::generation_publication::original_root()?;
        let end = self.operation_end()?;
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
            .map_err(|_| io::Error::other("original publication enrollment channel unavailable"))?;
        let remaining = end
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| io::Error::other("original publication end expired"))?;
        let binding = receiver
            .recv_timeout(remaining)
            .map_err(|_| io::Error::other("publication enrollment acknowledgement uncertain"))?
            .map_err(io::Error::other)?;
        if self.phase.load(Ordering::Acquire) != CONSUMED || Instant::now() >= end {
            return Err(io::Error::other(
                "original publication session ended during enrollment",
            ));
        }
        Ok(RootGenerationPublicationRegistrationV1 { binding })
    }
}

impl PreparedHostAuthoritySession {
    /// Capture a route from this original learning owner; the one-shot
    /// enrollment capability remains in the actual Root host.
    pub fn enable_generation_publication(
        &mut self,
    ) -> io::Result<(
        RootGenerationPublicationEnrollmentCapabilityV1,
        crate::RootGenerationPublicationOfferV1,
    )> {
        crate::authority_host_service::generation_publication::original_root()?;
        if self.publication.is_some() {
            return Err(io::Error::other(
                "original publication route already enabled",
            ));
        }
        let learning = self
            .learning
            .as_ref()
            .ok_or_else(|| io::Error::other("original scoped learning owner required"))?;
        let (runtime, capability, offer) = prepare_original_publication_route(
            &self.service,
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            learning,
            None,
            PublicationVersion::LegacyV1,
        )?;
        self.publication = Some(runtime);
        Ok((capability, offer))
    }
}

fn root_start() -> io::Result<u64> {
    std::fs::read_to_string("/proc/self/stat")?
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("actual Root incarnation missing"))
}
