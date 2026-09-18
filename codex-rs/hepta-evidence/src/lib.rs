#![forbid(unsafe_code)]

mod authbus_outbox;
mod authbus_outbox_record;
mod authbus_outbox_worker;
mod authbus_store;
mod canonical;
mod checkpoint;
mod governance_store;
mod governance_validation;
mod historical;
mod provider_claim;
mod provider_effect_store;
mod provider_insert;
mod provider_record;
mod provider_store;
mod qualification;
mod schema_validation;
mod store;
mod summary;

pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_ATTEMPTS;
pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_LEASE_MS;
pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_PAYLOAD_BYTES;
pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_ROWS;
pub use authbus_outbox_record::AuthBusClaimRequest;
pub use authbus_outbox_record::AuthBusDelivery;
pub use authbus_outbox_record::AuthBusDeliveryState;
pub use authbus_outbox_record::AuthBusDeliveryStatus;
pub use authbus_outbox_record::AuthBusLease;
pub use authbus_outbox_record::AuthBusOutboxError;
pub use authbus_store::AuthBusAdmissionError;
pub use checkpoint::EVIDENCE_EXTERNAL_CHECKPOINT_SCHEMA_VERSION;
pub use checkpoint::EvidenceExternalCheckpointV1;
pub use historical::HISTORICAL_EVIDENCE_SCHEMA_VERSION;
pub use historical::HistoricalEvidenceFamily;
pub use historical::HistoricalEvidenceRecord;
pub use historical::HistoricalEvidenceSelector;
pub use historical::HistoricalEvidenceState;
pub use historical::historical_record_sha256;
pub use provider_claim::ProviderBindingState;
pub use provider_claim::ProviderIntentClaimDisposition;
pub use provider_effect_store::PROVIDER_EFFECT_QUALIFICATION_EXTERNAL_EFFECTS;
pub use provider_effect_store::PROVIDER_EFFECT_QUALIFICATION_NAMESPACE;
pub use provider_effect_store::PROVIDER_EFFECT_QUALIFICATION_PRODUCTION_CALLER;
pub use provider_effect_store::ProviderEffectQualificationDispatchReceipt;
pub use provider_effect_store::StoredProviderEffect;
pub use provider_effect_store::StoredProviderEffectAck;
pub use provider_effect_store::StoredProviderEffectIntent;
pub use provider_effect_store::StoredProviderEffectUncertainty;
pub use provider_store::StoredProviderAttemptEvidence;
pub use provider_store::StoredProviderIntent;
pub use provider_store::StoredProviderReceipt;
pub use qualification::AuthenticatedEvidenceIssuerV1;
pub use qualification::EvidenceAssetRefV1;
pub use qualification::EvidenceCandidateV1;
pub use qualification::EvidenceClaimClassV1;
pub use qualification::EvidenceDispositionV1;
pub use qualification::EvidenceId;
pub use qualification::EvidenceIssuerAuthorityV1;
pub use qualification::EvidenceIssuerCertificateV1;
pub use qualification::EvidenceIssuerKeyRevocationV1;
pub use qualification::EvidenceIssuerRevocationsV1;
pub use qualification::EvidenceIssuerRoleV1;
pub use qualification::EvidenceReferenceV1;
pub use qualification::EvidenceTrustRootV1;
pub use qualification::QUALIFICATION_EVIDENCE_MAX_ASSETS;
pub use qualification::QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES;
pub use qualification::QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS;
pub use qualification::QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES;
pub use qualification::QUALIFICATION_EVIDENCE_SCHEMA_VERSION;
pub use qualification::QualificationEvidenceEnvelopeV1;
pub use qualification::SignedEvidenceIssuerCertificateV1;
pub use qualification::SignedEvidenceIssuerKeyRevocationV1;
pub use qualification::SignedQualificationEvidenceEnvelopeV1;
pub use qualification::authenticate_evidence_issuer;
pub use store::AppendDisposition;
pub use store::HeptaEvidenceStore;
pub use store::StoredActionEvidence;
pub use store::StoredReceipt;
pub use summary::EvidenceSummary;
pub use summary::GovernanceEvidenceSummary;
pub use summary::ProviderEvidenceSummary;

#[derive(Debug, thiserror::Error)]
pub enum EvidenceError {
    #[error("failed to serialize evidence: {0}")]
    Serialization(String),
    #[error("evidence backend is unavailable: {0}")]
    Unavailable(String),
    #[error("evidence identity conflict for {record_id}")]
    IdempotencyConflict { record_id: String },
    #[error("invalid evidence record: {0}")]
    InvalidRecord(String),
    #[error("evidence is corrupt: {0}")]
    Corrupt(String),
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;

#[cfg(test)]
#[path = "provider_tests.rs"]
mod provider_tests;

#[cfg(test)]
#[path = "provider_claim_tests.rs"]
mod provider_claim_tests;

#[cfg(test)]
#[path = "provider_effect_tests.rs"]
mod provider_effect_tests;

#[cfg(test)]
#[path = "summary_tests.rs"]
mod summary_tests;

#[cfg(test)]
#[path = "qualification_tests.rs"]
mod qualification_tests;

#[cfg(test)]
#[path = "historical_tests.rs"]
mod historical_tests;

#[cfg(test)]
#[path = "authbus_outbox_tests.rs"]
mod authbus_outbox_tests;

#[cfg(test)]
#[path = "authbus_outbox_quarantine_tests.rs"]
mod authbus_outbox_quarantine_tests;
