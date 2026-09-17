//! Active evidence-resolution boundary for governed plasticity.
//!
//! Opaque digests are not treated as proof. A governed caller must provide an
//! evidence resolver that looks up the owner record and returns a typed receipt
//! bound to the exact plasticity context. This crate validates that receipt and
//! hashes it into the governed admission. The host owns the concrete store and
//! producer-authorization policy; there is intentionally no permissive/no-op
//! implementation in this crate.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, Generation, StableId};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlasticityEvidenceKindV3 {
    UpdateRule,
    Modulator,
    ModulatorBroadcast,
    Eligibility,
    ParameterOpportunity,
}

impl PlasticityEvidenceKindV3 {
    const fn tag(self) -> u8 {
        match self {
            Self::UpdateRule => 0,
            Self::Modulator => 1,
            Self::ModulatorBroadcast => 2,
            Self::Eligibility => 3,
            Self::ParameterOpportunity => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityEvidenceQueryV3 {
    pub kind: PlasticityEvidenceKindV3,
    pub evidence_digest: Digest32,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window_id: StableId,
    pub window_digest: Digest32,
    pub dataset_digest: Digest32,
    pub baseline_generation: Generation,
    pub layer_id: Option<StableId>,
    pub parameter_id: Option<StableId>,
    pub now: u64,
}

/// Typed result returned only after the host resolver has found and authenticated
/// the owner evidence record. The crate re-checks every context field before use.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPlasticityEvidenceV3 {
    pub kind: PlasticityEvidenceKindV3,
    pub evidence_digest: Digest32,
    pub producer_id: StableId,
    pub producer_credential_digest: Digest32,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window_id: StableId,
    pub window_digest: Digest32,
    pub dataset_digest: Digest32,
    pub baseline_generation: Generation,
    pub layer_id: Option<StableId>,
    pub parameter_id: Option<StableId>,
    pub observed_at: u64,
    pub expires_at: u64,
    /// Digest of the authoritative owner/store receipt used by the resolver.
    pub source_receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityEvidencePortErrorV3 {
    Unavailable,
    Missing,
    Unauthorized,
    Stale,
    ContextMismatch,
    InvalidReceipt,
}

impl fmt::Display for PlasticityEvidencePortErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityEvidencePortErrorV3 {}

/// Host adapter for authoritative evidence lookup. Implementations MUST resolve
/// the digest against the owning store, authenticate its producer, and verify
/// freshness/current-context before returning a receipt. Returning data copied
/// from the request without an owner-store lookup violates this contract.
pub trait PlasticityEvidencePortV3 {
    fn verify(
        &self,
        query: &PlasticityEvidenceQueryV3,
    ) -> Result<VerifiedPlasticityEvidenceV3, PlasticityEvidencePortErrorV3>;
}

/// Re-check a host evidence receipt and return its canonical verification digest.
pub fn verify_plasticity_evidence_v3(
    port: &dyn PlasticityEvidencePortV3,
    query: &PlasticityEvidenceQueryV3,
) -> Result<Digest32, PlasticityEvidencePortErrorV3> {
    validate_query(query)?;
    let receipt = port.verify(query)?;
    if receipt.kind != query.kind
        || receipt.evidence_digest != query.evidence_digest
        || receipt.objective_digest != query.objective_digest
        || receipt.selected_artifact_digest != query.selected_artifact_digest
        || receipt.window_id != query.window_id
        || receipt.window_digest != query.window_digest
        || receipt.dataset_digest != query.dataset_digest
        || receipt.baseline_generation != query.baseline_generation
        || receipt.layer_id != query.layer_id
        || receipt.parameter_id != query.parameter_id
    {
        return Err(PlasticityEvidencePortErrorV3::ContextMismatch);
    }
    if receipt.producer_credential_digest.is_zero() || receipt.source_receipt_digest.is_zero() {
        return Err(PlasticityEvidencePortErrorV3::InvalidReceipt);
    }
    if receipt.observed_at > receipt.expires_at
        || query.now < receipt.observed_at
        || query.now > receipt.expires_at
    {
        return Err(PlasticityEvidencePortErrorV3::Stale);
    }

    let mut bytes = b"hepta.plasticity.verified-evidence.v3\0".to_vec();
    bytes.push(receipt.kind.tag());
    bytes.extend_from_slice(receipt.evidence_digest.as_array());
    push_id(&mut bytes, &receipt.producer_id)?;
    bytes.extend_from_slice(receipt.producer_credential_digest.as_array());
    bytes.extend_from_slice(receipt.objective_digest.as_array());
    bytes.extend_from_slice(receipt.selected_artifact_digest.as_array());
    push_id(&mut bytes, &receipt.window_id)?;
    bytes.extend_from_slice(receipt.window_digest.as_array());
    bytes.extend_from_slice(receipt.dataset_digest.as_array());
    bytes.extend_from_slice(&receipt.baseline_generation.get().to_be_bytes());
    push_optional_id(&mut bytes, receipt.layer_id.as_ref())?;
    push_optional_id(&mut bytes, receipt.parameter_id.as_ref())?;
    bytes.extend_from_slice(&receipt.observed_at.to_be_bytes());
    bytes.extend_from_slice(&receipt.expires_at.to_be_bytes());
    bytes.extend_from_slice(receipt.source_receipt_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_query(query: &PlasticityEvidenceQueryV3) -> Result<(), PlasticityEvidencePortErrorV3> {
    if query.evidence_digest.is_zero()
        || query.objective_digest.is_zero()
        || query.selected_artifact_digest.is_zero()
        || query.window_digest.is_zero()
        || query.dataset_digest.is_zero()
        || query.now == 0
    {
        return Err(PlasticityEvidencePortErrorV3::InvalidReceipt);
    }
    match query.kind {
        PlasticityEvidenceKindV3::ParameterOpportunity => {
            if query.layer_id.is_none() || query.parameter_id.is_none() {
                return Err(PlasticityEvidencePortErrorV3::InvalidReceipt);
            }
        }
        _ => {
            if query.layer_id.is_some() || query.parameter_id.is_some() {
                return Err(PlasticityEvidencePortErrorV3::InvalidReceipt);
            }
        }
    }
    Ok(())
}

fn push_optional_id(
    bytes: &mut Vec<u8>,
    value: Option<&StableId>,
) -> Result<(), PlasticityEvidencePortErrorV3> {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value)?;
        }
        None => bytes.push(0),
    }
    Ok(())
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), PlasticityEvidencePortErrorV3> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| PlasticityEvidencePortErrorV3::InvalidReceipt)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct EchoPort;

