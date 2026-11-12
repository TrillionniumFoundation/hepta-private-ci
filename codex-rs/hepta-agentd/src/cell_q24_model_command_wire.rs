//! Model requests contain only fixed correlations and a bounded action. Legacy
//! responses keep the original 80-byte record. A private read continuation also
//! transfers the canonical full E body; it cannot import any writable owner.
use super::Error;
use super::OriginalCellQ24ModelCommandReceiptV1;
use super::context::Context;
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

pub(in super::super) const PURPOSE: &str = "runtime.learning.original-q24-model.command.v1";
pub(in super::super) const MATERIAL_MAX_BYTES: usize = 131_072;
pub(in super::super) const MATERIAL_PAGE_BYTES: usize = 8192;
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub(in super::super) enum Action {
    Execute,
    Readback,
    BeginOriginalRead,
    BeginOriginalExecute,
    ReadOriginalPage { transfer: u64, index: u32 },
    FinishOriginalRead { transfer: u64 },
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(in super::super) struct Request {
    pub schema: u8,
    pub purpose: String,
    pub nonce: u64,
    pub context: String,
    pub initial_head: String,
    pub operation_id: String,
    pub actor_id: String,
    pub scope: String,
    pub action: Action,
}
impl Request {
    pub(in super::super) fn new(
        context: &Context,
        nonce: u64,
        action: Action,
    ) -> Result<Self, Error> {
        Ok(Self {
            schema: 1,
            purpose: PURPOSE.into(),
            nonce,
            context: context.binding()?.to_string(),
            initial_head: context.material.initial.head_digest.to_string(),
            operation_id: context.material.initial.request.operation_id.to_string(),
            actor_id: context.material.initial.owners.proposal.to_string(),
            scope: context.material.scope.binding().to_string(),
            action,
        })
    }
    pub(in super::super) fn require_initial(
        &self,
        material: &crate::OriginalCellQ24MaterialReceiptConfigV1,
        nonce: u64,
    ) -> Result<(), Error> {
        let context: Digest32 = self
            .context
            .parse()
            .map_err(|_| Error::Binding("canonical original Model context"))?;
        if self.schema != 1
            || self.purpose != PURPOSE
            || self.nonce != nonce
            || !(1..=128).contains(&nonce)
            || context.is_zero()
            || context.to_string() != self.context
            || self.initial_head != material.initial.head_digest.to_string()
            || self.operation_id != material.initial.request.operation_id.as_str()
            || self.actor_id != material.initial.owners.proposal.as_str()
            || self.scope != material.scope.binding().to_string()
        {
            return Err(Error::Binding("same original Model initial request"));
        }
        Ok(())
    }
    pub(in super::super) fn require_context(
        &self,
        context: &Context,
        nonce: u64,
    ) -> Result<(), Error> {
        self.require_initial(&context.material, nonce)?;
        if self.context != context.binding()?.to_string() {
            return Err(Error::Binding("same actual original D/T/E Model context"));
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(in super::super) struct Response {
    pub request: Request,
    pub outcome: Outcome,
}
#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(in super::super) enum Outcome {
    Completed { record: String },
    OriginalReadStarted { transfer: u64, record: String, total: usize, digest: String },
    OriginalReadPage { transfer: u64, index: u32, offset: usize, total: usize, digest: String, bytes: String },
    OriginalReadFinished { transfer: u64, record: String, total: usize, digest: String },
    Missing,
    Pending,
    Ineligible,
    Busy,
    Expired,
    ReadbackRequired,
    Unavailable,
    Uncertain,
}

pub(in super::super) fn record_bytes(
    context: &Context,
    material: Digest32,
    at: u64,
) -> Result<Vec<u8>, Error> {
    if material.is_zero()
        || at < context.evaluation.receipt().observed_unix_seconds
        || at
            >= context
                .material
                .initial
                .request
                .envelope
                .expiry_unix_seconds
    {
        return Err(Error::Binding("original Model material and recorded time"));
    }
    let mut bytes = b"HQ24PROP".to_vec();
    bytes.extend_from_slice(context.evaluation.snapshot().head_digest.as_array());
    bytes.extend_from_slice(material.as_array());
    bytes.extend_from_slice(&at.to_le_bytes());
    Ok(bytes)
}

pub(in super::super) fn encode_completed(
    context: &Context,
    actual: &crate::CellQ24ModelProposalReceiptV1,
    material: Digest32,
    current: u64,
) -> Result<Outcome, Error> {
    let bytes = record_bytes(
        context,
        material,
        actual.learning_receipt().observed_unix_seconds,
    )?;
    let record = STANDARD_NO_PAD.encode(bytes);
    let checked = decode_completed(context, &record, current)?;
    if checked.receipt() != actual.learning_receipt() {
        return Err(Error::Binding("exact original Model journal result"));
    }
    Ok(Outcome::Completed { record })
}

pub(in super::super) fn decode_completed(
    context: &Context,
    record: &str,
    current: u64,
) -> Result<OriginalCellQ24ModelCommandReceiptV1, Error> {
    let fresh = context.authenticate(current)?;
    context.require_qualified()?;
    if record.len() != 107 {
        return Err(Error::Binding("bounded original Model record"));
    }
    let bytes = STANDARD_NO_PAD
        .decode(record)
        .map_err(|_| Error::Binding("canonical original Model record"))?;
    if bytes.len() != 80 || STANDARD_NO_PAD.encode(&bytes) != record {
        return Err(Error::Binding("canonical original Model record"));
    }
    let material = Digest32::from_array(
        bytes[40..72]
            .try_into()
            .map_err(|_| Error::Binding("Model material"))?,
    );
    let at = u64::from_le_bytes(
        bytes[72..80]
            .try_into()
            .map_err(|_| Error::Binding("Model time"))?,
    );
    if record_bytes(context, material, at)? != bytes || at > fresh {
        return Err(Error::Binding("original Model bytes and time"));
    }
    let composition = Digest32::of_parts(&[b"hepta.cell.q24.model-proposal-receipt.v1\0", &bytes]);
    let mut coordinator =
        LearningIterationCoordinatorV1::from_snapshot(context.evaluation.snapshot().clone())?;
    let candidate = coordinator
        .candidate()
        .ok_or(Error::Binding("actual original Candidate"))?
        .digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    let receipt = LearningIterationReceiptV1 {
        operation_id: context.material.initial.request.operation_id.clone(),
        predecessor: context.evaluation.snapshot().head_digest,
        actor_id: context.material.initial.owners.proposal.clone(),
        evidence_digest: composition,
        observed_unix_seconds: at,
        observation: LearningIterationObservationV1::Proposal {
            candidate_bundle: candidate,
            proposal_id: context.material.initial.request.operation_id.clone(),
            composition_digest: composition,
            disposition: LearningProposalDispositionV1::UpdateCandidates,
        },
    };
    coordinator.record(receipt, at)?;
    context
        .material
        .scope
        .validate_snapshot(coordinator.snapshot())?;
    if coordinator.snapshot().receipts.len() != 5 {
        return Err(Error::Binding("one original Proposal extension"));
    }
    Ok(OriginalCellQ24ModelCommandReceiptV1 {
        snapshot: coordinator.snapshot().clone(),
        material,
        record: bytes
            .try_into()
            .map_err(|_| Error::Binding("complete original Model record"))?,
        context: context.binding()?,
        predecessors: [
            context.dataset.attestations()[0].clone(),
            context.dataset.attestations()[1].clone(),
            context.training.attestation().clone(),
            context.evaluation.attestation().clone(),
        ],
    })
}
