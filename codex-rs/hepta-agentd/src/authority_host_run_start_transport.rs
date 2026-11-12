//! One nonterminal retain request. The peer supplies only its append tuple;
//! the same Root runtime owns every file, registration and durability decision.

use super::*;
use crate::authority_host_service::generation_initial::Command;
use crate::authority_host_service::generation_initial::Request;

pub(crate) struct OriginalRunStartRetentionExchange<'a> {
    service: &'a HostAuthorityService,
    slot: &'a RegisteredGenerationInitial,
    config: &'a HostAuthorityServiceConfig,
    registration: &'a HostAuthorityRegistration,
    owner: &'a OwnedFd,
    retained: Option<&'a RegisteredInitialRunStartRetentionV1>,
    session_end: Instant,
    attempted: bool,
}

impl<'a> OriginalRunStartRetentionExchange<'a> {
    pub(crate) fn new(
        service: &'a HostAuthorityService,
        slot: &'a RegisteredGenerationInitial,
        config: &'a HostAuthorityServiceConfig,
        registration: &'a HostAuthorityRegistration,
        owner: &'a OwnedFd,
        retained: Option<&'a RegisteredInitialRunStartRetentionV1>,
        session_end: Instant,
    ) -> Self {
        Self {
            service,
            slot,
            config,
            registration,
            owner,
            retained,
            session_end,
            attempted: false,
        }
    }

    pub(crate) fn handles(&self, request: &Request) -> bool {
        request.purpose == RUN_START_RETENTION_PURPOSE
            || matches!(request.command, Command::RetainRunStart { .. })
    }

    pub(crate) fn exchange(
        &mut self,
        request: &Request,
        sequence: &mut u64,
    ) -> io::Result<Vec<u8>> {
        if self.attempted {
            return Err(io::Error::other(
                "original RunStart request already attempted",
            ));
        }
        self.attempted = true;
        let retained = self
            .retained
            .ok_or_else(|| io::Error::other("original Root RunStart inputs were not registered"))?;
        let result = (|| {
            require_end(self.session_end)?;
            if request.schema != 1
                || request.purpose != RUN_START_RETENTION_PURPOSE
                || request.profile != self.slot.profile.binding
                || request.request_id != *sequence
            {
                return Err(io::Error::other(
                    "original RunStart purpose/profile/sequence differs",
                ));
            }
            let Command::RetainRunStart { publication } = &request.command else {
                return Err(io::Error::other(
                    "dedicated RunStart retain command required",
                ));
            };
            *sequence = sequence
                .checked_add(1)
                .ok_or_else(|| io::Error::other("initial sequence exhausted"))?;
            self.service.retain_initial_run_start(
                retained,
                self.slot,
                self.config,
                self.registration,
                self.owner,
                publication,
                request.request_id,
                self.session_end,
            )
        })();
        if result.is_err() {
            // Refusal does not read the primary. An interrupted inspect is
            // already Armed; a preflight failure must also stay ineligible.
            retained.refusal.refuse()?;
        }
        result
    }
}
