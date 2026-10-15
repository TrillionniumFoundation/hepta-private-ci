//! Non-authorizing, all-or-nothing signed Stem batch proposal over the
//! ORIGINAL inference Worker owner. No batch effect/driver is invoked here.
//!
//! This is the preparation boundary for a future native backend batch, not a
//! second dispatcher, signature issuer, or authority grant. The executor MUST
//! revalidate every member and its current CAS/Final-use fence at actual use.

use std::collections::BTreeSet;

#[cfg(test)]
use codex_hepta_contracts::FinalUseAuthority;
#[cfg(test)]
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_infer_core::StemAccessContextV1;
use codex_hepta_infer_core::StemFeatureRefV1;
use codex_hepta_infer_core::StemHeadBindingV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::stem_artifact_cas::StemArtifactCasVerifierV1;
use crate::stem_artifact_cas::VerifiedStemCasArtifactsV1;

use super::Error;
use super::InferenceWorker;
use super::MAX_ACTIVE_REQUESTS;
use super::ModelDriver;
use super::NeuronFeatureDriver;
use super::WorkerRequest;
#[cfg(test)]
use super::with_verified_stem_batch_tokens_v1;

const MAX_BATCH_MEMBERS: usize = 32;

pub struct StemBatchMemberProposalV1<'a> {
    pub selected_head: &'a StemHeadBindingV1,
    pub authorization: &'a WorkerRequest,
}

/// One source, Scope, Principal, Generation, epoch and numerical feature
/// across multiple independent Head decisions. All caller claims still need
/// authentication from the original owners at actual physical dispatch.
#[derive(Clone, Copy)]
pub struct StemBatchProposalV1<'a> {
    pub source: &'a StemFeatureRefV1,
    pub access: &'a StemAccessContextV1,
    pub cas_verifier: &'a StemArtifactCasVerifierV1,
    pub verified_artifacts: &'a VerifiedStemCasArtifactsV1,
    pub feature_vector_q24: &'a [i64],
    pub members: &'a [StemBatchMemberProposalV1<'a>],
}

