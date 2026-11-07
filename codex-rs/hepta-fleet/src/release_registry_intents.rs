//! Typed H7 history access through the ordinary Fleet publication owner.

use codex_hepta_contracts::AgentId;
use std::sync::Arc;

use super::CurrentProtocolConfigurationAdmission;
use super::CurrentReleaseAdmission;
use super::ReleaseMode;
use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::ReleaseBinding;
use crate::ReleaseId;
use crate::ReleaseIntentAnchorV1;
use crate::release_authority::VerifiedDecisionWindow;
use crate::release_authority::invalid;

impl FleetRegistry {
    /// Same-lock signed-recovery observation. The result is a description and
    /// cannot authorize a process launch or extend either publication lifetime.
    pub fn release_binding_with_protocol_configuration(
        &self,
        admission: &CurrentProtocolConfigurationAdmission,
        agent: &AgentId,
        release: &ReleaseId,
    ) -> Result<ReleaseBinding, FleetRegistryError> {
        if !matches!(&self.release_authority, ReleaseMode::Pq(owner)
            if Arc::ptr_eq(owner, &admission.owner))
        {
            return Err(invalid(
                "protocol admission belongs to another release owner",
            ));
        }
        let projection = admission.owner.publication_member_projection(
            &admission.publication,
            agent,
            release,
        )?;
        let binding = self.observe_reconciliation_release_binding(
            agent,
            release,
            &projection.0,
            projection.1,
        )?;
        if admission
            .owner
            .publication_member_projection(&admission.publication, agent, release)?
            != projection
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        Ok(binding)
    }

    pub fn release_intent_anchor(
        &self,
        agent: &AgentId,
    ) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        self.pq_release_authority()?.intent_anchor(agent)
    }

    /// Retain only an exact predecessor's strict quarantine or the hot release
    /// owner's observed completion. This creates no new execution permission.
    pub fn record_intent_history(
        &self,
        expected: &ReleaseIntentAnchorV1,
        next: &ReleaseIntentAnchorV1,
    ) -> Result<(), FleetRegistryError> {
        self.pq_release_authority()?
            .record_intent_history(expected, next)
    }
}

impl CurrentProtocolConfigurationAdmission {
    /// The caller must first verify the actual PQ decision and convert its
    /// signed times to milliseconds with checked arithmetic. Every subsequent
    /// current check and the final external CAS enforce this exact window.
    pub fn with_verified_decision_window(
        mut self,
        not_before_ms: u64,
        expires_at_ms: u64,
    ) -> Result<Self, FleetRegistryError> {
        self.publication.decision_window =
            Some(VerifiedDecisionWindow::new(not_before_ms, expires_at_ms)?);
        self.revalidate()?;
        Ok(self)
    }

    pub fn previous_closed_intent_anchor(
        &self,
        agent: &AgentId,
    ) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        self.owner
            .previous_closed_intent_held(&self.publication, agent)
    }

    pub fn intent_anchor(
        &self,
        agent: &AgentId,
    ) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        self.owner.intent_anchor_held(&self.publication, agent)
    }

    /// Consume and refresh this same locked admission after its one external
    /// CAS. Callers first durably retain the exact new H7 intent; any error
    /// leaves it fenced. Revalidate at the actual effect entry after this call.
    pub fn anchor_intent(
        mut self,
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
    ) -> Result<Self, FleetRegistryError> {
        self.owner
            .anchor_protocol_intent(&mut self.publication, expected, next)?;
        Ok(self)
    }

    /// The caller verifies the explicit recovery decision under this current
    /// policy. The snapshot retains the original grant policy unchanged.
    pub fn recover_intent(
        mut self,
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
        decision_sha256: [u8; 32],
    ) -> Result<Self, FleetRegistryError> {
        self.owner.recover_protocol_intent(
            &mut self.publication,
            expected,
            next,
            decision_sha256,
        )?;
        Ok(self)
    }

    /// Explicit signed abandonment after a new Prepared file replaced a closed
    /// predecessor but its anchor CAS never committed. The H7 owner must verify
    /// its retained predecessor bytes, original proof, complete history prefix
    /// and actual transaction/state witness against the signed observation.
    /// This API cannot be used by ordinary anchoring or historical completion.
    pub fn recover_unanchored_intent(
        mut self,
        expected: &ReleaseIntentAnchorV1,
        next: &ReleaseIntentAnchorV1,
        decision_sha256: [u8; 32],
        predecessor_anchor_sha256: [u8; 32],
    ) -> Result<Self, FleetRegistryError> {
        self.owner.recover_unanchored_protocol_intent(
            &mut self.publication,
            expected,
            next,
            decision_sha256,
            predecessor_anchor_sha256,
        )?;
        Ok(self)
    }

    /// Records a separately signed publication confirmation for an already
    /// durable AbandonUnknown decision. It cannot confirm successful execution,
    /// alter that original decision or authorize any process dispatch.
    pub fn confirm_abandon_unknown_publication(
        mut self,
        expected: &ReleaseIntentAnchorV1,
        next: &ReleaseIntentAnchorV1,
        confirmation_sha256: [u8; 32],
        expected_anchor_sha256: [u8; 32],
    ) -> Result<Self, FleetRegistryError> {
        self.owner.confirm_abandon_unknown_publication(
            &mut self.publication,
            expected,
            next,
            confirmation_sha256,
            expected_anchor_sha256,
        )?;
        Ok(self)
    }
}

impl CurrentReleaseAdmission {
    /// Bind the verified grant/artifact window intersection before a new
    /// pending intent transition. Historical terminal reads need no old window.
    pub fn with_verified_decision_window(
        mut self,
        not_before_ms: u64,
        expires_at_ms: u64,
    ) -> Result<Self, FleetRegistryError> {
        let (owner, admission) = self
            .authority
            .as_mut()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?;
        admission.publication.decision_window =
            Some(VerifiedDecisionWindow::new(not_before_ms, expires_at_ms)?);
        owner.recheck(&admission.publication)?;
        Ok(self)
    }

    pub fn previous_closed_intent_anchor(
        &self,
    ) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        let (owner, admission) = self
            .authority
            .as_ref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?;
        let agent = admission
            .agent_id
            .as_ref()
            .ok_or_else(|| invalid("release admission has no bound agent"))?;
        owner.previous_closed_intent_held(&admission.publication, agent)
    }

    pub fn intent_anchor(&self) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        let (owner, admission) = self
            .authority
            .as_ref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?;
        let agent = admission
            .agent_id
            .as_ref()
            .ok_or_else(|| invalid("release admission has no bound agent"))?;
        owner.intent_anchor_held(&admission.publication, agent)
    }

    pub fn anchor_intent(
        mut self,
        policy_sha256: [u8; 32],
        expected: Option<&ReleaseIntentAnchorV1>,
        next: &ReleaseIntentAnchorV1,
    ) -> Result<Self, FleetRegistryError> {
        // Inspect actual retained program bytes before the fresh trust check.
        crate::release::revalidate_catalog_release(&self.catalog, &self.release)?;
        let (owner, admission) = self
            .authority
            .as_mut()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?;
        if admission.agent_id.as_ref() != Some(&next.agent_id) {
            return Err(invalid("intent anchor belongs to another release agent"));
        }
        owner.anchor_release_intent(&mut admission.publication, policy_sha256, expected, next)?;
        Ok(self)
    }
}
