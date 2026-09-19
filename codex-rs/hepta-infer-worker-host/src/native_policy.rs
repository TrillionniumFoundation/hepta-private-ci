//! Production policy binding for native App Server inference.
//!
//! AuthBus quota/resource records are evidence, never authority by themselves.
//! Physical turn dispatch additionally consumes a kernel-owned signed final-use
//! grant whose binding is constructed from the exact provider request.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::QuotaReservation;
use codex_hepta_contracts::QuotaReservationState;
use codex_hepta_contracts::ResourceAdvertisement;
use codex_hepta_contracts::ResourceAdvertisementState;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseReceipt;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::durable_control::native::NativeAdmissionBinding;
use codex_hepta_infer_core::durable_control::native::NativeFinalUseAuthority;
use codex_hepta_infer_core::durable_control::native::NativeFinalUseWitness;
use codex_hepta_infer_core::durable_control::native::NativePolicyAuthorityWitness;
use codex_hepta_infer_core::durable_control::native::NativeQuotaBinding;
use codex_hepta_infer_core::durable_control::native::NativeResourceBinding;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use sha2::Digest;
use sha2::Sha256;

const MAX_NATIVE_OUTPUT_TOKENS: u64 = 1_000_000;
const MAX_POLICY_AUTH_AGE_MS: u64 = 300_000;

#[derive(Clone, Debug)]
pub struct NativePolicyTrust {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub verifying_key: [u8; 32],
    pub revoked: bool,
}

#[derive(Clone, Debug)]
pub struct NativePolicySignature {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub signature: [u8; 64],
}

#[derive(Clone, Debug)]
struct NativePolicyAuthentication {
    issuer_id: String,
    key_epoch: u64,
    message_id: String,
    sequence: u64,
    expires_at_ms: u64,
    envelope_digest: String,
}

/// Provider admission policy whose quota/resource evidence has already passed
/// strict owner-signature authentication. Fields are deliberately private so
/// production callers cannot manufacture a policy from caller-controlled B2
/// JSON alone.
#[derive(Clone, Debug)]
pub struct NativeExecutionPolicy {
    quota: QuotaReservation,
    resource: ResourceAdvertisement,
    authentication: NativePolicyAuthentication,
}

pub type GrantResolveError = Box<dyn StdError + Send + Sync>;
pub type FinalUseGrantResolver<'a> =
    dyn Fn(&FinalUseBinding) -> Result<SignedFinalUseGrant, GrantResolveError> + Send + Sync + 'a;

pub(crate) struct ClaimedFinalUse {
    pub token: VerifiedUseToken,
    pub binding: FinalUseBinding,
    pub witness: NativeFinalUseWitness,
}

pub(crate) struct AdmittedFinalUse {
    pub receipt: VerifiedUseReceipt,
    pub binding: FinalUseBinding,
    pub witness: NativeFinalUseWitness,
}

