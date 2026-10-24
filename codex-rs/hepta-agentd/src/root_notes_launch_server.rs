//! Root half of one launch, retaining the same original authority object.
use super::*;
use crate::RootNotesLaunchChannel;
use crate::RootNotesLaunchFrame;
use crate::root_notes_launch_wire::ROOT_NOTES_PREPARATION_NS;
use crate::root_notes_launch_wire::ROOT_NOTES_TOTAL_PREPARATION_NS;
use crate::root_notes_launch_wire::invalid;
use codex_hepta_contracts::HostAuthorityOwnerLifetime;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::NotesTargetIdentity;
use std::fs::File;
use std::io::Read;
use std::sync::Mutex;
use std::time::Duration;

/// Root owns this exact pending service. The caller has already installed any
/// recovered image, spawned the actual Host, and retained its real Child/pidfd.
/// This object creates no grant, Current, writer, Session or replacement issuer.
pub struct RootNotesLaunchServer {
    service: HostAuthorityService,
    channel: RootNotesLaunchChannel,
    root_pidfd: OwnedFd,
    root: CognitiveCheckpointPeerLifetime,
    nonce: String,
    phase_end: u64,
    preparation_end: u64,
}

/// Exactly [Session FD0 offer, Session FD4 planned startup], made by Host.
pub struct RootNotesSessionChannels([OwnedFd; 2]);
impl RootNotesSessionChannels {
    pub fn into_descriptors(self) -> [OwnedFd; 2] {
        self.0
    }
}

/// Root must now spawn its fixed UID1000 Session with the transferred channels
/// and its separately retained Host pidfd at FD3. No claimed PID is opened here.
pub struct RootNotesAwaitingSession(RootNotesLaunchServer);

/// The actual Session supplied the target through the original Host allocator.
pub struct RootNotesReservedTarget {
    launch: RootNotesLaunchServer,
    session: HostAuthorityOwnerLifetime,
    target: NotesTargetIdentity,
}

/// Start the original five lane workers using `service()`, then wait for the
/// same Host's zero-input Ready. Dropping this value fences the pending owner;
/// cancellation cannot leave already cloned workers issuing new signatures.
pub struct RootNotesAuthorityStartup {
    service: Arc<HostAuthorityService>,
    channel: RootNotesLaunchChannel,
    session: HostAuthorityOwnerLifetime,
    nonce: String,
    preparation_end: u64,
    cancellation: RootNotesStartupCancellation,
}

/// Retain this before moving startup into a blocking worker. Cancelling the
/// worker's JoinHandle alone does not stop an already running synchronous call.
/// `cancel` closes its actual channel and all original authority lane aliases.
#[derive(Clone)]
pub struct RootNotesStartupCancellation(Arc<StartupCancellation>);

struct StartupCancellation {
    service: Arc<HostAuthorityService>,
    state: Mutex<StartupCancellationState>,
}

enum StartupCancellationState {
    Armed(crate::RootNotesLaunchAbort),
    Completed,
    Cancelled,
}

impl RootNotesStartupCancellation {
    pub fn cancel(&self) {
        let mut state = self
            .0
            .state
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if matches!(*state, StartupCancellationState::Armed(_)) {
            drop(std::mem::replace(
                &mut *state,
                StartupCancellationState::Cancelled,
            ));
            self.0.service.fail_material_startup();
        }
    }

    fn complete(&self) -> io::Result<()> {
        let mut state = self
            .0
            .state
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        match std::mem::replace(&mut *state, StartupCancellationState::Completed) {
            StartupCancellationState::Armed(abort) => {
                abort.disarm();
                Ok(())
            }
            StartupCancellationState::Cancelled => {
                *state = StartupCancellationState::Cancelled;
                Err(io::Error::other("Root Notes startup was cancelled"))
            }
            StartupCancellationState::Completed => Err(invalid()),
        }
    }
}

