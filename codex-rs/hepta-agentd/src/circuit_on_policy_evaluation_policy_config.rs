//! Explicit V2 producer configuration. A legacy V1 rule has no default policy.

use std::sync::Arc;

use super::Error;
use super::OriginalCircuitOnPolicyCohortConfigV1;
use super::policy::OriginalCircuitOnPolicyPanelPolicyV2;

pub struct OriginalCircuitOnPolicyCohortConfigV2 {
    pub(super) original: OriginalCircuitOnPolicyCohortConfigV1,
    pub(super) policy: Arc<OriginalCircuitOnPolicyPanelPolicyV2>,
}

impl OriginalCircuitOnPolicyCohortConfigV2 {
    pub fn from_original(
        original: OriginalCircuitOnPolicyCohortConfigV1,
        policy: Arc<OriginalCircuitOnPolicyPanelPolicyV2>,
    ) -> Result<Self, Error> {
        crate::OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_training(&policy, &original.training)?;
        let member = policy.member(&original.rule.plan_id)?;
        if policy.registration() != &original.registration
            || member.task_digest() != original.rule.task_digest
            || member.cohort_rule_digest()? != original.freeze_plan.inclusion_policy_digest
        {
            return Err(Error::Binding("explicit complete V2 declaration and original producer"));
        }
        Ok(Self { original, policy })
    }
}
