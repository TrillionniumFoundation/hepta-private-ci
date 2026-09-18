//! Authoritative prompt-registry mutations.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::model::AdmissionRequest;
use crate::model::Error;
use crate::model::FactorAdmissionRecord;
use crate::model::FactorSource;
use crate::model::Lifecycle;
use crate::model::LifecycleEventKind;
use crate::model::MutationDisposition;
use crate::model::PromptFactor;
use crate::model::PromptRealization;
use crate::model::RegistryReceipt;
use crate::model::lifecycle_event;
use crate::model::push_id;
use crate::registry::PromptRegistry;

const ADMISSION_BINDING_DOMAIN: &[u8] = b"hepta.prompt-registry.admission-binding.v1";

impl PromptRegistry {
    pub fn register_factor(&mut self, factor: PromptFactor) -> Result<RegistryReceipt, Error> {
        if factor.content_digest.is_zero() {
            return Err(Error::EmptyDigest("factor content"));
        }
        if factor.lifecycle != Lifecycle::Draft {
            return Err(Error::InvalidTransition);
        }
        if let Some(existing) = self.factors.get(&factor.factor_id) {
            if existing == &factor {
                return Ok(self.receipt(MutationDisposition::Unchanged));
            }
            return Err(Error::FactorConflict(factor.factor_id.to_string()));
        }
        self.ensure_capacity(/*additional*/ 1)?;
        self.ensure_lifecycle_capacity(/*additional*/ 1)?;
        let next_revision = self.next_revision()?;
        let event = lifecycle_event(
            factor.factor_id.clone(),
            LifecycleEventKind::Registered,
            None,
            Lifecycle::Draft,
            next_revision,
            factor.proposer_id.clone(),
            None,
            None,
            None,
            None,
        );
        self.factors.insert(factor.factor_id.clone(), factor);
        self.lifecycle_history.push(event);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    /// Legacy admission without an independently verified capability is denied.
    /// Call [`Self::admit_factor_authorized`] instead.
    pub fn admit_factor(
        &mut self,
        _factor_id: &StableId,
        _reviewer_id: &StableId,
        _evidence_digest: Digest32,
    ) -> Result<RegistryReceipt, Error> {
        Err(Error::AuthenticatedAdmissionRequired)
    }

    /// Build the exact final-use binding that an independent authority must sign.
    pub fn admission_binding(&self, request: &AdmissionRequest) -> Result<FinalUseBinding, Error> {
        self.validate_admission_request(request)?;
        let factor = self
            .factors
            .get(&request.factor_id)
            .ok_or_else(|| Error::FactorNotFound(request.factor_id.to_string()))?;
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ADMISSION_BINDING_DOMAIN);
        push_id(&mut bytes, &factor.factor_id);
        push_id(&mut bytes, &factor.proposer_id);
        push_id(&mut bytes, &factor.semantic_version);
        bytes.extend_from_slice(factor.content_digest.as_array());
        push_id(&mut bytes, &request.reviewer_id);
        bytes.extend_from_slice(request.evidence_digest.as_array());
        bytes.extend_from_slice(request.reviewed_scope_digest.as_array());
        let payload_digest = Digest32::of_bytes(&bytes);
        Ok(FinalUseBinding {
            subject_id: request.reviewer_id.to_string(),
            destination_id: "prompt.registry:admit_factor".to_string(),
            request_sha256: request.evidence_digest.into_array(),
            scope_sha256: request.reviewed_scope_digest.into_array(),
            payload_sha256: payload_digest.into_array(),
        })
    }

    /// Consume one independently verified, single-use and revocation-aware grant
    /// while transitioning a factor from draft to admitted.
    pub fn admit_factor_authorized(
        &mut self,
        authority: &FinalUseAuthority,
        token: VerifiedUseToken,
        request: AdmissionRequest,
    ) -> Result<RegistryReceipt, Error> {
        let expected = self.admission_binding(&request)?;
        authority
            .with_verified_use(token, &expected, || self.admit_factor_verified(request))
            .map_err(|error| Error::Authority(error.to_string()))?
    }