impl RootNotesLaunchServer {
    /// The stream must be accepted by the trusted Root launcher. The original
    /// service independently pins the exact actual Root and dedicated Host.
    /// `preparation_end` was fixed before long recovery, and is never renewed.
    pub fn from_registered_host_stream(
        service: HostAuthorityService,
        stream: UnixStream,
        preheld_host_pidfd: OwnedFd,
        preheld_root_pidfd: OwnedFd,
        preparation_end_boottime_ns: u64,
    ) -> io::Result<Self> {
        if !service
            .material_startup
            .as_ref()
            .is_some_and(|state| state.is_pending())
            || service
                .checkpoint
                .as_ref()
                .and_then(|c| c.recovered.as_ref())
                .is_some_and(|recovered| {
                    !recovered
                        .installed
                        .load(std::sync::atomic::Ordering::Acquire)
                })
        {
            return Err(invalid());
        }
        let bundle = service.capture_public_bootstrap()?;
        if bundle.consumer.uid != 60001
            || bundle.root.uid != 0
            || bundle.root.pid != std::process::id()
        {
            return Err(invalid());
        }
        let lifetime = remaining(preparation_end_boottime_ns)?;
        if lifetime.as_nanos() > u128::from(ROOT_NOTES_TOTAL_PREPARATION_NS) {
            return Err(invalid());
        }
        // Keep the caller's already fixed end, and only shorten it. Anchor
        // BOOTTIME before the protected clock's possible I/O, so that I/O and
        // millisecond rounding cannot accidentally renew the real lease.
        let preparation_end_boottime_ns = service.issuer.with_live_lease(|lease| {
            use codex_hepta_contracts::AuthorityClock;
            let before = now()?;
            let observed = service.clock.now_unix_ms().map_err(io::Error::other)?;
            let writer = service.writer.as_ref().ok_or_else(invalid)?;
            let expiry = lease
                .expires_at_unix_ms
                .min(writer.registration.authority_lease.expires_at_unix_ms);
            let remaining_ms = expiry
                .checked_sub(observed)
                .and_then(|left| left.checked_sub(1))
                .filter(|left| *left > 0)
                .ok_or_else(invalid)?;
            let lease_end = before
                .checked_add(remaining_ms.checked_mul(1_000_000).ok_or_else(invalid)?)
                .ok_or_else(invalid)?;
            Ok(preparation_end_boottime_ns.min(lease_end))
        })?;
        let lifetime = remaining(preparation_end_boottime_ns)?;
        HostAuthorityOwnerLifetime::from_pidfd(
            preheld_root_pidfd.try_clone()?,
            bundle.root.pid,
            lifetime,
        )
        .map_err(io::Error::other)?
        .check_alive()
        .map_err(io::Error::other)?;
        let channel = RootNotesLaunchChannel::from_peer_stream(
            stream,
            bundle.consumer,
            preheld_host_pidfd,
            preparation_end_boottime_ns,
        )?;
        let mut random = [0u8; 16];
        File::open("/dev/urandom")?.read_exact(&mut random)?;
        let nonce = random.iter().map(|byte| format!("{byte:02x}")).collect();
        Ok(Self {
            service,
            channel,
            root_pidfd: preheld_root_pidfd,
            root: bundle.root,
            nonce,
            phase_end: 0,
            preparation_end: preparation_end_boottime_ns,
        })
    }

    /// Start Phase A once, after slow physical installation. Its original five
    /// seconds and Parent's already fixed total end are distinct absolute values.
    pub fn prepare_session(
        mut self,
    ) -> io::Result<(RootNotesAwaitingSession, RootNotesSessionChannels)> {
        self.service.capture_public_bootstrap()?;
        self.phase_end = now()?
            .checked_add(ROOT_NOTES_PREPARATION_NS)
            .ok_or_else(invalid)?;
        if self.phase_end >= self.preparation_end {
            return Err(invalid());
        }
        self.channel.send(
            &RootNotesLaunchFrame::PrepareSessionV1 {
                schema_version: 1,
                launch_nonce: self.nonce.clone(),
                end_boottime_ns: self.phase_end,
                preparation_end_boottime_ns: self.preparation_end,
            },
            &[],
            self.phase_end,
        )?;
        let (frame, descriptors) = self.channel.read(self.phase_end)?;
        require_nonce(&frame, &self.nonce)?;
        if !matches!(frame, RootNotesLaunchFrame::SessionChannelsV1 { .. }) {
            return Err(invalid());
        }
        for descriptor in &descriptors {
            crate::root_notes_launch_io::require_connected_unix_datagram(descriptor)?;
        }
        let channels: [OwnedFd; 2] = descriptors.try_into().map_err(|_| invalid())?;
        self.channel.check(self.phase_end)?;
        Ok((
            RootNotesAwaitingSession(self),
            RootNotesSessionChannels(channels),
        ))
    }
}

