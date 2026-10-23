//! Actual root-authenticated observation and original writer authority. The
//! retained session owns its single stream; dropping it closes authority.
use crate::AgentdRootAuthorityError;
use crate::AgentdRootAuthorityPeer;
use crate::AgentdRootWriterTrust;
use crate::HOST_AUTHORITY_OBSERVATION_V2;
use crate::HOST_WRITER_AUTHORIZATION_V1;
use crate::HostAuthorityObservationRequestV2;
use crate::HostAuthorityObservationResponseV2;
use crate::HostWriterAuthorizationReadRequestV1;
use crate::HostWriterAuthorizationReadResponseV1;
use crate::root_observation_cache::MAX_AGE_NS;
use crate::root_observation_cache::RootObservationCache;
use crate::root_observation_cache::boottime_ns;
use crate::root_observation_stream::RootObservationStream;
use crate::root_observation_stream::check_lifetime;
use crate::root_writer_proof::VerifiedRootWriterProof;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityVerifier;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::io::unix::AsyncFd;

struct LiveRoot {
    proof: VerifiedRootWriterProof,
    cache: RootObservationCache,
    root: Arc<AsyncFd<OwnedFd>>,
    end_boottime_ns: u64,
    active: AtomicBool,
    consumers: Mutex<Vec<FinalUseAuthority>>,
    serial: tokio::sync::Mutex<()>,
}
impl LiveRoot {
    fn current(
        &self,
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), AgentdRootAuthorityError> {
        if check_lifetime(self.root.get_ref()).is_err()
            || boottime_ns().map_or(true, |now| now >= self.end_boottime_ns)
        {
            self.cache.fence();
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let (observation, now) = self.cache.current()?;
        if self.proof.matches_observation(&observation).is_err()
            || now
                >= self
                    .proof
                    .authority()
                    .lease_expires_at_unix_seconds
                    .saturating_mul(1000)
            || check_lifetime(self.root.get_ref()).is_err()
        {
            self.cache.fence();
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        Ok((observation, now))
    }
}
impl AuthorityClock for LiveRoot {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.current()
            .map(|(_, now)| now)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
}
impl ProductionAuthorityVerifier for LiveRoot {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        if !self.active.load(Ordering::Acquire)
            || authority != self.proof.authority()
            || &authority.agent_id != expected_agent
        {
            return Err(
                "root writer registration is inactive or differs from its verified proof".into(),
            );
        }
        self.current()
            .map(|_| ())
            .map_err(|_| "root writer observation is unavailable or fenced".into())
    }
}

/// Keep this handle alive for the whole original owner lifetime. `connect`
/// starts only a read feed. The writer verifier remains disabled until the
/// actual independently opened FinalUse consumers are installed and synced.
pub struct AgentdRootAuthoritySession {
    live: Arc<LiveRoot>,
    worker: tokio::task::JoinHandle<()>,
}
impl AgentdRootAuthoritySession {
    pub async fn connect(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
        trust: AgentdRootWriterTrust,
    ) -> Result<Self, AgentdRootAuthorityError> {
        let created = boottime_ns()?;
        let boot_id = peer.boot_id.clone();
        let stream =
            RootObservationStream::from_stream(stream, peer, root_pidfd, timeout, lifetime)?;
        Self::connect_owned_stream(stream, boot_id, created, lifetime, trust).await
    }
    async fn connect_owned_stream(
        stream: RootObservationStream,
        boot_id: String,
        created: u64,
        lifetime: Duration,
        trust: AgentdRootWriterTrust,
    ) -> Result<Self, AgentdRootAuthorityError> {
        let response: HostWriterAuthorizationReadResponseV1 = stream
            .read(&HostWriterAuthorizationReadRequestV1 {
                schema_version: 1,
                operation: HOST_WRITER_AUTHORIZATION_V1.into(),
            })
            .await?;
        if response.schema_version != 1 || response.operation != HOST_WRITER_AUTHORIZATION_V1 {
            return Err(AgentdRootAuthorityError::Refused);
        }
        let proof = VerifiedRootWriterProof::verify(response.proof, &trust)?;
        let live = Arc::new(LiveRoot {
            proof,
            cache: RootObservationCache::new(boot_id),
            root: stream.root_lifetime(),
            end_boottime_ns: created
                .checked_add(
                    u64::try_from(lifetime.as_nanos())
                        .map_err(|_| AgentdRootAuthorityError::Refused)?,
                )
                .ok_or(AgentdRootAuthorityError::Refused)?,
            active: AtomicBool::new(false),
            consumers: Mutex::new(Vec::new()),
            serial: tokio::sync::Mutex::new(()),
        });
        refresh(&live, &stream).await?;
        let background = Arc::clone(&live);
        let worker = tokio::spawn(async move {
            let _fence = FenceOnDrop(Arc::clone(&background));
            loop {
                tokio::time::sleep(Duration::from_millis(100)).await;
                if refresh(&background, &stream).await.is_err() {
                    return;
                }
            }
        });
        Ok(Self { live, worker })
    }
    pub fn clock(&self) -> Arc<dyn AuthorityClock> {
        self.live.clone()
    }
    pub fn authority(&self) -> ProductionAuthorityLease {
        self.live.proof.authority().clone()
    }
    pub fn verifier(&self) -> Arc<dyn ProductionAuthorityVerifier> {
        self.live.clone()
    }
    pub fn revocations(&self) -> Result<FinalUseRevocations, AgentdRootAuthorityError> {
        self.live
            .current()
            .map(|(value, _)| value.revocations.clone())
    }
    /// Install the exact original Device/Notes owners, not replacement state
    /// or a second nonce ledger. Their separate original frontier stores remain
    /// the only durable owners. Calling twice is refused; failure stays fenced.
    pub async fn activate_final_use_owners(
        &self,
        consumers: Vec<FinalUseAuthority>,
    ) -> Result<(), AgentdRootAuthorityError> {
        if consumers.is_empty() || consumers.len() > 8 || self.live.active.load(Ordering::Acquire) {
            return Err(AgentdRootAuthorityError::Refused);
        }
        let started = boottime_ns()?;
        let _serial = tokio::time::timeout(Duration::from_millis(500), self.live.serial.lock())
            .await
            .map_err(|_| {
                self.live.cache.fence();
                AgentdRootAuthorityError::Unavailable
            })?;
        if self.live.active.load(Ordering::Acquire) {
            return Err(AgentdRootAuthorityError::Refused);
        }
        let mut attempt = ActivationAttempt {
            live: &self.live,
            complete: false,
        };
        let (observation, _) = self.live.current()?;
        self.live.cache.begin_update();
        synchronize_consumers(consumers.clone(), observation.revocations.clone(), started).await?;
        *self
            .live
            .consumers
            .lock()
            .map_err(|_| AgentdRootAuthorityError::Unavailable)? = consumers;
        self.live.cache.end_update();
        self.live.current()?;
        self.live.active.store(true, Ordering::Release);
        attempt.complete = true;
        Ok(())
    }
}
impl Drop for AgentdRootAuthoritySession {
    fn drop(&mut self) {
        self.live.cache.fence();
        self.worker.abort();
    }
}
struct FenceOnDrop(Arc<LiveRoot>);
impl Drop for FenceOnDrop {
    fn drop(&mut self) {
        self.0.cache.fence();
    }
}
struct ActivationAttempt<'a> {
    live: &'a LiveRoot,
    complete: bool,
}
impl Drop for ActivationAttempt<'_> {
    fn drop(&mut self) {
        if !self.complete {
            self.live.cache.fence();
        }
    }
}

