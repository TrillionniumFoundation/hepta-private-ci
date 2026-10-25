use super::AgentdConfig;

pub(crate) enum AgentdSocketInputs {
    Bind,
    #[cfg(target_os = "linux")]
    RootBound {
        control: std::os::fd::OwnedFd,
        app_server: std::os::fd::OwnedFd,
    },
}

impl AgentdConfig {
    /// Retain the two descriptors after the original Root handoff and actual
    /// credential drop. Both must remain bound but not listening. Runtime takes
    /// them once; neither a path nor an environment flag supplies this right.
    #[cfg(target_os = "linux")]
    pub fn with_root_bound_sockets(
        mut self,
        control: std::os::fd::OwnedFd,
        app_server: std::os::fd::OwnedFd,
    ) -> Result<Self, crate::AgentdError> {
        if !matches!(self.sockets, AgentdSocketInputs::Bind) {
            return Err(crate::AgentdError::Invalid("Root-bound sockets already configured".into()));
        }
        crate::root_bound_socket::validate_root_bound_socket(&control, &self.identity.control_socket)?;
        crate::root_bound_socket::validate_root_bound_socket(&app_server, &self.identity.app_server_socket)?;
        self.sockets = AgentdSocketInputs::RootBound { control, app_server };
        Ok(self)
    }

    pub(crate) fn take_socket_inputs(&mut self) -> AgentdSocketInputs {
        std::mem::replace(&mut self.sockets, AgentdSocketInputs::Bind)
    }
}