impl RootNotesAwaitingSession {
    /// Supply only the original actually spawned Session and its pre-held
    /// pidfd. Root sends no private DB, issuer, checkpoint or Root directory FD.
    pub fn session_spawned(
        mut self,
        session: CognitiveCheckpointPeerLifetime,
        preheld_session_pidfd: OwnedFd,
    ) -> io::Result<RootNotesReservedTarget> {
        let launch = &mut self.0;
        if session.uid != 1000
            || session.boot_id != launch.root.boot_id
            || session.pid == launch.root.pid
            || session.pid == launch.channel.peer().pid
        {
            return Err(invalid());
        }
        crate::root_notes_launch_channel::validate_process(&session)?;
        let owner = HostAuthorityOwnerLifetime::from_pidfd(
            preheld_session_pidfd.try_clone()?,
            session.pid,
            remaining(launch.preparation_end)?,
        )
        .map_err(io::Error::other)?;
        owner.check_alive().map_err(io::Error::other)?;
        launch.channel.send(
            &RootNotesLaunchFrame::SessionSpawnedV1 {
                schema_version: 1,
                launch_nonce: launch.nonce.clone(),
                session,
            },
            &[preheld_session_pidfd],
            launch.phase_end,
        )?;
        let (frame, descriptors) = launch.channel.read(launch.phase_end)?;
        require_nonce(&frame, &launch.nonce)?;
        let RootNotesLaunchFrame::TargetReservedV1 { target, .. } = frame else {
            return Err(invalid());
        };
        if !descriptors.is_empty() {
            return Err(invalid());
        }
        owner.check_alive().map_err(io::Error::other)?;
        launch.channel.check(launch.phase_end)?;
        Ok(RootNotesReservedTarget {
            launch: self.0,
            session: owner,
            target,
        })
    }
}

impl RootNotesReservedTarget {
    pub fn target(&self) -> &NotesTargetIdentity {
        &self.target
    }

    /// First real target: add no placeholder policy at initial installation.
    pub fn install_first_notes(
        self,
        registry: Arc<AuthorityLeaseRegistry>,
        lifetime_ms: u64,
    ) -> io::Result<RootNotesAuthorityStartup> {
        let writer = &self
            .launch
            .service
            .writer
            .as_ref()
            .ok_or_else(invalid)?
            .registration;
        self.launch.service.issuer.install_registered_notes_policy(
            writer,
            &self.target,
            lifetime_ms,
        )?;
        self.register_admission(registry, lifetime_ms)
    }

    /// Recovery has an independently retained previous actual target. This is
    /// the existing full issuer-state CAS, never a clear-and-recreate policy.
    pub fn replace_notes(
        self,
        registry: Arc<AuthorityLeaseRegistry>,
        previous_target: &NotesTargetIdentity,
        previous_lifetime_ms: u64,
        lifetime_ms: u64,
    ) -> io::Result<RootNotesAuthorityStartup> {
        let writer = &self
            .launch
            .service
            .writer
            .as_ref()
            .ok_or_else(invalid)?
            .registration;
        self.launch.service.issuer.replace_registered_notes_policy(
            writer,
            previous_target,
            previous_lifetime_ms,
            &self.target,
            lifetime_ms,
        )?;
        self.register_admission(registry, lifetime_ms)
    }

