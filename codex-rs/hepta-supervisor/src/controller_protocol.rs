//! Finite desktop lifecycle requests. Release admission and upgrades are absent.

use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Serialize;

use crate::SupervisordControlFence;
use crate::SupervisordMethod;
use crate::SupervisordRequest;
use crate::SupervisordRequestValidationError;

pub const SUPERVISOR_CONTROLLER_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorControllerRequest {
    pub schema_version: u32,
    pub request_id: u64,
    pub method: SupervisorControllerMethod,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum SupervisorControllerMethod {
    /// Restart the current already admitted release, without selecting another.
    Start {
        fence: SupervisordControlFence,
    },
    Stop {
        fence: SupervisordControlFence,
    },
    Restart {
        fence: SupervisordControlFence,
    },
    Receipt {
        agent_id: AgentId,
        mutation_request_id: u64,
    },
}

impl SupervisorControllerRequest {
    pub fn new(request_id: u64, method: SupervisorControllerMethod) -> Self {
        Self {
            schema_version: SUPERVISOR_CONTROLLER_SCHEMA_VERSION,
            request_id,
            method,
        }
    }

    pub fn validate(&self) -> Result<(), SupervisordRequestValidationError> {
        self.clone().owner_request().map(|_| ())
    }

    pub(crate) fn owner_request(
        self,
    ) -> Result<SupervisordRequest, SupervisordRequestValidationError> {
        if self.schema_version != SUPERVISOR_CONTROLLER_SCHEMA_VERSION {
            return Err(SupervisordRequestValidationError::UnsupportedSchema);
        }
        let method = match self.method {
            SupervisorControllerMethod::Start { fence } => {
                let release_id = fence
                    .current_release
                    .clone()
                    .filter(|_| !fence.release_change_pending)
                    .ok_or(SupervisordRequestValidationError::InvalidRequest)?;
                SupervisordMethod::Start { fence, release_id }
            }
            SupervisorControllerMethod::Stop { fence } => SupervisordMethod::Stop { fence },
            SupervisorControllerMethod::Restart { fence } => SupervisordMethod::Restart { fence },
            SupervisorControllerMethod::Receipt {
                agent_id,
                mutation_request_id,
            } => SupervisordMethod::OrdinaryMutationStatus {
                agent_id,
                mutation_request_id,
            },
        };
        let request = SupervisordRequest::new(self.request_id, method);
        request.validate()?;
        Ok(request)
    }
}

#[cfg(test)]
#[path = "controller_protocol_tests.rs"]
mod tests;
