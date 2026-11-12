//! Durable publication of the exact qualification produced by the runner.
//!
//! This is a data store, not an evaluator or receipt factory. The host supplies
//! a distinct authorized evidence file, its namespace binding and independently
//! retained recovery minimum. The wrapped original file store retains its OS
//! lock, append/fsync, immutable completion and fail-closed recovery semantics.
//! Namespace admission, directory durability and external anchor retention
//! remain host duties. No precomputed qualification is loaded as an execution.

use std::fs::File;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationDispositionV1;
use crate::LockedFileProductEvaluationExecutionErrorV1;
use crate::LockedFileProductEvaluationExecutionStoreV1;
use crate::MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1;
use crate::ProductEvaluationExecutionAnchorV1;
use crate::ProductEvaluationExecutionClaimV1;
use crate::ProductEvaluationExecutionKeyV1;
use crate::ProductEvaluationExecutionStateV1;
use crate::ProductEvaluationExecutionStoreErrorV1;
use crate::ProductEvaluationExecutionStoreV1;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;

type SinkError = ProductEvidenceSinkErrorV1;
type FileError = LockedFileProductEvaluationExecutionErrorV1;
type StoreError = ProductEvaluationExecutionStoreErrorV1;

/// Owns a separate evidence namespace. There is no constructor accepting an
/// arbitrary store implementation, claimed digest, completed receipt or callback.
pub struct LockedFileProductQualificationEvidenceSinkV1 {
    publication_store: LockedFileProductEvaluationExecutionStoreV1,
    owner_binding: Digest32,
    terminal_uncertainty: bool,
}

impl LockedFileProductQualificationEvidenceSinkV1 {
    pub fn create(file: File, owner_binding: Digest32) -> Result<Self, FileError> {
        let binding = evidence_namespace(owner_binding)?;
        let publication_store =
            LockedFileProductEvaluationExecutionStoreV1::create(file, binding)?;
        Ok(Self {
            publication_store,
            owner_binding,
            terminal_uncertainty: false,
        })
    }

    pub fn recover(
        file: File,
        owner_binding: Digest32,
        minimum: ProductEvaluationExecutionAnchorV1,
    ) -> Result<Self, FileError> {
        let binding = evidence_namespace(owner_binding)?;
        let publication_store =
            LockedFileProductEvaluationExecutionStoreV1::recover(file, binding, minimum)?;
        Ok(Self {
            publication_store,
            owner_binding,
            terminal_uncertainty: false,
        })
    }

    #[must_use]
    pub fn anchor(&self) -> ProductEvaluationExecutionAnchorV1 {
        self.publication_store.anchor()
    }

    /// Read the exact committed data. This does not reconstruct a sealed
    /// ProductQualificationReceiptV1, reauthenticate a role or grant eligibility.
    pub fn readback(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, SinkError> {
        if self.terminal_uncertainty {
            return Err(SinkError::Indeterminate);
        }
        let payload = encode_decision(self.owner_binding, execution_digest, decision)?;
        let key = publication_key(self.owner_binding, execution_digest)?;
        let state = ProductEvaluationExecutionStoreV1::readback(
            &mut self.publication_store,
            &key,
        )
        .map_err(store_error)?;
        match state {
            ProductEvaluationExecutionStateV1::Completed(bytes) if bytes == payload => {
                Ok(publication_digest(&payload))
            }
            ProductEvaluationExecutionStateV1::Completed(_) => Err(SinkError::Rejected),
            ProductEvaluationExecutionStateV1::Pending => {
                self.terminal_uncertainty = true;
                Err(SinkError::Indeterminate)
            }
        }
    }
}

impl ProductQualificationEvidenceSinkV1 for LockedFileProductQualificationEvidenceSinkV1 {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, SinkError> {
        if self.terminal_uncertainty {
            return Err(SinkError::Indeterminate);
        }
        let payload = encode_decision(self.owner_binding, execution_digest, decision)?;
        let key = publication_key(self.owner_binding, execution_digest)?;
        let claim = ProductEvaluationExecutionStoreV1::claim(
            &mut self.publication_store,
            &key,
        )
        .map_err(store_error)?;
        match claim {
            ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Completed(bytes),
            ) => {
                if bytes != payload {
                    return Err(SinkError::Rejected);
                }
            }
            ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Pending,
            ) => {
                self.terminal_uncertainty = true;
                return Err(SinkError::Indeterminate);
            }
            ProductEvaluationExecutionClaimV1::Claimed => {
                if ProductEvaluationExecutionStoreV1::complete(
                    &mut self.publication_store,
                    &key,
                    &payload,
                )
                .is_err()
                {
                    self.terminal_uncertainty = true;
                    return Err(SinkError::Indeterminate);
                }
            }
        }
        // Retain the original store's post-fsync readback and metadata check.
        // Once a claim could exist, failure is terminal, never a fresh retry.
        match ProductEvaluationExecutionStoreV1::readback(
            &mut self.publication_store,
            &key,
        ) {
            Ok(ProductEvaluationExecutionStateV1::Completed(bytes)) if bytes == payload => {
                Ok(publication_digest(&payload))
            }
            Ok(_) | Err(_) => {
                self.terminal_uncertainty = true;
                Err(SinkError::Indeterminate)
            }
        }
    }
}