#[derive(Debug)]
pub enum NativePolicyError {
    Contract(String),
    Invalid(&'static str),
    Authority(FinalUseError),
    Grant(String),
    Authentication(String),
}

impl fmt::Display for NativePolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NativePolicyError {}

impl From<FinalUseError> for NativePolicyError {
    fn from(value: FinalUseError) -> Self {
        Self::Authority(value)
    }
}

impl NativeExecutionPolicy {
    pub fn authenticate(
        quota: QuotaReservation,
        resource: ResourceAdvertisement,
        trust: &NativePolicyTrust,
        signed: NativePolicySignature,
        now_ms: u64,
    ) -> Result<Self, NativePolicyError> {
        quota
            .validate()
            .map_err(|error| NativePolicyError::Contract(error.to_string()))?;
        resource
            .validate()
            .map_err(|error| NativePolicyError::Contract(error.to_string()))?;
        if quota.resource_sha256 != resource.resource_sha256
            || resource.quota_sha256
                != quota
                    .digest()
                    .map_err(|error| NativePolicyError::Contract(error.to_string()))?
            || quota.subject.generation != quota.generation
            || resource.subject.as_ref() != Some(&quota.subject)
            || resource.generation != quota.generation
            || resource.authority_epoch != quota.authority_epoch
        {
            return Err(NativePolicyError::Invalid(
                "quota/resource authentication binding mismatch",
            ));
        }

        let contract_expiry_ms = quota
            .expires_at_unix_seconds
            .min(resource.expires_at_unix_seconds)
            .checked_mul(1000)
            .ok_or(NativePolicyError::Invalid("policy expiry overflow"))?;
        if signed.expires_at_ms <= now_ms
            || signed.expires_at_ms > contract_expiry_ms
            || signed.expires_at_ms.saturating_sub(now_ms) > MAX_POLICY_AUTH_AGE_MS
        {
            return Err(NativePolicyError::Invalid(
                "policy authentication expiry outside current evidence window",
            ));
        }

        let payload_digest = policy_payload_digest(&quota, &resource)?;
        let scope_digest = policy_scope_digest(&quota, &resource)?;
        let subject_id = StableId::new(quota.subject.agent.clone())
            .map_err(|error| NativePolicyError::Authentication(error.to_string()))?;
        let claims = SignedMessageClaims {
            issuer_id: StableId::new(signed.issuer_id.clone())
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            key_epoch: Generation::new(signed.key_epoch)
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            message_id: StableId::new(signed.message_id.clone())
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            subject_id,
            scope_digest,
            payload_digest,
            sequence: signed.sequence,
            expires_at_ms: signed.expires_at_ms,
        };
        let issuer = IssuerRegistration {
            issuer_id: StableId::new(trust.issuer_id.clone())
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            key_epoch: Generation::new(trust.key_epoch)
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            verifying_key: VerifyingKey::from_bytes(&trust.verifying_key)
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            revoked: trust.revoked,
        };
        let authenticated = SignedMessage {
            claims,
            signature: signed.signature,
        }
        .authenticate(&issuer, scope_digest, payload_digest, now_ms)
        .map_err(|error| NativePolicyError::Authentication(error.to_string()))?;
        if authenticated.receipt().authority.grants_any() {
            return Err(NativePolicyError::Invalid(
                "AuthBus policy authentication must not grant effect authority",
            ));
        }
        let receipt = authenticated.receipt();
        Ok(Self {
            quota,
            resource,
            authentication: NativePolicyAuthentication {
                issuer_id: receipt.issuer_id.to_string(),
                key_epoch: receipt.key_epoch.get(),
                message_id: receipt.message_id.to_string(),
                sequence: receipt.sequence,
                expires_at_ms: signed.expires_at_ms,
                envelope_digest: receipt.envelope_digest.to_string(),
            },
        })
    }

    /// Canonical claims helper for an independent quota/resource owner. The
    /// resulting AuthBus message authenticates a reusable bounded reservation
    /// snapshot; it is not a one-use provider effect grant.
    pub fn signing_claims(
        quota: &QuotaReservation,
        resource: &ResourceAdvertisement,
        issuer_id: &str,
        key_epoch: u64,
        message_id: &str,
        sequence: u64,
        expires_at_ms: u64,
    ) -> Result<SignedMessageClaims, NativePolicyError> {
        Ok(SignedMessageClaims {
            issuer_id: StableId::new(issuer_id.to_string())
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            key_epoch: Generation::new(key_epoch)
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            message_id: StableId::new(message_id.to_string())
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            subject_id: StableId::new(quota.subject.agent.clone())
                .map_err(|error| NativePolicyError::Authentication(error.to_string()))?,
            scope_digest: policy_scope_digest(quota, resource)?,
            payload_digest: policy_payload_digest(quota, resource)?,
            sequence,
            expires_at_ms,
        })
    }

