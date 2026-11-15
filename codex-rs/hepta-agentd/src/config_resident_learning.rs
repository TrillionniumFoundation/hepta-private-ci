//! Explicit optional late enrollment. Startup holds only a bounded actor;
//! the actual completed-A Root profile arrives later through its original peer.

use super::AgentdConfig;
use crate::AgentdError;
use crate::AgentdRootResidentDeliveryV3;
use crate::AgentdRootResidentEnrollmentV3;

impl AgentdConfig {
    /// Opt in to one late original-Root handoff. This allocates no learning
    /// request, profile, checkpoint, signer or future task receipt.
    pub fn with_root_resident_learning_enrollment(
        mut self,
    ) -> Result<(Self, AgentdRootResidentEnrollmentV3), AgentdError> {
        if self.resident_learning_delivery.is_some()
            || self.learning_iteration_bootstrap.is_some()
            || self.root_learning_inputs.is_some()
            || self.circuit_task_bootstrap.is_none()
            || self.circuit_task_invocation.is_none()
            || self.objective_profile_file.is_none()
            || self.authbus_trust_file.is_none()
        {
            return Err(AgentdError::Invalid(
                "resident learning requires its exclusive ordinary Circuit/Objective source".into(),
            ));
        }
        let (enrollment, delivery) =
            crate::circuit_learning_delivery::root_resident_learning_delivery_v3();
        self.resident_learning_delivery = Some(delivery);
        Ok((self, enrollment))
    }

    pub(crate) fn take_root_resident_learning_delivery(
        &mut self,
    ) -> Option<AgentdRootResidentDeliveryV3> {
        self.resident_learning_delivery.take()
    }
}
