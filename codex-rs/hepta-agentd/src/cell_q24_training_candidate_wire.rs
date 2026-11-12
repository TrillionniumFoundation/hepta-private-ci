//! Separate read-only purpose for one original Candidate Begin/Pages/Finish.
//! Only fixed sequential reads enter; no Training effect or signing body does.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCellQ24TrainingCommandContextV1;
use crate::OriginalCellQ24CandidateMaterialV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;

pub(super) const OPERATION: &str = "runtime.learning.original-q24-training.candidate-material.v1";
pub(super) const PAGE_BYTES: usize = 2_048;
pub(super) const MAX_PAGES: usize = 17;
const FRAME_BYTES: usize = 16_384;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Phase {
    Begin,
    Page,
    Finish,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub operation_id: String,
    pub dataset_head: String,
    pub scope_binding: String,
    pub actor_id: String,
    pub completion: String,
    pub page: u8,
    pub transfer: u64,
    pub phase: Phase,
}

impl Request {
    pub(super) fn new(
        context: &OriginalCellQ24TrainingCommandContextV1,
        binding: Digest32,
        completion: Digest32,
        request_id: u64,
        page: usize,
    ) -> Result<Self, Error> {
        if page >= MAX_PAGES {
            return Err(Error::Binding("bounded Candidate page"));
        }
        Ok(Self {
            schema: 1,
            operation: OPERATION.into(),
            request_id,
            binding: binding.to_string(),
            operation_id: context.dataset.request.operation_id.to_string(),
            dataset_head: context.dataset.head_digest.to_string(),
            scope_binding: context.scope.binding().to_string(),
            actor_id: context.dataset.owners.trainer.to_string(),
            completion: completion.to_string(),
            page: page as u8,
            transfer: request_id.checked_sub(page as u64)
                .filter(|first| *first > 0).ok_or(Error::Binding("original Candidate transfer"))?,
            phase: if page == 0 { Phase::Begin } else { Phase::Page },
        })
    }

    pub(super) fn finish(
        context: &OriginalCellQ24TrainingCommandContextV1,
        binding: Digest32,
        completion: Digest32,
        request_id: u64,
        transfer: u64,
    ) -> Result<Self, Error> {
        let mut request = Self::new(context, binding, completion, request_id, 0)?;
        request.transfer = transfer;
        request.phase = Phase::Finish;
        Ok(request)
    }

    pub(super) fn require_context(
        &self,
        context: &OriginalCellQ24TrainingCommandContextV1,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        self.require_common(request_id)?;
        if self.binding != binding.to_string()
            || self.operation_id != context.dataset.request.operation_id.as_str()
            || self.dataset_head != context.dataset.head_digest.to_string()
            || self.scope_binding != context.scope.binding().to_string()
            || self.actor_id != context.dataset.owners.trainer.as_str()
        {
            return Err(Error::Binding("same original Candidate material context"));
        }
        Ok(())
    }

    pub(super) fn require_initial(
        &self,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        request_id: u64,
    ) -> Result<(), Error> {
        self.require_common(request_id)?;
        if self.operation_id != material.initial.request.operation_id.as_str()
            || self.scope_binding != material.scope.binding().to_string()
            || self.actor_id != material.initial.owners.trainer.as_str()
        {
            return Err(Error::Binding("same original Candidate initial context"));
        }
        Ok(())
    }

    fn require_common(&self, request_id: u64) -> Result<(), Error> {
        if self.schema != 1
            || self.operation != OPERATION
            || self.request_id != request_id
            || !(1..=128).contains(&request_id)
            || self.transfer == 0 || self.transfer > request_id
            || usize::from(self.page) >= MAX_PAGES
        {
            return Err(Error::Binding("original Candidate purpose and sequence"));
        }
        for value in [
            &self.binding,
            &self.dataset_head,
            &self.scope_binding,
            &self.completion,
        ] {
            let digest: Digest32 = value
                .parse()
                .map_err(|_| Error::Binding("canonical Candidate binding"))?;
            if digest.is_zero() || digest.to_string() != *value {
                return Err(Error::Binding("canonical Candidate binding"));
            }
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub request: Request,
    pub result: MaterialResult,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum MaterialResult {
    Page {
        offset: u32,
        total: u32,
        heads: String,
        heads_digest: String,
    },
    Finished {
        total: u32,
        heads_digest: String,
    },
    NoCandidate,
    Missing,
    Pending,
    Busy,
    ReadbackRequired,
    Uncertain,
    Unavailable,
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum SessionDisposition {
    ContinueReadback,
    CloseReadback,
}

#[path = "cell_q24_training_candidate_transfer.rs"]
mod transfer;
pub(super) use transfer::Session;

pub(super) fn completion_digest(
    receipt: &LearningIterationReceiptV1,
    attestation: &SignedLearningEvidenceV1,
) -> Result<Digest32, Error> {
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-q24-candidate-completion.v1\0",
        &learning_iteration_receipt_signing_bytes_v1(receipt)?,
        &attestation.signing_bytes(),
        &attestation.signature,
    ]))
}

pub(super) fn original_page(
    request: &Request,
    material: &OriginalCellQ24CandidateMaterialV1,
) -> Result<MaterialResult, Error> {
    if request.completion
        != completion_digest(material.receipt(), material.attestation())?.to_string()
    {
        return Err(Error::Binding(
            "unchanged full original Training receipt and signature",
        ));
    }
    if !matches!(request.phase, Phase::Begin | Phase::Page) {
        return Err(Error::Binding("Candidate data page phase"));
    }
    let bytes = material.heads();
    let offset = usize::from(request.page) * PAGE_BYTES;
    if offset >= bytes.len() {
        return Err(Error::Binding("original Candidate page range"));
    }
    let end = offset.saturating_add(PAGE_BYTES).min(bytes.len());
    Ok(MaterialResult::Page {
        offset: offset as u32,
        total: bytes.len() as u32,
        heads: STANDARD_NO_PAD.encode(&bytes[offset..end]),
        heads_digest: Digest32::of_bytes(bytes).to_string(),
    })
}