    pub fn admission_binding(
        &self,
        now_unix_seconds: u64,
        agent_id: &str,
        generation: u64,
        model: &str,
        maximum_output_tokens: u64,
        maximum_budget_units: u64,
    ) -> Result<NativeAdmissionBinding, NativePolicyError> {
        self.quota
            .validate()
            .map_err(|error| NativePolicyError::Contract(error.to_string()))?;
        self.resource
            .validate()
            .map_err(|error| NativePolicyError::Contract(error.to_string()))?;

        if maximum_output_tokens == 0 || maximum_output_tokens > MAX_NATIVE_OUTPUT_TOKENS {
            return Err(NativePolicyError::Invalid("maximum output tokens"));
        }
        if maximum_budget_units == 0 {
            return Err(NativePolicyError::Invalid("maximum budget units"));
        }
        if self.quota.state != QuotaReservationState::Held {
            return Err(NativePolicyError::Invalid("quota reservation is not held"));
        }
        if self.resource.state != ResourceAdvertisementState::Available {
            return Err(NativePolicyError::Invalid("resource is not available"));
        }
        if now_unix_seconds < self.quota.not_before_unix_seconds
            || now_unix_seconds >= self.quota.expires_at_unix_seconds
            || now_unix_seconds < self.resource.not_before_unix_seconds
            || now_unix_seconds >= self.resource.expires_at_unix_seconds
        {
            return Err(NativePolicyError::Invalid(
                "policy evidence expired or not yet valid",
            ));
        }
        if generation == 0
            || self.quota.generation != generation
            || self.resource.generation != generation
            || self.quota.subject.generation != generation
            || self.quota.subject.agent != agent_id
            || self.resource.subject.as_ref() != Some(&self.quota.subject)
        {
            return Err(NativePolicyError::Invalid("subject or generation mismatch"));
        }
        if self.resource.model.as_deref() != Some(model) {
            return Err(NativePolicyError::Invalid("resource model mismatch"));
        }
        if self.quota.authority_epoch == 0
            || self.resource.authority_epoch != self.quota.authority_epoch
            || self.quota.reserved_requests == 0
            || self.quota.reserved_concurrency == 0
            || self.quota.reserved_tokens < maximum_output_tokens
            || self.quota.reserved_day_budget < maximum_budget_units
        {
            return Err(NativePolicyError::Invalid(
                "quota/resource authority mismatch",
            ));
        }

        let quota_digest = self
            .quota
            .digest()
            .map_err(|error| NativePolicyError::Contract(error.to_string()))?;
        let resource_digest = self
            .resource
            .digest()
            .map_err(|error| NativePolicyError::Contract(error.to_string()))?;
        if self.quota.resource_sha256 != self.resource.resource_sha256
            || self.resource.quota_sha256 != quota_digest
        {
            return Err(NativePolicyError::Invalid("quota/resource digest mismatch"));
        }

        Ok(NativeAdmissionBinding {
            quota: NativeQuotaBinding {
                reservation_id: self.quota.reservation_id.clone(),
                reservation_digest: quota_digest.as_str().to_string(),
                reserved_requests: self.quota.reserved_requests,
                reserved_tokens: self.quota.reserved_tokens,
                reserved_concurrency: self.quota.reserved_concurrency,
                reserved_day_budget: self.quota.reserved_day_budget,
                authority_epoch: self.quota.authority_epoch,
                expires_at_unix_seconds: self.quota.expires_at_unix_seconds,
            },
            resource: NativeResourceBinding {
                resource_id: self.resource.resource_id.clone(),
                resource_digest: resource_digest.as_str().to_string(),
                provider_id: self.resource.provider_id.clone(),
                model: model.to_string(),
                generation,
                expires_at_unix_seconds: self.resource.expires_at_unix_seconds,
            },
            policy_authority: Some(NativePolicyAuthorityWitness {
                issuer_id: self.authentication.issuer_id.clone(),
                key_epoch: self.authentication.key_epoch,
                message_id: self.authentication.message_id.clone(),
                sequence: self.authentication.sequence,
                expires_at_unix_ms: self.authentication.expires_at_ms,
                envelope_digest: self.authentication.envelope_digest.clone(),
            }),
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn claim_turn(
        &self,
        authority: &FinalUseAuthority,
        resolver: &FinalUseGrantResolver<'_>,
        agent_id: &str,
        generation: u64,
        request_id: &str,
        model: &str,
        model_provider: &str,
        request_payload_digest: &str,
        context_digest: &str,
        maximum_output_tokens: u64,
        maximum_budget_units: u64,
        exact_turn_payload: &[u8],
    ) -> Result<ClaimedFinalUse, NativePolicyError> {
        let admission = self.admission_binding(
            unix_seconds()?,
            agent_id,
            generation,
            model,
            maximum_output_tokens,
            maximum_budget_units,
        )?;
        if admission.resource.provider_id != model_provider {
            return Err(NativePolicyError::Invalid("provider mismatch"));
        }
        let request_sha256 = hash_array(
            &serde_json::to_vec(&(
                "hepta.inference.final-use.request.v1",
                request_id,
                request_payload_digest,
                admission.quota.reservation_digest.as_str(),
                admission.resource.resource_digest.as_str(),
            ))
            .map_err(|_| NativePolicyError::Invalid("request binding encode"))?,
        );
        let scope_sha256 = hash_array(
            &serde_json::to_vec(&(
                "hepta.inference.final-use.scope.v1",
                agent_id,
                generation,
                model,
                model_provider,
                admission.quota.authority_epoch,
                admission.resource.resource_id.as_str(),
                context_digest,
            ))
            .map_err(|_| NativePolicyError::Invalid("scope binding encode"))?,
        );
        let binding = FinalUseBinding {
            subject_id: agent_id.to_string(),
            destination_id: format!("provider:{model_provider}"),
            request_sha256,
            scope_sha256,
            payload_sha256: hash_array(exact_turn_payload),
        };
        let signed =
            resolver(&binding).map_err(|error| NativePolicyError::Grant(error.to_string()))?;
        if signed.grant.authority_epoch != admission.quota.authority_epoch {
            return Err(NativePolicyError::Invalid("grant authority epoch mismatch"));
        }
        let token = authority.claim(&signed, &binding)?;
        let binding_digest = format!(
            "{:x}",
            Sha256::digest(
                serde_json::to_vec(&binding)
                    .map_err(|_| NativePolicyError::Invalid("final-use binding encode"))?
            )
        );
        Ok(ClaimedFinalUse {
            token,
            binding,
            witness: NativeFinalUseWitness {
                grant_id: signed.grant.grant_id,
                authority_epoch: signed.grant.authority_epoch,
                expires_at_unix_ms: signed.grant.expires_at_unix_ms,
                binding_digest,
            },
        })
    }

    pub(crate) fn admit<T>(
        authority: &FinalUseAuthority,
        claimed: ClaimedFinalUse,
        consumer: impl FnOnce() -> T,
    ) -> Result<(T, AdmittedFinalUse), NativePolicyError> {
        let ClaimedFinalUse {
            token,
            binding,
            witness,
        } = claimed;
        let (result, receipt) =
            authority.with_verified_use_receipt(token, &binding, consumer)?;
        Ok((
            result,
            AdmittedFinalUse {
                receipt,
                binding,
                witness,
            },
        ))
    }

    pub(crate) fn finalize(
        authority: &FinalUseAuthority,
        admitted: AdmittedFinalUse,
    ) -> NativeFinalUseAuthority {
        let grant_id = admitted.witness.grant_id.clone();
        let authority_epoch = admitted.witness.authority_epoch;
        match authority.revalidate_used(&admitted.receipt, &admitted.binding) {
            Ok(()) => NativeFinalUseAuthority::VerifiedAtTerminal {
                grant_id,
                authority_epoch,
            },
            Err(error) => NativeFinalUseAuthority::Lost {
                reason: format!("final-use authority revalidation failed: {error}"),
            },
        }
    }
}

fn policy_payload_digest(
    quota: &QuotaReservation,
    resource: &ResourceAdvertisement,
) -> Result<Digest32, NativePolicyError> {
    let payload = serde_json::to_vec(&(
        "hepta.inference.policy-evidence.payload.v1",
        quota,
        resource,
    ))
    .map_err(|_| NativePolicyError::Invalid("policy payload encode"))?;
    Ok(Digest32::of_bytes(&payload))
}

fn policy_scope_digest(
    quota: &QuotaReservation,
    resource: &ResourceAdvertisement,
) -> Result<Digest32, NativePolicyError> {
    let scope = serde_json::to_vec(&(
        "hepta.inference.policy-evidence.scope.v1",
        &quota.subject,
        quota.generation,
        quota.authority_epoch,
        &resource.provider_id,
        &resource.model,
    ))
    .map_err(|_| NativePolicyError::Invalid("policy scope encode"))?;
    Ok(Digest32::of_bytes(&scope))
}

pub(crate) fn claimed_authority(witness: &NativeFinalUseWitness) -> NativeFinalUseAuthority {
    NativeFinalUseAuthority::Claimed {
        grant_id: witness.grant_id.clone(),
        authority_epoch: witness.authority_epoch,
    }
}

fn unix_seconds() -> Result<u64, NativePolicyError> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| NativePolicyError::Invalid("system clock"))
        .map(|duration| duration.as_secs())
}

fn hash_array(bytes: &[u8]) -> [u8; 32] {
    let output = Sha256::digest(bytes);
    let mut digest = [0_u8; 32];
    digest.copy_from_slice(&output);
    digest
}

#[cfg(test)]
#[path = "native_policy_tests.rs"]
mod tests;
