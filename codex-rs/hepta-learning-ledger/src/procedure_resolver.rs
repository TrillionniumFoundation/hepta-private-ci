//! Host-approved procedure profiles resolved through the current durable owner.

use codex_hepta_types::FixedQ32;

use super::*;
use crate::ProcedureExecutionEvidenceV1;

/// Installed by the trusted host before requests are handled. The exact plan,
/// environment, preconditions and success predicates must already be approved;
/// an arbitrary positive reward or a request-selected threshold cannot qualify.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcedureQualificationProfileV1 {
    pub profile_id: StableId,
    pub contract_digest: Digest32,
    pub unit_profile_digest: Digest32,
    pub successful_value: FixedQ32,
    pub maximum_evidence_age_seconds: u64,
}

/// An owner borrow and an immutable evidence borrow; neither is detached or
/// cloned. Consumers must recheck currentness immediately before committing or
/// using the qualified memory. This does not authorize execution effects.
pub struct VerifiedProcedureExecutionV1<'owner> {
    current: CurrentAuthenticatedOutcomeV1<'owner>,
    evidence: &'owner ProcedureExecutionEvidenceV1,
    contract_digest: Digest32,
    valid_until: u64,
}

impl<'owner> VerifiedProcedureExecutionV1<'owner> {
    pub fn ensure_current(&self) -> Result<(), ProductionLedgerError> {
        self.current.ensure_current()?;
        if self.current.owner_time()? > self.valid_until {
            return Err(ProductionLedgerError::Binding("procedure evidence expired"));
        }
        Ok(())
    }

    #[must_use]
    pub fn evidence(&self) -> &ProcedureExecutionEvidenceV1 {
        self.evidence
    }

    #[must_use]
    pub fn current_outcome(&self) -> &CurrentAuthenticatedOutcomeV1<'owner> {
        &self.current
    }

    #[must_use]
    pub fn contract_digest(&self) -> Digest32 {
        self.contract_digest
    }

    #[must_use]
    pub fn valid_until_unix_seconds(&self) -> u64 {
        self.valid_until
    }
}

impl LedgerWriter {
    pub fn install_procedure_profile(
        &mut self,
        profile: ProcedureQualificationProfileV1,
    ) -> Result<(), ProductionLedgerError> {
        if profile.contract_digest.is_zero()
            || profile.unit_profile_digest.is_zero()
            || profile.maximum_evidence_age_seconds == 0
            || (self.procedure_profiles.len() >= 32
                && !self.procedure_profiles.contains_key(&profile.profile_id))
        {
            return Err(ProductionLedgerError::Binding(
                "invalid host procedure profile",
            ));
        }
        self.procedure_profiles
            .insert(profile.profile_id.clone(), profile);
        Ok(())
    }

    pub fn remove_procedure_profile(&mut self, profile_id: &StableId) -> bool {
        self.procedure_profiles.remove(profile_id).is_some()
    }

    pub fn resolve_procedure_execution<'owner>(
        &'owner self,
        outcome_record_id: &StableId,
        evidence: &'owner ProcedureExecutionEvidenceV1,
    ) -> Result<VerifiedProcedureExecutionV1<'owner>, ProductionLedgerError> {
        let profile = self.procedure_profiles.get(&evidence.profile_id).ok_or(
            ProductionLedgerError::Binding("procedure profile not installed by host"),
        )?;
        let contract_digest = evidence.contract_digest()?;
        if contract_digest != profile.contract_digest {
            return Err(ProductionLedgerError::Binding(
                "procedure contract differs from host profile",
            ));
        }
        let support = evidence.canonical_digest()?;
        evidence.validate_successful_execution()?;
        let current =
            self.resolve_current_outcome(outcome_record_id, &evidence.episode_id, support)?;
        let outcome = current.outcome();
        let decision = current.decision();
        if outcome.observer_id != evidence.observer_id
            || outcome.observed_at != Some(evidence.observer_checked_at)
            || outcome.unit_profile_digest != profile.unit_profile_digest
            || outcome.value != Some(profile.successful_value)
            || decision.record_id != evidence.decision_record_id
            || decision.run_snapshot_digest != evidence.run_snapshot_digest
            || decision.selected_candidate_id != evidence.procedure_id
            || decision.support_digest != contract_digest
        {
            return Err(ProductionLedgerError::Binding(
                "procedure current decision/outcome binding",
            ));
        }
        let age_deadline = evidence
            .observer_checked_at
            .checked_add(profile.maximum_evidence_age_seconds)
            .ok_or(ProductionLedgerError::Binding("procedure expiry overflow"))?;
        let valid_until = age_deadline.min(current.valid_until_unix_seconds());
        let verified = VerifiedProcedureExecutionV1 {
            current,
            evidence,
            contract_digest,
            valid_until,
        };
        verified.ensure_current()?;
        Ok(verified)
    }
}
