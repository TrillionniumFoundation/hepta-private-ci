use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::AuthBusAuthorityHost;
use crate::AuthBusAuthorityError;
use crate::AuthPolicy;
use crate::PolicyDecision;
use crate::PolicySpec;
use crate::TrustedTimeSample;

impl AuthBusAuthorityHost {
    pub async fn create_policy(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.create_policy(spec, time).await
    }

    pub async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
            .replace_policy(spec, expected_revision, time)
            .await
    }

    pub async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
            .revoke_policy(policy_id, expected_revision, time)
            .await
    }

    pub async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
            .retire_policy(policy_id, expected_revision, retired_at_ms)
            .await
    }

    pub async fn authorize(
        &self,
        principal: &StableId,
        action: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
            .authorize(principal, action, scope_digest, policy_revision, time)
            .await
    }
}
