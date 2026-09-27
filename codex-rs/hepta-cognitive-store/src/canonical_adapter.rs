//! Canonical V1 adapter for the existing authenticated V2 store writer.
//!
//! The adapter does not create a second writer. It invokes the existing
//! `append_admitted` authority/fence/snapshot path, upgrades the compatibility
//! receipt into the fully bound canonical receipt, verifies closed-registry
//! round-trip decoding, and emits a semantic shadow-equivalence receipt.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::consumer::CognitiveConsumerV1;
use codex_hepta_cognitive_types::consumer::ConsumerConvergenceErrorV1;
use codex_hepta_cognitive_types::consumer::SchemaFlowV1;
use codex_hepta_cognitive_types::consumer::ShadowComparisonReceiptV1;
use codex_hepta_cognitive_types::consumer::decode_registered_for_consumer_v1;
use codex_hepta_cognitive_types::contract::Validated;
use codex_hepta_cognitive_types::lane_c::MemoryAdmissionCandidateV1;
use codex_hepta_cognitive_types::lane_c::MemoryWriteDisposition as LegacyMemoryWriteDisposition;
use codex_hepta_cognitive_types::lane_c::MemoryWriteIntentV1 as LegacyMemoryWriteIntentV1;
use codex_hepta_cognitive_types::lane_c::MemoryWriteReceiptV1 as LegacyMemoryWriteReceiptV1;
use codex_hepta_cognitive_types::wire::CognitiveWireError;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteCommitDispositionV1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteOutcomeV1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteReceiptErrorV1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteReceiptV1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteRejectionCodeV1;
use codex_hepta_types::Digest32;

use crate::AdmittedCognitiveStoreV2;
use crate::CognitiveStoreV2Error;
use crate::StoreAuthorityVerifierV2;

const STORE_SHADOW_DOMAIN_V1: &[u8] =
    b"hepta.cognitive-store.canonical-write-equivalence.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalMemoryWriteV1 {
    pub compatibility_receipt: LegacyMemoryWriteReceiptV1,
    pub canonical_receipt: MemoryWriteReceiptV1,
    pub canonical_wire: Vec<u8>,
    pub shadow_receipt: ShadowComparisonReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalMemoryWriteRejectionV1 {
    pub canonical_receipt: MemoryWriteReceiptV1,
    pub canonical_wire: Vec<u8>,
}

#[derive(Debug)]
pub enum CanonicalStoreAdapterErrorV1 {
    Store(CognitiveStoreV2Error),
    Receipt(MemoryWriteReceiptErrorV1),
    Wire(CognitiveWireError),
    Consumer(ConsumerConvergenceErrorV1),
    CompatibilityContract(String),
    NonCommittedOutcome,
    SemanticMismatch,
}

impl fmt::Display for CanonicalStoreAdapterErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalStoreAdapterErrorV1 {}

pub trait CanonicalCognitiveStoreV1Ext {
    fn append_admitted_canonical<V: StoreAuthorityVerifierV2>(
        &mut self,
        verifier: &V,
        candidate: MemoryAdmissionCandidateV1,
        intent: LegacyMemoryWriteIntentV1,
        writer_id: impl Into<String>,
        issued_at_unix_ms: u64,
    ) -> Result<CanonicalMemoryWriteV1, CanonicalStoreAdapterErrorV1>;
}

