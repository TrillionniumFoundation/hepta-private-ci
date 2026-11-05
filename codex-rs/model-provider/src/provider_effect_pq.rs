//! Versioned contract authentication; dispatch and recovery retain their owners.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;

use super::HttpProviderEffectContractAttestation;
use super::valid_contract_id;

/// The signature profile actually verified for a provider contract.
///
/// Only successful verification can set the private attestation field. A profile
/// value alone grants no dispatch, current-role or FinalUse authority.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HttpProviderEffectAuthenticationProfile {
    ClassicalV1,
    MlDsa65V2,
}

impl HttpProviderEffectContractAttestation {
    pub const PQ_SIGNING_DOMAIN: &'static str = "hepta-provider-effect-attestation-v2";

    /// Exact V2 bytes for pure ML-DSA-65 with the canonical empty context.
    ///
    /// This is a separate signed domain; V1 signatures and statements are never
    /// reinterpreted as PQ. The HTTP contract digest keeps its existing codec.
    pub fn statement_for_pq(
        contract_id: &str,
        contract_sha256: &Sha256Digest,
        authority_epoch: u64,
    ) -> Vec<u8> {
        format!(
            "{}\nauthentication_profile=ml_dsa65_v2\ncontract_id={contract_id}\ncontract_sha256={}\nauthority_epoch={authority_epoch}\n",
            Self::PQ_SIGNING_DOMAIN,
            contract_sha256.as_str(),
        )
        .into_bytes()
    }

    /// Verifies the exact contract under an independently pinned ML-DSA-65 SPKI.
    ///
    /// `expected_key_id` comes from the trusted configuration, not the signature
    /// or candidate key. There is no classical or alternate-provider fallback.
    /// The caller still owns current-role, epoch and revocation admission.
    pub fn verify_pq_signed(
        contract_id: impl Into<String>,
        contract_sha256: Sha256Digest,
        authority_epoch: u64,
        signature: &[u8],
        pinned_spki: &[u8],
        expected_key_id: [u8; 32],
    ) -> Result<Self, String> {
        let contract_id = contract_id.into();
        if !valid_contract_id(&contract_id) {
            return Err("contract_id must be a bounded identifier".to_string());
        }
        if authority_epoch == 0 {
            return Err("authority_epoch must be non-zero".to_string());
        }
        Sha256Digest::parse(contract_sha256.as_str().to_string())
            .map_err(|error| format!("invalid contract digest: {error}"))?;
        let verifier = PqNativeVerifier::from_pinned_spki(pinned_spki, expected_key_id)
            .map_err(|error| format!("invalid pinned ML-DSA-65 key: {error}"))?;
        let statement = Self::statement_for_pq(&contract_id, &contract_sha256, authority_epoch);
        verifier
            .verify_exact_message(&statement, signature)
            .map_err(|_| "provider contract PQ attestation signature mismatch".to_string())?;
        Ok(Self {
            contract_id,
            contract_sha256,
            authority_epoch,
            verified: true,
            authentication_profile: HttpProviderEffectAuthenticationProfile::MlDsa65V2,
        })
    }

    pub fn authentication_profile(&self) -> HttpProviderEffectAuthenticationProfile {
        self.authentication_profile
    }

    /// A verified classical contract must never satisfy a PQ-only host gate.
    pub fn is_pq_verified(&self) -> bool {
        self.verified
            && self.authentication_profile == HttpProviderEffectAuthenticationProfile::MlDsa65V2
    }
}

#[cfg(test)]
#[path = "provider_effect_pq_tests.rs"]
mod tests;
