#![forbid(unsafe_code)]

mod authbus_outbox;
mod authbus_outbox_record;
mod authbus_outbox_worker;
mod authbus_store;
mod canonical;
mod governance_store;
mod governance_validation;
mod historical;
mod provider_claim;
mod provider_effect_store;
mod provider_insert;
mod provider_record;
mod provider_store;
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
pub use store::AppendDisposition;
pub use store::HeptaEvidenceStore;
pub use store::StoredActionEvidence;
pub use store::StoredReceipt;
pub use summary::EvidenceSummary;
pub use summary::GovernanceEvidenceSummary;
pub use summary::ProviderEvidenceSummary;

#[derive(Debug, thiserror::Error)]
pub enum EvidenceError {
    #[error("failed to serialize governance evidence: {0}")]
    Serialization(String),
    #[error("governance evidence backend is unavailable: {0}")]
    Unavailable(String),
    #[error("governance evidence identity conflict for {record_id}")]
    IdempotencyConflict { record_id: String },
    #[error("invalid governance evidence record: {0}")]
    InvalidRecord(String),
    #[error("governance evidence is corrupt: {0}")]
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
#[path = "historical_tests.rs"]
mod historical_tests;

#[cfg(test)]
#[path = "authbus_outbox_tests.rs"]
mod authbus_outbox_tests;
