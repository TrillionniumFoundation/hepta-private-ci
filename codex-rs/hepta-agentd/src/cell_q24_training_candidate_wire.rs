//! Separate read-only purpose for pages of one original Candidate completion.
//! No action, model bytes, arbitrary range, or signing body is accepted.

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
        })
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

pub(super) struct Session {
    next_page: u8,
    completion: Option<String>,
}

impl Session {
    pub(super) fn new() -> Self {
        Self {
            next_page: 0,
            completion: None,
        }
    }

    pub(super) fn require_request(&self, request: &Request) -> Result<(), Error> {
        if request.page != self.next_page
            || self
                .completion
                .as_ref()
                .is_some_and(|pin| pin != &request.completion)
        {
            return Err(Error::Binding("same Candidate session and next page"));
        }
        Ok(())
    }

    pub(super) fn encode_response(
        &mut self,
        request: Request,
        result: MaterialResult,
    ) -> Result<(Vec<u8>, SessionDisposition), Error> {
        self.require_request(&request)?;
        let disposition = if let MaterialResult::Page {
            offset,
            total,
            heads,
        } = &result
        {
            let bytes = STANDARD_NO_PAD
                .decode(heads)
                .map_err(|_| Error::Binding("original Candidate page encoding"))?;
            let end = (*offset as usize)
                .checked_add(bytes.len())
                .ok_or(Error::Binding("original Candidate page end"))?;
            if !(12..=32_780).contains(&(*total as usize))
                || *offset as usize != usize::from(request.page) * PAGE_BYTES
                || *offset as usize >= *total as usize
                || bytes.len() != PAGE_BYTES.min(*total as usize - *offset as usize)
                || STANDARD_NO_PAD.encode(&bytes) != *heads
                || end > *total as usize
            {
                return Err(Error::Binding("original Candidate page total"));
            }
            self.next_page = if end == *total as usize {
                0
            } else {
                request.page + 1
            };
            self.completion = Some(request.completion.clone());
            SessionDisposition::ContinueReadback
        } else {
            SessionDisposition::CloseReadback
        };
        let bytes = serde_json::to_vec(&Response { request, result })?;
        if bytes.len() > FRAME_BYTES {
            return Err(Error::Binding("existing Candidate frame bound"));
        }
        Ok((bytes, disposition))
    }
}

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
    })
}