    fn register_admission(
        self,
        registry: Arc<AuthorityLeaseRegistry>,
        lifetime_ms: u64,
    ) -> io::Result<RootNotesAuthorityStartup> {
        let Self {
            launch,
            session,
            target,
        } = self;
        let RootNotesLaunchServer {
            service,
            mut channel,
            root_pidfd,
            root,
            nonce,
            phase_end,
            preparation_end,
        } = launch;
        let registration = service
            .writer
            .as_ref()
            .ok_or_else(invalid)?
            .registration
            .clone();
        let notes = crate::RootNotesGrantAdmission::from_registered_notes(
            &service.issuer,
            registry,
            registration,
            &target,
            lifetime_ms,
        )?;
        let service = Arc::new(service.with_registered_notes(notes)?);
        let bundle = service.capture_public_bootstrap()?;
        if bundle.root != root || bundle.consumer != *channel.peer() {
            return Err(invalid());
        }
        let sealed = crate::seal_host_authority_bootstrap(&bundle)?;
        session.check_alive().map_err(io::Error::other)?;
        channel.check(phase_end)?;
        channel.send(
            &RootNotesLaunchFrame::OriginalBootstrapV1 {
                schema_version: 1,
                launch_nonce: nonce.clone(),
            },
            &[sealed.into(), root_pidfd],
            phase_end,
        )?;
        channel.check(phase_end)?;
        let cancellation = RootNotesStartupCancellation(Arc::new(StartupCancellation {
            service: Arc::clone(&service),
            state: Mutex::new(StartupCancellationState::Armed(channel.abort_handle()?)),
        }));
        Ok(RootNotesAuthorityStartup {
            service,
            channel,
            session,
            nonce,
            preparation_end,
            cancellation,
        })
    }
}

impl RootNotesAuthorityStartup {
    /// Every runtime lane must serve this same allocation, including its
    /// permanent Unknown state, original clock, canonical issuer and peer pin.
    pub fn service(&self) -> Arc<HostAuthorityService> {
        Arc::clone(&self.service)
    }

    pub fn cancellation(&self) -> RootNotesStartupCancellation {
        self.cancellation.clone()
    }

    /// Original recovered-owner-ready, zero material inputs, exactly once.
    /// Any error or cancellation permanently closes this launch's service.
    pub fn wait_and_confirm(mut self) -> io::Result<Arc<HostAuthorityService>> {
        let (frame, descriptors) = self.channel.read(self.preparation_end)?;
        require_nonce(&frame, &self.nonce)?;
        if !descriptors.is_empty()
            || !matches!(frame, RootNotesLaunchFrame::RecoveredOwnerReadyV1 { .. })
        {
            return Err(invalid());
        }
        self.session.check_alive().map_err(io::Error::other)?;
        self.channel.check(self.preparation_end)?;
        self.service.confirm_recovered_owner_ready()?;
        self.session.check_alive().map_err(io::Error::other)?;
        self.channel.check(self.preparation_end)?;
        self.channel.send(
            &RootNotesLaunchFrame::RecoveredOwnerRegisteredV1 {
                schema_version: 1,
                launch_nonce: self.nonce.clone(),
            },
            &[],
            self.preparation_end,
        )?;
        self.session.check_alive().map_err(io::Error::other)?;
        self.channel.check(self.preparation_end)?;
        self.cancellation.complete()?;
        Ok(Arc::clone(&self.service))
    }
}

impl Drop for RootNotesAuthorityStartup {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

fn now() -> io::Result<u64> {
    codex_hepta_authority_client::boottime_ns().map_err(io::Error::other)
}
fn remaining(end: u64) -> io::Result<Duration> {
    end.checked_sub(now()?)
        .filter(|left| *left > 0)
        .map(Duration::from_nanos)
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "Root Notes launch deadline"))
}
fn require_nonce(frame: &RootNotesLaunchFrame, nonce: &str) -> io::Result<()> {
    if frame.launch_nonce() != nonce {
        return Err(invalid());
    }
    Ok(())
}
