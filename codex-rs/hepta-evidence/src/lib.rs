#![forbid(unsafe_code)]

mod qualification_types;

#[cfg(feature = "runtime")]
mod authbus_outbox;
#[cfg(feature = "runtime")]
mod authbus_outbox_record;
#[cfg(feature = "runtime")]
mod authbus_outbox_worker;
#[cfg(feature = "runtime")]
mod authbus_recovery;
#[cfg(feature = "runtime")]
mod authbus_store;
#[cfg(feature = "runtime")]
mod canonical;
#[cfg(feature = "runtime")]
mod governance_store;
#[cfg(feature = "runtime")]
mod governance_validation;
#[cfg(feature = "runtime")]
mod historical;
#[cfg(feature = "runtime")]
mod provider_claim;
#[cfg(feature = "runtime")]
mod provider_effect_store;
#[cfg(feature = "runtime")]
mod provider_insert;
#[cfg(feature = "runtime")]
mod provider_record;
#[cfg(feature = "runtime")]
mod provider_store;
#[cfg(feature = "runtime")]
mod qualification;
#[cfg(feature = "runtime")]
mod recovery_frontier;
#[cfg(feature = "runtime")]
mod schema_validation;
#[cfg(feature = "runtime")]
mod store;
#[cfg(feature = "runtime")]
mod summary;

#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_ACTIVE_PER_ISSUER;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_ATTEMPTS;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_LEASE_MS;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_PAYLOAD_BYTES;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AUTHBUS_OUTBOX_MAX_ROWS;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AuthBusClaimRequest;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AuthBusDelivery;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AuthBusDeliveryState;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AuthBusDeliveryStatus;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AuthBusLease;
#[cfg(feature = "runtime")]
pub use authbus_outbox_record::AuthBusOutboxError;
#[cfg(feature = "runtime")]
pub use authbus_recovery::AuthBusRecoveryError;
#[cfg(feature = "runtime")]
pub use authbus_recovery::ReplayCheckpoint;
#[cfg(feature = "runtime")]
pub use authbus_store::AuthBusAdmissionError;
#[cfg(feature = "runtime")]
pub use historical::HISTORICAL_EVIDENCE_SCHEMA_VERSION;
#[cfg(feature = "runtime")]
pub use historical::HistoricalEvidenceFamily;
#[cfg(feature = "runtime")]
pub use historical::HistoricalEvidenceRecord;
#[cfg(feature = "runtime")]
pub use historical::HistoricalEvidenceSelector;
#[cfg(feature = "runtime")]
pub use historical::HistoricalEvidenceState;
#[cfg(feature = "runtime")]
pub use historical::historical_record_sha256;
#[cfg(feature = "runtime")]
pub use provider_claim::ProviderBindingState;
#[cfg(feature = "runtime")]
pub use provider_claim::ProviderIntentClaimDisposition;
#[cfg(feature = "runtime")]
pub use provider_effect_store::PROVIDER_EFFECT_QUALIFICATION_EXTERNAL_EFFECTS;
#[cfg(feature = "runtime")]
pub use provider_effect_store::PROVIDER_EFFECT_QUALIFICATION_NAMESPACE;
#[cfg(feature = "runtime")]
pub use provider_effect_store::PROVIDER_EFFECT_QUALIFICATION_PRODUCTION_CALLER;
#[cfg(feature = "runtime")]
pub use provider_effect_store::ProviderEffectQualificationDispatchReceipt;
#[cfg(feature = "runtime")]
pub use provider_effect_store::StoredProviderEffect;
#[cfg(feature = "runtime")]
pub use provider_effect_store::StoredProviderEffectAck;
#[cfg(feature = "runtime")]
pub use provider_effect_store::StoredProviderEffectIntent;
#[cfg(feature = "runtime")]
pub use provider_effect_store::StoredProviderEffectUncertainty;
#[cfg(feature = "runtime")]
pub use provider_store::StoredProviderAttemptEvidence;
#[cfg(feature = "runtime")]
pub use provider_store::StoredProviderIntent;
#[cfg(feature = "runtime")]
pub use provider_store::StoredProviderReceipt;
#[cfg(feature = "runtime")]
pub use qualification::EvidenceCandidateV1;
#[cfg(feature = "runtime")]
pub use qualification::EvidenceIssuerTrustBindingV1;
#[cfg(feature = "runtime")]
pub use qualification::IndependentDecisionReceiptV1;
#[cfg(feature = "runtime")]
pub use qualification::IndependentDecisionRoleV1;
#[cfg(feature = "runtime")]
pub use qualification::IndependentDecisionV1;
#[cfg(feature = "runtime")]
pub use qualification::QUALIFICATION_EVIDENCE_MAX_ASSETS;
#[cfg(feature = "runtime")]
pub use qualification::QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES;
#[cfg(feature = "runtime")]
pub use qualification::QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS;
#[cfg(feature = "runtime")]
pub use qualification::QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES;
#[cfg(feature = "runtime")]
pub use qualification::QUALIFICATION_EVIDENCE_SCHEMA_VERSION;
#[cfg(feature = "runtime")]
pub use qualification::QualificationEvidenceEnvelopeV1;
#[cfg(feature = "runtime")]
pub use qualification::QualificationEvidenceStore;
#[cfg(feature = "runtime")]
pub use qualification::VerifyChainRequestV1;
#[cfg(feature = "runtime")]
pub use qualification::evidence_set_digest;
#[cfg(feature = "runtime")]
pub use qualification::qualification_append_scope_digest;
#[cfg(feature = "runtime")]
pub use qualification::qualification_envelope_bytes;
#[cfg(feature = "runtime")]
pub use qualification::qualification_subject;
pub use qualification_types::EvidenceClaimClassV1;
pub use qualification_types::EvidenceDispositionV1;
pub use qualification_types::EvidenceId;
pub use qualification_types::EvidenceIssuerRoleV1;
pub use qualification_types::EvidenceReceiptKindV1;
pub use qualification_types::EvidenceReferenceV1;
#[cfg(feature = "runtime")]
pub use recovery_frontier::EVIDENCE_DATABASE_LINEAGE;
#[cfg(feature = "runtime")]
pub use recovery_frontier::EvidenceRecoverySnapshotV1;
#[cfg(feature = "runtime")]
pub use store::AppendDisposition;
#[cfg(feature = "runtime")]
pub use store::HeptaEvidenceStore;
#[cfg(feature = "runtime")]
pub use store::StoredActionEvidence;
#[cfg(feature = "runtime")]
pub use store::StoredReceipt;
#[cfg(feature = "runtime")]
pub use summary::EvidenceSummary;
#[cfg(feature = "runtime")]
pub use summary::GovernanceEvidenceSummary;
#[cfg(feature = "runtime")]
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