    pub(crate) fn admit_factor_verified(
        &mut self,
        request: AdmissionRequest,
    ) -> Result<RegistryReceipt, Error> {
        self.validate_admission_request(&request)?;
        let Some(factor) = self.factors.get(&request.factor_id) else {
            return Err(Error::FactorNotFound(request.factor_id.to_string()));
        };
        if factor.source == FactorSource::ExternalUntrusted {
            return Err(Error::ExternalSelfAdmission);
        }
        if factor.proposer_id == request.reviewer_id {
            return Err(Error::SelfReview);
        }
        if factor.lifecycle != Lifecycle::Draft {
            return Err(Error::InvalidTransition);
        }
        if self.admissions.contains_key(&request.factor_id) {
            return Err(Error::InvalidTransition);
        }
        self.ensure_lifecycle_capacity(/*additional*/ 1)?;
        let next_revision = self.next_revision()?;
        let mut admission = FactorAdmissionRecord {
            factor_id: request.factor_id.clone(),
            reviewer_id: request.reviewer_id.clone(),
            evidence_digest: request.evidence_digest,
            reviewed_scope_digest: request.reviewed_scope_digest,
            revision: next_revision,
            admission_digest: Digest32::ZERO,
        };
        admission.admission_digest = admission.compute_digest();
        admission.validate()?;
        let event = lifecycle_event(
            request.factor_id.clone(),
            LifecycleEventKind::Admitted,
            Some(Lifecycle::Draft),
            Lifecycle::Admitted,
            next_revision,
            request.reviewer_id,
            Some(request.evidence_digest),
            Some(request.reviewed_scope_digest),
            None,
            None,
        );
        let factor = self
            .factors
            .get_mut(&request.factor_id)
            .ok_or_else(|| Error::FactorNotFound(request.factor_id.to_string()))?;
        factor.lifecycle = Lifecycle::Admitted;
        self.admissions.insert(request.factor_id, admission);
        self.lifecycle_history.push(event);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    /// Legacy digest-only realization registration is retained only for
    /// compatibility with old callers and reopened historical records. New
    /// digest-only records are rejected because they cannot prove exact-profile
    /// payload delivery. Call `register_realization_v2` with bounded payload
    /// bytes instead.
    pub fn register_realization(
        &mut self,
        realization: PromptRealization,
    ) -> Result<RegistryReceipt, Error> {
        for (name, value) in [
            ("model", realization.model_digest),
            ("tokenizer", realization.tokenizer_digest),
            ("realization content", realization.content_digest),
        ] {
            if value.is_zero() {
                return Err(Error::EmptyDigest(name));
            }
        }
        let Some(factor) = self.factors.get(&realization.factor_id) else {
            return Err(Error::FactorNotFound(realization.factor_id.to_string()));
        };
        if factor.lifecycle != Lifecycle::Admitted {
            return Err(Error::FactorNotAdmitted(realization.factor_id.to_string()));
        }
        if !realization.active {
            return Err(Error::InvalidTransition);
        }
        if let Some(existing) = self.realizations.get(&realization.realization_id) {
            if existing == &realization {
                return Ok(self.receipt(MutationDisposition::Unchanged));
            }
            return Err(Error::RealizationConflict(
                realization.realization_id.to_string(),
            ));
        }
        Err(Error::PayloadRequired)
    }

    pub fn retire_factor(&mut self, _factor_id: &StableId) -> Result<RegistryReceipt, Error> {
        Err(Error::LifecycleReasonRequired)
    }

    pub fn retire_factor_with_reason(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<RegistryReceipt, Error> {
        if reason_digest.is_zero() {
            return Err(Error::EmptyDigest("retirement reason"));
        }
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if factor.lifecycle != Lifecycle::Admitted {
            return Err(Error::InvalidTransition);
        }
        self.ensure_lifecycle_capacity(/*additional*/ 1)?;
        let next_revision = self.next_revision()?;
        let event = lifecycle_event(
            factor_id.clone(),
            LifecycleEventKind::Retired,
            Some(Lifecycle::Admitted),
            Lifecycle::Retired,
            next_revision,
            actor_id.clone(),
            None,
            None,
            Some(reason_digest),
            None,
        );
        let factor = self
            .factors
            .get_mut(factor_id)
            .ok_or_else(|| Error::FactorNotFound(factor_id.to_string()))?;
        factor.lifecycle = Lifecycle::Retired;
        self.disable_realizations(factor_id);
        self.lifecycle_history.push(event);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub fn revoke_factor(&mut self, _factor_id: &StableId) -> Result<RegistryReceipt, Error> {
        Err(Error::LifecycleReasonRequired)
    }

    pub fn revoke_factor_with_reason(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
        cutoff_unix_ms: u64,
    ) -> Result<RegistryReceipt, Error> {
        if reason_digest.is_zero() {
            return Err(Error::EmptyDigest("revocation reason"));
        }
        if cutoff_unix_ms == 0 {
            return Err(Error::InvalidTransition);
        }
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if !matches!(factor.lifecycle, Lifecycle::Admitted | Lifecycle::Retired) {
            return Err(Error::InvalidTransition);
        }
        self.ensure_lifecycle_capacity(/*additional*/ 1)?;
        let from = factor.lifecycle;
        let next_revision = self.next_revision()?;
        let event = lifecycle_event(
            factor_id.clone(),
            LifecycleEventKind::Revoked,
            Some(from),
            Lifecycle::Revoked,
            next_revision,
            actor_id.clone(),
            None,
            None,
            Some(reason_digest),
            Some(cutoff_unix_ms),
        );
        let factor = self
            .factors
            .get_mut(factor_id)
            .ok_or_else(|| Error::FactorNotFound(factor_id.to_string()))?;
        factor.lifecycle = Lifecycle::Revoked;
        self.disable_realizations(factor_id);
        self.lifecycle_history.push(event);
        self.commit_revision(next_revision, /*revocation*/ true);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }
}
