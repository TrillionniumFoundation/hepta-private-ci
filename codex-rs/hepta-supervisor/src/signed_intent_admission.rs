//! Durable admission under one current policy owner; no second authority.
use super::*;
use codex_hepta_fleet::CurrentProtocolConfigurationAdmission;
use codex_hepta_fleet::FleetRegistry;

/// This guard is taken after release/registry preflights and released before
/// entering the existing NodeSoftware owner, whose file lock is not reentrant.
pub(crate) struct MutationPolicyAdmission {
    guard: Option<CurrentProtocolConfigurationAdmission>,
    qualification_now_seconds: u64,
}

impl MutationPolicyAdmission {
    pub(crate) fn acquire(
        registry: &FleetRegistry,
        verifier: &H7H89ProductionGrantVerifier,
        qualification_now_seconds: u64,
    ) -> Result<Self, SupervisorError> {
        let guard = match verifier.policy_sha256() {
            Some(digest) => Some(registry.admit_protocol_configuration(digest_bytes(digest)?)?),
            None if registry.is_release_qualification() => None,
            None => {
                return Err(SupervisorError::ProductionAuthority(
                    "ordinary production requires an explicit current PQ authority policy"
                        .to_string(),
                ));
            }
        };
        Ok(Self {
            guard,
            qualification_now_seconds,
        })
    }

    pub(crate) fn now_seconds(&self) -> Result<u64, SupervisorError> {
        match &self.guard {
            Some(guard) => Ok(guard.revalidate()? / 1000),
            None => Ok(self.qualification_now_seconds),
        }
    }

    pub(crate) fn binding(
        &self,
        registry: &FleetRegistry,
        agent: &codex_hepta_contracts::AgentId,
        release: &codex_hepta_fleet::ReleaseId,
    ) -> Result<codex_hepta_fleet::ReleaseBinding, SupervisorError> {
        match &self.guard {
            Some(guard) => {
                Ok(registry.release_binding_with_protocol_configuration(guard, agent, release)?)
            }
            None => Ok(registry.resolve_release_binding(agent, release)?),
        }
    }

    /// The original intent is durable before the external CAS. A failed or
    /// uncertain publication is retained for containment; it never dispatches.
    pub(crate) fn publish_current(
        self,
        record: &codex_hepta_fleet::AgentRecord,
        previous: Option<&SignedSupervisorIntent>,
        next: &SignedSupervisorIntent,
    ) -> Result<Self, SupervisorError> {
        let Some(guard) = self.guard else {
            crate::signed_intent::write_intent(record.layout.run_root(), next)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            return Ok(self);
        };
        let proof = next.pq_authority.as_ref().ok_or_else(|| {
            SupervisorError::ProductionAuthority(
                "ordinary publication requires the complete PQ grant proof".to_string(),
            )
        })?;
        proof.verify_at(next, guard.revalidate()? / 1000)?;
        let guard = guard.with_verified_decision_window(
            authority_milliseconds(proof.issued_at_unix_seconds)?,
            authority_milliseconds(proof.expires_at_unix_seconds)?,
        )?;
        let old = guard.intent_anchor(&record.release_state.agent_id)?;
        crate::signed_intent_anchor::check_previous(old.as_ref(), previous, record)?;
        if crate::signed_intent::read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .as_ref()
            != previous
        {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                record.release_state.agent_id.clone(),
            ));
        }
        let anchor = crate::signed_intent_anchor::next_anchor(old.as_ref(), next, record)?;
        if let Some(previous) = previous {
            crate::signed_intent::predecessor::stage(record.layout.run_root(), previous)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }
        crate::signed_intent::write_intent(record.layout.run_root(), next)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let guard = guard.anchor_intent(old.as_ref(), &anchor)?;
        crate::signed_intent::predecessor::clear_after_confirmation(record.layout.run_root(), next)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        Ok(Self {
            guard: Some(guard),
            qualification_now_seconds: self.qualification_now_seconds,
        })
    }

    pub(crate) fn publish_recovery(
        self,
        record: &codex_hepta_fleet::AgentRecord,
        previous: &SignedSupervisorIntent,
        next: &SignedSupervisorIntent,
        decision: &crate::ProductionRecoveryDecision,
    ) -> Result<Self, SupervisorError> {
        let Some(guard) = self.guard else {
            crate::signed_intent::write_intent(record.layout.run_root(), next)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            return Ok(self);
        };
        let guard = guard.with_verified_decision_window(
            authority_milliseconds(decision.issued_at_unix_seconds)?,
            authority_milliseconds(decision.expires_at_unix_seconds)?,
        )?;
        let old = guard.intent_anchor(&record.release_state.agent_id)?;
        if old.is_some() {
            crate::signed_intent_anchor::check_previous(old.as_ref(), Some(previous), record)?;
        } else if !previous.requires_recovery() {
            // Old unanchored terminal labels never bootstrap current authority.
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                record.release_state.agent_id.clone(),
            ));
        }
        if crate::signed_intent::read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .as_ref()
            != Some(previous)
        {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                record.release_state.agent_id.clone(),
            ));
        }
        let anchor = crate::signed_intent_anchor::next_anchor(old.as_ref(), next, record)?;
        if old.is_some() {
            crate::signed_intent::predecessor::stage(record.layout.run_root(), previous)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }
        crate::signed_intent::write_intent(record.layout.run_root(), next)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let guard =
            guard.recover_intent(old.as_ref(), &anchor, digest_bytes(decision.digest())?)?;
        crate::signed_intent::predecessor::clear_after_confirmation(record.layout.run_root(), next)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        Ok(Self {
            guard: Some(guard),
            qualification_now_seconds: self.qualification_now_seconds,
        })
    }

    pub(crate) fn revalidate_window(
        &self,
        issued: u64,
        expires: u64,
    ) -> Result<(), SupervisorError> {
        current_window(self.now_seconds()?, issued, expires)
    }
}