async fn refresh(
    live: &Arc<LiveRoot>,
    stream: &RootObservationStream,
) -> Result<(), AgentdRootAuthorityError> {
    let _serial = live.serial.lock().await;
    let started = boottime_ns()?;
    let observation: HostAuthorityObservationResponseV2 = stream
        .read(&HostAuthorityObservationRequestV2 {
            schema_version: 2,
            operation: HOST_AUTHORITY_OBSERVATION_V2.into(),
        })
        .await?;
    let ended = boottime_ns()?;
    live.proof.matches_observation(&observation)?;
    let head = observation.revocations.clone();
    let changed = !live.cache.revocations_match(&head);
    if changed {
        live.cache.begin_update();
    }
    // Validate and stage the complete response while the public cache is
    // paused, then advance each original consumer before releasing the barrier.
    live.cache.accept(observation, started, ended)?;
    if changed {
        let consumers = live
            .consumers
            .lock()
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?
            .clone();
        synchronize_consumers(consumers, head, started).await?;
        live.cache.end_update();
    }
    live.current()?;
    Ok(())
}
async fn synchronize_consumers(
    consumers: Vec<FinalUseAuthority>,
    head: FinalUseRevocations,
    started: u64,
) -> Result<(), AgentdRootAuthorityError> {
    if consumers.is_empty() {
        return Ok(());
    }
    let elapsed = boottime_ns()?
        .checked_sub(started)
        .ok_or(AgentdRootAuthorityError::Unavailable)?;
    let remaining = MAX_AGE_NS
        .checked_sub(elapsed)
        .filter(|remaining| *remaining > 0)
        .ok_or(AgentdRootAuthorityError::Unavailable)?;
    let result = tokio::time::timeout(
        Duration::from_nanos(remaining),
        tokio::task::spawn_blocking(move || {
            for owner in consumers {
                if owner
                    .revocation_head()
                    .map_err(|_| AgentdRootAuthorityError::Unavailable)?
                    != head
                {
                    owner
                        .update_revocations(head.clone())
                        .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
                }
                if owner
                    .revocation_head()
                    .map_err(|_| AgentdRootAuthorityError::Unavailable)?
                    != head
                {
                    return Err(AgentdRootAuthorityError::Unavailable);
                }
            }
            Ok(())
        }),
    )
    .await
    .map_err(|_| AgentdRootAuthorityError::Unavailable)?
    .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
    result?;
    if boottime_ns()?
        .checked_sub(started)
        .is_none_or(|age| age > MAX_AGE_NS)
    {
        return Err(AgentdRootAuthorityError::Unavailable);
    }
    Ok(())
}
#[cfg(test)]
#[path = "root_authority_session_tests.rs"]
mod tests;
