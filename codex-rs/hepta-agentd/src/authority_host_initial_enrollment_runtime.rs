//! The same original enrollment and baseline checks serve both explicit
//! Root-host registration and the fixed-input ordinary readiness route.

use super::*;
use crate::RootGenerationInitialEnrollmentV1;
use crate::authority_host_service::generation_initial::RegisteredGenerationInitial;
use crate::authority_host_service::generation_initial::run_start_retention::RegisteredInitialRunStartRetentionV1;

pub(super) struct InitialEnrollmentContext<'a> {
    pub(super) initial: &'a BoundInitial,
    pub(super) service: &'a HostAuthorityService,
    pub(super) config: &'a HostAuthorityServiceConfig,
    pub(super) registration: &'a HostAuthorityRegistration,
    pub(super) owner: &'a OwnedFd,
    pub(super) stopping: &'a AtomicBool,
    pub(super) end: Instant,
}

impl InitialEnrollmentContext<'_> {
    pub(super) fn require_original_context(&self, end: Instant) -> io::Result<()> {
        if end > self.end || self.stopping.load(Ordering::Acquire) {
            return Err(io::Error::other("original Initial serving context closed"));
        }
        owner_alive(self.owner, end)?;
        self.service.with_initial_publication_context(
            self.config,
            self.registration,
            self.owner,
            |proof| {
                if proof != self.initial.runtime.writer {
                    return Err(io::Error::other("original Initial writer differs"));
                }
                owner_alive(self.owner, end)
            },
        )?;
        owner_alive(self.owner, end)
    }

    pub(super) fn enroll_original(
        &self,
        inputs: RootGenerationInitialEnrollmentV1,
        end: Instant,
    ) -> io::Result<(
        RegisteredGenerationInitial,
        Option<RegisteredInitialRunStartRetentionV1>,
    )> {
        self.require_original_context(end)?;
        let enrolled = self.service.enroll_generation_initial(
            self.config,
            self.registration,
            self.owner,
            &self.initial.runtime.deployment,
            inputs,
        );
        let enrollment_post = self.require_original_context(end);
        let slot: RegisteredGenerationInitial = enrolled?;
        if let Err(error) = enrollment_post {
            RegisteredGenerationInitial::refuse_original_enrollment(&slot)?;
            return Err(error);
        }
        let result = (|| {
            let run_start = self
                .initial
                .runtime
                .run_start
                .as_ref()
                .map(|files| {
                    self.service.register_initial_run_start_retention(
                        &slot,
                        self.config,
                        self.registration,
                        self.owner,
                        Arc::clone(files),
                        end,
                    )
                })
                .transpose()?;
            if let Some(source) = self.initial.runtime.source_capture.as_ref() {
                let context = source_capture::SourceCaptureContext {
                    service: self.service,
                    config: self.config,
                    registration: self.registration,
                    owner: self.owner,
                    slot: &slot,
                    stopping: self.stopping,
                    end,
                };
                source.register_original_source_cell(context)?;
                source.register_original_source_ledger(context)?;
            }
            RegisteredGenerationInitial::require_original_enrollment_profile(&slot)?;
            Ok(run_start)
        })();
        // A failed baseline still receives the original writer/pidfd/end
        // postcheck, and any retained Initial profile is fenced on failure.
        let post = self.require_original_context(end);
        match result.and_then(|run_start| post.map(|()| run_start)) {
            Ok(run_start) => Ok((slot, run_start)),
            Err(error) => {
                RegisteredGenerationInitial::refuse_original_enrollment(&slot)?;
                Err(error)
            }
        }
    }

    pub(super) fn accept_original(
        &self,
        active: &Mutex<Option<UnixStream>>,
    ) -> io::Result<Option<UnixStream>> {
        let stream = loop {
            if self.stopping.load(Ordering::Acquire) {
                return Ok(None);
            }
            owner_alive(self.owner, self.end)?;
            match self.initial.listener.accept() {
                Ok((stream, _)) => break stream,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(5));
                }
                Err(error) => return Err(error),
            }
        };
        verify_pinned_process(
            self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            self.owner,
            self.end,
        )?;
        let mut held = active
            .lock()
            .map_err(|_| io::Error::other("initial lane poisoned"))?;
        if self.stopping.load(Ordering::Acquire) {
            return Ok(None);
        }
        *held = Some(stream.try_clone()?);
        Ok(Some(stream))
    }

    pub(super) fn peer_policy(&self) -> io::Result<HostAuthorityPeerPolicy> {
        Ok(HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: self.config.peer_uid,
                pid: self.registration.peer_pid,
            },
            timeout: Duration::from_millis(self.config.timeout_ms),
            lifetime: self
                .end
                .checked_duration_since(Instant::now())
                .ok_or_else(|| io::Error::other("initial Root session expired"))?,
            request_bound: 16 * 1024,
            response_bound: 16 * 1024,
        })
    }
}