    impl PlasticityEvidencePortV3 for EchoPort {
        fn verify(
            &self,
            query: &PlasticityEvidenceQueryV3,
        ) -> Result<VerifiedPlasticityEvidenceV3, PlasticityEvidencePortErrorV3> {
            Ok(VerifiedPlasticityEvidenceV3 {
                kind: query.kind,
                evidence_digest: query.evidence_digest,
                producer_id: StableId::new("producer:one").expect("valid id"),
                producer_credential_digest: Digest32::of_bytes(b"credential"),
                objective_digest: query.objective_digest,
                selected_artifact_digest: query.selected_artifact_digest,
                window_id: query.window_id.clone(),
                window_digest: query.window_digest,
                dataset_digest: query.dataset_digest,
                baseline_generation: query.baseline_generation,
                layer_id: query.layer_id.clone(),
                parameter_id: query.parameter_id.clone(),
                observed_at: 9,
                expires_at: 11,
                source_receipt_digest: Digest32::of_bytes(b"owner-receipt"),
            })
        }
    }

    fn query() -> PlasticityEvidenceQueryV3 {
        PlasticityEvidenceQueryV3 {
            kind: PlasticityEvidenceKindV3::UpdateRule,
            evidence_digest: Digest32::of_bytes(b"update-rule"),
            objective_digest: Digest32::of_bytes(b"objective"),
            selected_artifact_digest: Digest32::of_bytes(b"artifact"),
            window_id: StableId::new("window:one").expect("valid id"),
            window_digest: Digest32::of_bytes(b"window"),
            dataset_digest: Digest32::of_bytes(b"dataset"),
            baseline_generation: Generation::new(4).expect("valid generation"),
            layer_id: None,
            parameter_id: None,
            now: 10,
        }
    }

    #[test]
    fn active_evidence_receipt_is_context_bound() {
        let digest = verify_plasticity_evidence_v3(&EchoPort, &query()).expect("verified");
        assert_ne!(digest, Digest32::ZERO);
    }

    struct MismatchedPort;

    impl PlasticityEvidencePortV3 for MismatchedPort {
        fn verify(
            &self,
            query: &PlasticityEvidenceQueryV3,
        ) -> Result<VerifiedPlasticityEvidenceV3, PlasticityEvidencePortErrorV3> {
            let mut receipt = EchoPort.verify(query)?;
            receipt.dataset_digest = Digest32::of_bytes(b"different-dataset");
            Ok(receipt)
        }
    }

    #[test]
    fn active_evidence_rejects_context_substitution() {
        assert_eq!(
            verify_plasticity_evidence_v3(&MismatchedPort, &query()),
            Err(PlasticityEvidencePortErrorV3::ContextMismatch)
        );
    }
}