/// Read-only batch intent. Bindings are merely proposals to the independent
/// signer, NEVER signed tokens, a live reservation, or execution authority.
#[derive(Debug)]
pub struct NonAuthorizingStemBatchPlanV1 {
    pub batch_digest: Digest32,
    /// An independently signed *aggregate* intent is required in addition to
    /// every independently signed member. Otherwise valid standalone member
    /// grants could be recombined into an unapproved multi-Head operation.
    pub group_binding: FinalUseBinding,
    pub bindings: Vec<FinalUseBinding>,
    pub authority: AuthorityPosture,
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    /// Require *every* Head/lease/Scope/loaded-model match before returning
    /// any batch plan. No driver call, model mutation or signing occurs.
    pub fn prepare_stem_final_use_batch_proposal_v1(
        &self,
        now_ms: u64,
        proposal: StemBatchProposalV1<'_>,
    ) -> Result<NonAuthorizingStemBatchPlanV1, Error> {
        self.validate_current_grant(now_ms)?;
        if proposal.members.is_empty() || proposal.members.len() > MAX_BATCH_MEMBERS {
            return Err(Error::FeatureLimit);
        }
        if proposal.access.now_ms != now_ms
            || proposal.source.authority_epoch != self.grant.authority_epoch
            || proposal.access.authority_epoch != self.grant.authority_epoch
            || proposal.source.stem_generation.get() != self.generation
            || proposal.access.stem_generation.get() != self.generation
            || !proposal.verified_artifacts.matches_source(proposal.source)
            || proposal.verified_artifacts.authority().grants_any()
        {
            return Err(Error::FeatureContract);
        }
        // The proof had to hash all four physical roles at its creation.
        // Recheck its exact root/inodes now; this is not a loaded-tensor proof.
        proposal
            .cas_verifier
            .verify_pinned_current(proposal.source, proposal.verified_artifacts)
            .map_err(|_| Error::FeatureContract)?;

        let max_active = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if self
            .active_requests
            .len()
            .checked_add(proposal.members.len())
            .ok_or(Error::ArithmeticOverflow)?
            > max_active
        {
            return Err(Error::RequestCapacity);
        }

        // Conservative admission floor: all loaded model handles, distinct
        // output vectors per Head, and one possible local gated scratch per
        // member. A real driver must still report/enforce its actual peak.
        let resident_bytes = self.models.values().try_fold(0_u64, |acc, model| {
            acc.checked_add(model.handle.observed_memory_bytes)
        }).ok_or(Error::ArithmeticOverflow)?;
        let feature_scratch_each = u64::try_from(proposal.feature_vector_q24.len())
            .map_err(|_| Error::ArithmeticOverflow)?
            .checked_mul(8)
            .ok_or(Error::ArithmeticOverflow)?;
        let batch_scratch = feature_scratch_each
            .checked_mul(u64::try_from(proposal.members.len()).map_err(|_| Error::ArithmeticOverflow)?)
            .ok_or(Error::ArithmeticOverflow)?;

        let mut requests = BTreeSet::new();
        let mut reservations = BTreeSet::new();
        let mut selected_heads = BTreeSet::new();
        let mut output_bytes = 0_u64;
        let mut bindings = Vec::with_capacity(proposal.members.len());
        let first_width = proposal.members[0].selected_head.expected_output_width;
        for item in proposal.members {
            if item.authorization.cancelled
                || item.selected_head.expected_output_width != first_width
                || !requests.insert(item.authorization.request_id.as_str())
                || !reservations.insert(item.authorization.reservation_id.as_str())
                || !selected_heads.insert(item.selected_head.head_model_id.as_str())
                || self.active_requests.contains_key(&item.authorization.request_id)
            {
                return Err(Error::FeatureContract);
            }

            let width = u64::try_from(item.selected_head.expected_output_width)
                .map_err(|_| Error::ArithmeticOverflow)?;
            output_bytes = output_bytes
                .checked_add(width.checked_mul(16).ok_or(Error::ArithmeticOverflow)?)
                .ok_or(Error::ArithmeticOverflow)?;

            // Existing single-owner preflight binds physical loaded Head,
            // Scope/Principal, whole Q24 payload, lease, reservation, grant,
            // deadline and exact per-item Final-use signature proposal.
            bindings.push(self.expected_stem_final_use_binding_v1(
                now_ms,
                proposal.source,
                proposal.access,
                item.selected_head.clone(),
                proposal.feature_vector_q24,
                item.authorization,
            )?);
        }
        let minimum_bytes = resident_bytes
            .checked_add(output_bytes)
            .and_then(|value| value.checked_add(batch_scratch))
            .ok_or(Error::ArithmeticOverflow)?;
        if minimum_bytes > self.grant.maximum_memory_bytes {
            return Err(Error::ModelCapacity);
        }
        proposal
            .cas_verifier
            .verify_pinned_current(proposal.source, proposal.verified_artifacts)
            .map_err(|_| Error::FeatureContract)?;

        let mut bytes = b"hepta.infer-worker.stem-batch-proposal.v1".to_vec();
        bytes.extend_from_slice(&self.generation.to_be_bytes());
        bytes.extend_from_slice(&self.grant.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(proposal.source.feature_digest.as_array());
        // Keep this read-only proposal tied to the exact host-selected CAS
        // directory identity; it is still not an artifact-load certificate.
        bytes.extend_from_slice(
            proposal.verified_artifacts.cas_directory_digest().as_array()
        );
        append_field(&mut bytes, proposal.source.scope_id.as_str())?;
        append_field(&mut bytes, proposal.source.principal_id.as_str())?;
        bytes.extend_from_slice(
            &u32::try_from(bindings.len())
                .map_err(|_| Error::ArithmeticOverflow)?
                .to_be_bytes(),
        );
        for (member, binding) in proposal.members.iter().zip(&bindings) {
            append_field(&mut bytes, &member.authorization.request_id)?;
            append_field(&mut bytes, &member.authorization.reservation_id)?;
            append_field(&mut bytes, member.selected_head.head_model_id.as_str())?;
            append_field(&mut bytes, &binding.subject_id)?;
            append_field(&mut bytes, &binding.destination_id)?;
            bytes.extend_from_slice(&binding.request_sha256);
            bytes.extend_from_slice(&binding.scope_sha256);
            bytes.extend_from_slice(&binding.payload_sha256);
        }
        let batch_digest = Digest32::of_bytes(&bytes);
        let group_binding = FinalUseBinding {
            subject_id: proposal.source.principal_id.to_string(),
            destination_id: format!("neuron.stem-batch:{}", proposal.source.stem_model_id),
            request_sha256: Digest32::of_parts(&[
                b"hepta.infer-worker.stem-batch-aggregate.v1",
                batch_digest.as_array(),
            ])
            .into_array(),
            // Every signed Head member already carries this exact source and
            // Scope reference; the group must cover the SAME authenticated
            // Scope, not an attacker-supplied batch grouping.
            scope_sha256: bindings[0].scope_sha256,
            payload_sha256: batch_digest.into_array(),
        };
        Ok(NonAuthorizingStemBatchPlanV1 {
            batch_digest,
            group_binding,
            bindings,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}


impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    /// Testable owner-local building block for an eventual ONE-call native
    /// batch. Not exported to outside crates. No signer or model effect is
    /// created here, and no physical batch backend is installed.
    ///
    /// All original single-use signed tokens are validated before the effect
    /// starts. The outermost authority fence stays active until the whole
    /// synchronous callback finishes, so revocation updates cannot race
    /// with any inner token entry or the effect. A denied member means ZERO
    /// callback invocations. Claimed nonces are never refunded.
    ///
    /// The caller must later wire the effect only to the original Evidence-
    /// journalled batch driver with complete post-effect observations.
    #[cfg(test)]
    pub(crate) fn with_verified_stem_batch_effect_v1<T>(
        &mut self,
        now_ms: u64,
        proposed: StemBatchProposalV1<'_>,
        frozen_plan: &NonAuthorizingStemBatchPlanV1,
        authority: &FinalUseAuthority,
        group_token: VerifiedUseToken,
        tokens: Vec<VerifiedUseToken>,
        effect: impl FnOnce(&mut Self) -> Result<T, Error>,
    ) -> Result<T, Error> {
        if frozen_plan.authority.grants_any()
            || tokens.is_empty()
            || tokens.len() != frozen_plan.bindings.len()
            || tokens.len() > MAX_BATCH_MEMBERS
        {
            return Err(Error::FinalUseDenied);
        }
        // The stale proposal is not admission: revalidate every member,
        // resource budget, source, and CAS physical currentness *now*.
        let current = self.prepare_stem_final_use_batch_proposal_v1(now_ms, proposed)?;
        if current.batch_digest != frozen_plan.batch_digest
            || current.group_binding != frozen_plan.group_binding
            || current.bindings != frozen_plan.bindings
        {
            return Err(Error::FeatureContract);
        }

        // Each token remains owned and non-cloneable; request order is fixed
        // by the preflight plan. A foreign-owner token, revoked token, expired
        // grant or incorrect signed binding rejects before the callback.
        let mut signed_members = Vec::with_capacity(tokens.len() + 1);
        // First enter the group grant so no standalone member token can be
        // interpreted as permission to combine unrelated approved effects.
        signed_members.push((group_token, current.group_binding));
        signed_members.extend(tokens.into_iter().zip(current.bindings));

        // The callback is invoked ONLY from inside all original effect
        // fences. Recheck immutable CAS/current grants after token validation
        // and immediately before a future driver dispatch.
        let run = move || -> Result<T, Error> {
            let fresh = self.prepare_stem_final_use_batch_proposal_v1(now_ms, proposed)?;
            if fresh.batch_digest != frozen_plan.batch_digest
                || fresh.group_binding != frozen_plan.group_binding
                || fresh.bindings != frozen_plan.bindings
            {
                return Err(Error::FeatureContract);
            }
            // If the physical driver returns an unknown result or panics,
            // fence the whole worker generation. A fully rejected admission
            // (above) does not poison a generation that performed no effect.
            let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| effect(self)));
            match outcome {
                Ok(Ok(value)) => Ok(value),
                Ok(Err(error)) => {
                    self.poisoned = true;
                    Err(error)
                }
                Err(panic) => {
                    self.poisoned = true;
                    std::panic::resume_unwind(panic)
                }
            }
        };

        // No new source-visible privileged boundary: the original signed
        // Worker caller owns the multi-token nested final-use effect fence.
        with_verified_stem_batch_tokens_v1(authority, signed_members, Box::new(run))
    }
}

fn append_field(bytes: &mut Vec<u8>, value: &str) -> Result<(), Error> {
    let raw = value.as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| Error::ArithmeticOverflow)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}