fn evidence_namespace(owner_binding: Digest32) -> Result<Digest32, FileError> {
    if owner_binding.is_zero() {
        return Err(FileError::Binding);
    }
    Ok(Digest32::of_parts(&[
        b"hepta.product-qualification.evidence-namespace.v1",
        owner_binding.as_array(),
    ]))
}

fn publication_key(
    owner_binding: Digest32,
    execution_digest: Digest32,
) -> Result<ProductEvaluationExecutionKeyV1, SinkError> {
    // One actual execution has one immutable terminal decision. Its evaluation
    // ID is committed in the payload and cannot select another publication key.
    let plan_id = StableId::new(execution_digest.to_string()).map_err(|_| SinkError::Rejected)?;
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id,
        binding_digest: Digest32::of_parts(&[
            b"hepta.product-qualification.evidence-key.v1",
            owner_binding.as_array(),
            execution_digest.as_array(),
        ]),
    })
}

fn encode_decision(
    owner_binding: Digest32,
    execution_digest: Digest32,
    signed: &SignedEvaluationDecisionV1,
) -> Result<Vec<u8>, SinkError> {
    let decision = &signed.decision;
    if owner_binding.is_zero()
        || execution_digest.is_zero()
        || decision.evidence_digest.is_zero()
        || signed.trust_digest.is_zero()
        || signed.authentication_digest.is_zero()
        || decision.authority.grants_any()
        || decision.failed_metrics.len() > 128
    {
        return Err(SinkError::Rejected);
    }
    let mut bytes = b"HPQLEV01".to_vec();
    bytes.extend_from_slice(owner_binding.as_array());
    bytes.extend_from_slice(execution_digest.as_array());
    for id in [
        &decision.evaluation_id,
        &decision.candidate_id,
        &decision.baseline_id,
    ] {
        put_id(&mut bytes, id)?;
    }
    bytes.push(match decision.disposition {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        IndependentEvaluationDispositionV1::Ineligible => 1,
        IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    bytes.extend_from_slice(&(decision.failed_metrics.len() as u32).to_be_bytes());
    for id in &decision.failed_metrics {
        put_id(&mut bytes, id)?;
    }
    for digest in [
        decision.evidence_digest,
        signed.trust_digest,
        signed.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    if bytes.len() > MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 {
        return Err(SinkError::Rejected);
    }
    Ok(bytes)
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), SinkError> {
    let value = id.as_str().as_bytes();
    if value.is_empty() || value.len() > 128 {
        return Err(SinkError::Rejected);
    }
    bytes.extend_from_slice(&(value.len() as u16).to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

fn publication_digest(payload: &[u8]) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.product-qualification.durable-publication.v1",
        payload,
    ])
}

fn store_error(error: StoreError) -> SinkError {
    match error {
        StoreError::Unavailable => SinkError::Unavailable,
        StoreError::Indeterminate | StoreError::Corrupt => SinkError::Indeterminate,
        StoreError::Missing | StoreError::Conflict | StoreError::Rejected => SinkError::Rejected,
    }
}

#[cfg(test)]
#[path = "product_qualification_file_tests.rs"]
mod tests;
