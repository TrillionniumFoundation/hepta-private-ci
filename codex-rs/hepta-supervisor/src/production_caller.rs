use std::path::PathBuf;

use codex_hepta_memory::H7SignedArtifactEnvelope;
use serde::Deserialize;
use serde::Serialize;

use crate::H7H89ProductionGrant;
use crate::H7H89ProductionTransition;
use crate::SupervisordClient;
use crate::SupervisordControlFence;
use crate::SupervisordMutationAccepted;
use crate::SupervisorError;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionCallerRequest {
    pub fence: SupervisordControlFence,
    pub grant: H7H89ProductionGrant,
    pub h7_envelope: H7SignedArtifactEnvelope,
}

impl ProductionCallerRequest {
    pub fn validate(&self) -> Result<(), SupervisorError> {
        self.fence
            .validate()
            .map_err(|_| SupervisorError::Invalid("production caller fence is invalid".to_string()))?;
        if self.grant.agent_id != self.fence.agent_id.to_string() {
            return Err(SupervisorError::Invalid(
                "production caller grant does not bind the fenced Agent".to_string(),
            ));
        }
        self.grant
            .validate_shape(&self.h7_envelope)
            .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))
    }
}

pub async fn execute_production_caller(
    socket_path: PathBuf,
    request: ProductionCallerRequest,
) -> Result<SupervisordMutationAccepted, SupervisorError> {
    request.validate()?;
    let client = SupervisordClient::new(socket_path)?;
    match request.grant.transition {
        H7H89ProductionTransition::Upgrade => {
            client
                .signed_upgrade(request.fence, request.grant, request.h7_envelope)
                .await
        }
        H7H89ProductionTransition::Rollback => {
            client
                .signed_rollback(request.fence, request.grant, request.h7_envelope)
                .await
        }
    }
}