impl CanonicalCognitiveStoreV1Ext for AdmittedCognitiveStoreV2 {
    fn append_admitted_canonical<V: StoreAuthorityVerifierV2>(
        &mut self,
        verifier: &V,
        candidate: MemoryAdmissionCandidateV1,
        intent: LegacyMemoryWriteIntentV1,
        writer_id: impl Into<String>,
        issued_at_unix_ms: u64,
    ) -> Result<CanonicalMemoryWriteV1, CanonicalStoreAdapterErrorV1> {
        let compatibility_receipt = self
            .append_admitted(verifier, candidate, intent.clone())
            .map_err(CanonicalStoreAdapterErrorV1::Store)?;
        let canonical_receipt = MemoryWriteReceiptV1::from_legacy_committed(
            &intent,
            writer_id,
            issued_at_unix_ms,
            &compatibility_receipt,
        )
        .map_err(CanonicalStoreAdapterErrorV1::Receipt)?;
        let canonical_wire = Validated::from_cognitive_contract(canonical_receipt.clone())
            .map_err(CanonicalStoreAdapterErrorV1::Wire)?
            .encode_wire_v1()
            .map_err(CanonicalStoreAdapterErrorV1::Wire)?;
        let decoded = decode_registered_for_consumer_v1::<MemoryWriteReceiptV1>(
            CognitiveConsumerV1::CognitiveStore,
            SchemaFlowV1::Output,
            &canonical_wire,
        )
        .map_err(CanonicalStoreAdapterErrorV1::Consumer)?;
        if decoded.as_ref() != &canonical_receipt {
            return Err(CanonicalStoreAdapterErrorV1::SemanticMismatch);
        }

        let compatibility_digest = compatibility_semantic_digest_v1(&compatibility_receipt)
            .ok_or(CanonicalStoreAdapterErrorV1::NonCommittedOutcome)?;
        let canonical_digest = canonical_semantic_digest_v1(&canonical_receipt)
            .ok_or(CanonicalStoreAdapterErrorV1::NonCommittedOutcome)?;
        let shadow_receipt = ShadowComparisonReceiptV1::new(
            intent.intent_id.clone(),
            CognitiveConsumerV1::CognitiveStore,
            Some(compatibility_digest),
            Some(canonical_digest),
            issued_at_unix_ms,
        )
        .map_err(CanonicalStoreAdapterErrorV1::Consumer)?;
        if !shadow_receipt.cutover_eligible() {
            return Err(CanonicalStoreAdapterErrorV1::SemanticMismatch);
        }

        Ok(CanonicalMemoryWriteV1 {
            compatibility_receipt,
            canonical_receipt,
            canonical_wire,
            shadow_receipt,
        })
    }
}

pub fn canonical_rejection_v1(
    intent: &LegacyMemoryWriteIntentV1,
    writer_id: impl Into<String>,
    issued_at_unix_ms: u64,
    rejection_code: MemoryWriteRejectionCodeV1,
    observed_snapshot_digest: Option<Digest32>,
    retryable: bool,
) -> Result<CanonicalMemoryWriteRejectionV1, CanonicalStoreAdapterErrorV1> {
    let canonical_receipt = MemoryWriteReceiptV1::rejected(
        intent,
        writer_id,
        issued_at_unix_ms,
        rejection_code,
        observed_snapshot_digest,
        retryable,
    )
    .map_err(CanonicalStoreAdapterErrorV1::Receipt)?;
    let canonical_wire = Validated::from_cognitive_contract(canonical_receipt.clone())
        .map_err(CanonicalStoreAdapterErrorV1::Wire)?
        .encode_wire_v1()
        .map_err(CanonicalStoreAdapterErrorV1::Wire)?;
    decode_registered_for_consumer_v1::<MemoryWriteReceiptV1>(
        CognitiveConsumerV1::CognitiveStore,
        SchemaFlowV1::Output,
        &canonical_wire,
    )
    .map_err(CanonicalStoreAdapterErrorV1::Consumer)?;
    Ok(CanonicalMemoryWriteRejectionV1 {
        canonical_receipt,
        canonical_wire,
    })
}

