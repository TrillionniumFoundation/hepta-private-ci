//! Read-only human provenance checks on the original registered issuer lane.
//! The current human registration is installed only by the trusted Root entry.
use super::*;
use crate::deployment_issuer::TextHumanBinding;
use crate::text_session::TextOwnerReceipt;
use std::os::fd::AsRawFd;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

impl HostAuthorityTextUiRegistration {
    pub(super) fn human_binding(&self) -> TextHumanBinding {
        TextHumanBinding {
            principal_id: self.principal_id.clone(),
            session_id: self.session_id.clone(),
            permission_revision: self.permission_revision,
            expires_at_ms: self.expires_at_ms,
            route: self.route.clone(),
        }
    }
}

impl HostAuthorityService {
    pub(crate) fn with_live_human_text(
        mut self,
        registration: HostAuthorityTextUiRegistration,
        ui_pidfd: OwnedFd,
    ) -> io::Result<Self> {
        if self.human_text.is_some() {
            return Err(io::Error::other(
                "original human session is already installed",
            ));
        }
        registration.validate(&self)?;
        self.check_logind_binding(&registration.human_binding())?;
        let fd = ui_pidfd.as_raw_fd();
        let info = std::fs::read_to_string(format!("/proc/self/fdinfo/{fd}"))?;
        if std::fs::read_link(format!("/proc/self/fd/{fd}"))? != Path::new("anon_inode:[pidfd]")
            || info
                .lines()
                .find_map(|line| line.strip_prefix("Pid:").map(str::trim))
                != Some(registration.peer_pid.to_string().as_str())
        {
            return Err(io::Error::other("original human UI held pidfd mismatch"));
        }
        crate::authority_host_runtime::owner_alive(
            &ui_pidfd,
            Instant::now() + Duration::from_secs(1),
        )?;
        self.human_text = Some((registration, ui_pidfd));
        Ok(self)
    }

    pub(super) fn verify_original_human_text(
        &self,
        ingress: &crate::AuthBusTextIngress,
    ) -> Result<TextOwnerReceipt, HostIssuerTransportError> {
        // A protected profile string alone cannot establish a physical login.
        // The explicit original provider must also hand over its live handle.
        if self.logind_session.is_none() {
            return Err(HostIssuerTransportError::Unavailable);
        }
        self.check_logind_lifetime().map_err(unavailable)?;
        let (registration, pidfd) = self
            .human_text
            .as_ref()
            .ok_or(HostIssuerTransportError::Unavailable)?;
        let end = Instant::now() + Duration::from_secs(1);
        crate::authority_host_runtime::owner_alive(pidfd, end).map_err(unavailable)?;
        self.text_ui_owner(registration)?;
        self.issuer
            .verify_retained_human_text(
                &self.identity,
                ingress,
                &registration.human_binding(),
                &registration.namespace(),
            )
            .map_err(unavailable)?;
        crate::authority_host_runtime::owner_alive(pidfd, end).map_err(unavailable)?;
        self.text_ui_owner(registration)
    }
}
