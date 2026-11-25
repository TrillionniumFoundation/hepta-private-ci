//! Read-only human provenance checks on the original registered issuer lane.
//! The current human registration is installed only by the trusted Root entry.
use super::*;
use crate::deployment_issuer::TextHumanBinding;
use crate::text_session::TextOwnerReceipt;
use std::os::fd::AsRawFd;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

/// A borrowed lifetime check over the two original installed descriptors.
/// Keeping this value is not authority to read material later: callers must
/// check it again at the synchronous entry under their original owner locks.
pub(crate) struct OriginalHumanLifetime<'a> {
    registration: &'a HostAuthorityTextUiRegistration,
    ui: &'a OwnedFd,
    login: &'a super::logind::OriginalLogindSession,
    end: Instant,
}

impl<'a> OriginalHumanLifetime<'a> {
    pub(super) fn from_original(
        human: Option<&'a (HostAuthorityTextUiRegistration, OwnedFd)>,
        login: Option<&'a super::logind::OriginalLogindSession>,
        end: Instant,
    ) -> io::Result<Self> {
        let (registration, ui) =
            human.ok_or_else(|| io::Error::other("original human UI is not installed"))?;
        let login =
            login.ok_or_else(|| io::Error::other("original physical login is not installed"))?;
        let held = Self {
            registration,
            ui,
            login,
            end,
        };
        held.recheck_original_human_lifetime(&registration.human_binding())?;
        Ok(held)
    }

    pub(crate) fn binding(&self) -> TextHumanBinding {
        self.registration.human_binding()
    }

    pub(crate) fn namespace(&self) -> String {
        self.registration.namespace()
    }

    pub(crate) fn recheck_original_human_lifetime(
        &self,
        expected: &TextHumanBinding,
    ) -> io::Result<()> {
        if self.registration.human_binding() != *expected {
            return Err(io::Error::other("original human UI binding changed"));
        }
        self.login
            .check_original_human_binding(expected, self.end)?;
        crate::authority_host_runtime::owner_alive(self.ui, self.end)
    }
}

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
        let end = Instant::now() + Duration::from_secs(1);
        let held = OriginalHumanLifetime::from_original(
            self.human_text.as_ref(),
            self.logind_session.as_ref(),
            end,
        )
        .map_err(unavailable)?;
        let registration = held.registration;
        self.text_ui_owner(registration)?;
        self.issuer
            .verify_retained_human_text(&self.identity, ingress, &held.binding(), &held.namespace())
            .map_err(unavailable)?;
        let owner = self.text_ui_owner(registration)?;
        held.recheck_original_human_lifetime(&held.binding())
            .map_err(unavailable)?;
        Ok(owner)
    }
}