impl CanonicalMemoryWriteV1 {
    pub fn validate(&self) -> Result<(), CanonicalStoreAdapterErrorV1> {
        self.compatibility_receipt
            .validate()
            .map_err(|error| {
                CanonicalStoreAdapterErrorV1::CompatibilityContract(error.to_string())
            })?;
        self.canonical_receipt
            .validate()
            .map_err(CanonicalStoreAdapterErrorV1::Receipt)?;
        self.shadow_receipt
            .validate()
            .map_err(CanonicalStoreAdapterErrorV1::Consumer)?;
        if !self.shadow_receipt.cutover_eligible() {
            return Err(CanonicalStoreAdapterErrorV1::SemanticMismatch);
        }
        let decoded = decode_registered_for_consumer_v1::<MemoryWriteReceiptV1>(
            CognitiveConsumerV1::CognitiveStore,
            SchemaFlowV1::Output,
            &self.canonical_wire,
        )
        .map_err(CanonicalStoreAdapterErrorV1::Consumer)?;
        if decoded.as_ref() != &self.canonical_receipt {
            return Err(CanonicalStoreAdapterErrorV1::SemanticMismatch);
        }
        let compatibility_digest = compatibility_semantic_digest_v1(
            &self.compatibility_receipt,
        )
        .ok_or(CanonicalStoreAdapterErrorV1::NonCommittedOutcome)?;
        let canonical_digest = canonical_semantic_digest_v1(&self.canonical_receipt)
            .ok_or(CanonicalStoreAdapterErrorV1::NonCommittedOutcome)?;
        if compatibility_digest != canonical_digest {
            return Err(CanonicalStoreAdapterErrorV1::SemanticMismatch);
        }
        Ok(())
    }
}

impl CanonicalMemoryWriteRejectionV1 {
    pub fn validate(&self) -> Result<(), CanonicalStoreAdapterErrorV1> {
        self.canonical_receipt
            .validate()
            .map_err(CanonicalStoreAdapterErrorV1::Receipt)?;
        if !matches!(
            self.canonical_receipt.outcome(),
            MemoryWriteOutcomeV1::Rejected { .. }
        ) {
            return Err(CanonicalStoreAdapterErrorV1::NonCommittedOutcome);
        }
        let decoded = decode_registered_for_consumer_v1::<MemoryWriteReceiptV1>(
            CognitiveConsumerV1::CognitiveStore,
            SchemaFlowV1::Output,
            &self.canonical_wire,
        )
        .map_err(CanonicalStoreAdapterErrorV1::Consumer)?;
        if decoded.as_ref() != &self.canonical_receipt {
            return Err(CanonicalStoreAdapterErrorV1::SemanticMismatch);
        }
        Ok(())
    }
}

fn compatibility_semantic_digest_v1(
    receipt: &LegacyMemoryWriteReceiptV1,
) -> Option<Digest32> {
    let disposition = match receipt.disposition {
        LegacyMemoryWriteDisposition::Inserted => MemoryWriteCommitDispositionV1::Inserted,
        LegacyMemoryWriteDisposition::Unchanged => MemoryWriteCommitDispositionV1::Unchanged,
        LegacyMemoryWriteDisposition::Rejected => return None,
    };
    Some(commit_semantic_digest_v1(
        receipt.intent_id.as_str(),
        receipt.record_id.as_str(),
        receipt.record_digest,
        receipt.committed_frontier,
        receipt.snapshot_key.vector_digest,
        disposition,
    ))
}

fn canonical_semantic_digest_v1(receipt: &MemoryWriteReceiptV1) -> Option<Digest32> {
    let MemoryWriteOutcomeV1::Committed {
        record_id,
        record_digest,
        committed_memory_frontier,
        committed_snapshot_digest,
        disposition,
    } = receipt.outcome()
    else {
        return None;
    };
    Some(commit_semantic_digest_v1(
        receipt.intent_id().as_str(),
        record_id.as_str(),
        record_digest.digest(),
        *committed_memory_frontier,
        committed_snapshot_digest.digest(),
        *disposition,
    ))
}

fn commit_semantic_digest_v1(
    intent_id: &str,
    record_id: &str,
    record_digest: Digest32,
    committed_frontier: u64,
    snapshot_digest: Digest32,
    disposition: MemoryWriteCommitDispositionV1,
) -> Digest32 {
    let mut bytes = STORE_SHADOW_DOMAIN_V1.to_vec();
    push_text(&mut bytes, intent_id);
    push_text(&mut bytes, record_id);
    bytes.extend_from_slice(record_digest.as_array());
    bytes.extend_from_slice(&committed_frontier.to_be_bytes());
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.push(match disposition {
        MemoryWriteCommitDispositionV1::Inserted => 0,
        MemoryWriteCommitDispositionV1::Unchanged => 1,
    });
    Digest32::of_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u64::try_from(value.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}
