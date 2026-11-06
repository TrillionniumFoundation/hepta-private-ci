#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct ProcessState {
    pub(crate) has_exited: bool,
    pub(crate) exit_code: Option<i32>,
    pub(crate) failure_message: Option<String>,
    pub(crate) sandbox_denied: bool,
}

impl ProcessState {
    pub(crate) fn exited(&self, exit_code: Option<i32>) -> Self {
        if self.has_exited {
            return self.clone();
        }
        Self {
            has_exited: true,
            exit_code,
            failure_message: self.failure_message.clone(),
            sandbox_denied: self.sandbox_denied,
        }
    }

    /// A control or policy failure does not establish a native exit.
    pub(crate) fn failed(&self, message: String) -> Self {
        Self {
            failure_message: self.failure_message.clone().or(Some(message)),
            ..self.clone()
        }
    }

    /// Losing an observation channel does not establish a native process exit.
    pub(crate) fn observation_failed(&self, message: String) -> Self {
        Self {
            failure_message: self.failure_message.clone().or(Some(message)),
            ..self.clone()
        }
    }
}
