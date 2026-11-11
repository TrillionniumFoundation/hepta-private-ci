//! Source admission for complete Python episodic namespace observations.
//! This is not a writer capability; only the retained native owner may commit it.
use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveScope;
use crate::MemoryVerification;
use crate::ProductionCognitiveMutationError;
use crate::ProductionWriterError;
use crate::SourceDraft;

#[path = "production_episodic_snapshot.rs"]
pub(crate) mod snapshot;
use snapshot::Snapshot;
use snapshot::digest;

/// Original-host admission of a complete, current source namespace.
/// Implementations must authenticate the live source owner, its complete
/// roster and exact observed fact bytes (not an implied whole-document copy).
/// Return the original canonical source observations for those bytes.
/// A checksum or Python provenance fields alone
/// cannot implement this contract. Called before use and again before commit;
/// there is no default implementation or qualification fallback.
pub trait EpisodicSnapshotVerifier: Send + Sync {
    fn verify_current(&self, snapshot_json: &str) -> Result<EpisodicSnapshotAdmission, String>;
}

/// One original-host source observation and its independently chosen native
/// verification state. Source custody alone cannot upgrade a fact to Verified.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EpisodicRecordAdmission {
    pub source: SourceDraft,
    pub verification: MemoryVerification,
}

/// Source payloads admitted by the original host, never deserialized from the
/// import request. Each record maps to its actual canonical source observation.
/// Withdrawing prior facts additionally requires an admitted withdrawal event.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EpisodicSnapshotAdmission {
    pub records: BTreeMap<String, EpisodicRecordAdmission>,
    pub withdrawal: Option<SourceDraft>,
}

/// Persistent association between one Python fact slot and its canonical head.
/// Retired slots remain in the receipt, preventing old snapshot resurrection.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EpisodicMemoryBinding {
    pub source_id: String,
    pub key: String,
    pub version: u64,
    pub record_id: String,
    pub memory_id: String,
    pub memory_revision: u64,
    pub canonical_source_id: String,
    pub canonical_source_revision: u64,
    pub active: bool,
    pub source_admission_sha256: String,
    pub source_content_sha256: String,
    pub mutation_receipt_sha256: String,
    pub mutation_commit_event_id: String,
}

/// Committed bridge state, replayed unchanged after an acknowledgement is lost.
/// Hashes identify source bytes; authority comes from the retained writer and
/// the separately supplied source verifier, not from this serializable receipt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EpisodicImportReceipt {
    pub schema_version: u32,
    pub owner_agent_id: String,
    pub scope_binding: String,
    pub authority_id: String,
    pub namespace: String,
    pub generation: u64,
    pub snapshot_sha256: String,
    pub admission_sha256: String,
    pub lease_id: String,
    pub writer_generation: u64,
    pub bindings: Vec<EpisodicMemoryBinding>,
}


/// A bounded snapshot and source observations admitted by the original host.
/// This object cannot be deserialized or constructed from a digest. Its source
/// verifier remains attached for the required final read linearization check.
pub struct AdmittedEpisodicSnapshot<'a> {
    pub(crate) snapshot: Snapshot,
    pub(crate) admitted: EpisodicSnapshotAdmission,
    pub(crate) admission_sha256: String,
    original: &'a str,
    verifier: &'a dyn EpisodicSnapshotVerifier,
}

impl<'a> AdmittedEpisodicSnapshot<'a> {
    pub fn admit(
        snapshot_json: &'a str,
        scope: &CognitiveScope,
        admission: &'a dyn EpisodicSnapshotVerifier,
    ) -> Result<Self, ProductionCognitiveMutationError> {
        let snapshot = Snapshot::parse(snapshot_json)?;
        let body = &snapshot.body;
        let admitted = admission.verify_current(snapshot_json).map_err(|reason| {
            ProductionWriterError::AuthorityRejected(format!("episodic source: {reason}"))
        })?;
        if admitted.records.len() != body.records.len()
            || body.records.iter().any(|record| !admitted.records.get(&record.record_id)
                .is_some_and(|source| source.source.scope == *scope && source.source.content == record.text.as_bytes()))
            || admitted.withdrawal.as_ref().is_some_and(|source| source.scope != *scope)
        {
            return Err(invalid("admitted source payloads do not exactly bind the complete snapshot"));
        }
        for source in admitted.records.values().map(|admission| &admission.source).chain(admitted.withdrawal.iter()) {
            crate::cognitive_store::validate_key(&source.event_key, "episodic source event key")?;
        }
        if admitted.withdrawal.as_ref().is_some_and(|source| source.content.is_empty()
            || source.content.len() > 256 || std::str::from_utf8(&source.content).is_err())
        {
            return Err(invalid("withdrawal event must contain 1..=256 UTF-8 bytes"));
        }
        let admission_sha256 = digest(&serde_json::to_value(&admitted).map_err(|error| invalid(error.to_string()))?)?;

        Ok(Self {
            snapshot, admitted, admission_sha256,
            original: snapshot_json, verifier: admission,
        })
    }

    /// Rechecks exact source admission; it does not fence a later external use.
    pub fn revalidate(&self) -> Result<(), ProductionCognitiveMutationError> {
        let current = self.verifier.verify_current(self.original)
            .map_err(ProductionWriterError::AuthorityRejected)?;
        if current != self.admitted {
            return Err(invalid("source admission changed before commit"));
        }
        Ok(())
    }
}

pub(crate) fn invalid(message: impl Into<String>) -> ProductionCognitiveMutationError {
    ProductionWriterError::Invalid(message.into()).into()
}

#[cfg(test)]
#[path = "episodic_source_tests.rs"]
mod tests;