#[cfg(all(test, feature = "runtime"))]
#[path = "tests.rs"]
#[cfg(feature = "runtime")]
mod tests;

#[cfg(all(test, feature = "runtime"))]
#[path = "provider_tests.rs"]
#[cfg(feature = "runtime")]
mod provider_tests;

#[cfg(all(test, feature = "runtime"))]
#[path = "provider_claim_tests.rs"]
#[cfg(feature = "runtime")]
mod provider_claim_tests;

#[cfg(all(test, feature = "runtime"))]
#[path = "provider_effect_tests.rs"]
#[cfg(feature = "runtime")]
mod provider_effect_tests;

#[cfg(all(test, feature = "runtime"))]
#[path = "summary_tests.rs"]
#[cfg(feature = "runtime")]
mod summary_tests;

#[cfg(all(test, feature = "runtime"))]
#[path = "historical_tests.rs"]
#[cfg(feature = "runtime")]
mod historical_tests;

#[cfg(all(test, feature = "runtime"))]
#[path = "authbus_outbox_tests.rs"]
#[cfg(feature = "runtime")]
mod authbus_outbox_tests;

#[cfg(all(test, feature = "runtime"))]
#[path = "authbus_outbox_quarantine_tests.rs"]
#[cfg(feature = "runtime")]
mod authbus_outbox_quarantine_tests;

#[cfg(all(test, feature = "runtime"))]
#[path = "qualification_tests.rs"]
#[cfg(feature = "runtime")]
mod qualification_tests;
