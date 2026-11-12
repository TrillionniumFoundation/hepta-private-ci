//! A current proof on the original Candidate connection, after complete pages.
//! Retained bytes are model data only. The host re-reads the same SourceBound
//! owner for every proof, and neither side can create or renew a connection.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCellQ24TrainingCommandContextV1;
use super::candidate_wire;
use crate::OriginalCellQ24CandidateMaterialV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;

const OPERATION: &str = "runtime.learning.original-q24-training.candidate-current.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct Pin {
    pub(super) completion: String,
    pub(super) heads: String,
    pub(super) total: u32,
}

impl Pin {
    pub(super) fn from_heads(completion: String, heads: &[u8]) -> Result<Self, Error> {
        if !(12..=32_780).contains(&heads.len()) {
            return Err(Error::Binding("bounded complete Candidate Current bytes"));
        }
        canonical(&completion)?;
        Ok(Self {
            completion,
            heads: Digest32::of_bytes(heads).to_string(),
            total: heads.len() as u32,
        })
    }
}

/// The old Page request remains byte-for-byte unchanged. The two strict
/// shapes cannot overlap: Current has no page, and Page has no heads or total.
#[derive(Deserialize)]
#[serde(untagged)]
pub(super) enum ReadRequest {
    Page(candidate_wire::Request),
    Current(Request),
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
    pub heads: String,
    pub total: u32,
}

impl Request {
    pub(super) fn new(
        context: &OriginalCellQ24TrainingCommandContextV1,
        binding: Digest32,
        completion: Digest32,
        request_id: u64,
        heads: &[u8],
    ) -> Result<Self, Error> {
        let original = candidate_wire::Request::new(
            context, binding, completion, request_id, /*page*/ 0,
        )?;
        let pin = Pin::from_heads(original.completion, heads)?;
        let request = Self {
            schema: original.schema,
            operation: OPERATION.into(),
            request_id,
            binding: original.binding,
            operation_id: original.operation_id,
            dataset_head: original.dataset_head,
            scope_binding: original.scope_binding,
            actor_id: original.actor_id,
            completion: pin.completion,
            heads: pin.heads,
            total: pin.total,
        };
        request.require_context(context, binding, request_id)?;
        Ok(request)
    }

    pub(super) fn pin(&self) -> Pin {
        Pin {
            completion: self.completion.clone(),
            heads: self.heads.clone(),
            total: self.total,
        }
    }

    pub(super) fn require_context(
        &self,
        context: &OriginalCellQ24TrainingCommandContextV1,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        self.original_context()?
            .require_context(context, binding, request_id)
    }

    pub(super) fn require_initial(
        &self,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        request_id: u64,
    ) -> Result<(), Error> {
        self.original_context()?
            .require_initial(material, request_id)
    }

    fn original_context(&self) -> Result<candidate_wire::Request, Error> {
        if self.operation != OPERATION
            || !(1..=128).contains(&self.request_id)
            || !(12..=32_780).contains(&self.total)
        {
            return Err(Error::Binding(
                "original Candidate Current purpose and bounds",
            ));
        }
        canonical(&self.heads)?;
        Ok(candidate_wire::Request {
            schema: self.schema,
            operation: candidate_wire::OPERATION.into(),
            request_id: self.request_id,
            binding: self.binding.clone(),
            operation_id: self.operation_id.clone(),
            dataset_head: self.dataset_head.clone(),
            scope_binding: self.scope_binding.clone(),
            actor_id: self.actor_id.clone(),
            completion: self.completion.clone(),
            page: 0,
        })
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub request: Request,
    pub result: candidate_wire::MaterialResult,
}

pub(super) fn original_candidate_current_proof_v1(
    request: &Request,
    material: &OriginalCellQ24CandidateMaterialV1,
) -> Result<candidate_wire::MaterialResult, Error> {
    let pin = Pin::from_heads(
        candidate_wire::completion_digest(material.receipt(), material.attestation())?.to_string(),
        material.heads(),
    )?;
    if request.pin() != pin {
        return Err(Error::Binding(
            "same complete original Candidate Current material",
        ));
    }
    Ok(candidate_wire::MaterialResult::Current {
        completion: pin.completion,
        heads: pin.heads,
        total: pin.total,
    })
}

fn canonical(value: &str) -> Result<(), Error> {
    let digest: Digest32 = value
        .parse()
        .map_err(|_| Error::Binding("canonical Candidate Current digest"))?;
    if digest.is_zero() || digest.to_string() != value {
        return Err(Error::Binding("canonical Candidate Current digest"));
    }
    Ok(())
}
