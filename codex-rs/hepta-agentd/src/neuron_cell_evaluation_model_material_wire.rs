//! A single-session readonly transfer. Pages never constitute a capability.
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::Receipt;
use super::super::contract::Context;

const PURPOSE: &str = "runtime.learning.original-cell-evaluation.model-material.readback.v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "read", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Read {
    Begin,
    Page { transfer: u64, index: u32 },
    Finish { transfer: u64, digest: String },
}

#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    schema: u8, purpose: String, pub id: u64, context: String,
    pub read: Read,
}
impl Request {
    pub(super) fn new(id: u64, context: Digest32, read: Read) -> Self {
        Self { schema: 1, purpose: PURPOSE.into(), id, context: context.to_string(), read }
    }
    pub(super) fn require(&self, id: u64, context: Digest32) -> Result<(), Error> {
        if self.schema != 1 || self.purpose != PURPOSE || self.id != id
            || !(1..=128).contains(&id) || self.context != context.to_string()
        { return Err(Error::Binding("fixed original Model material purpose, context and session sequence")); }
        Ok(())
    }
    pub(super) fn context(&self) -> Result<Digest32, Error> {
        self.context.parse().map_err(|_| Error::Binding("original material context"))
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Outcome {
    Page { transfer: u64, index: u32, offset: usize, total: usize, digest: String, bytes: String },
    Completed { transfer: u64, total: usize, digest: String },
    Missing,
    Pending,
    Busy,
    Uncertain,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response { pub request: Request, pub outcome: Outcome }

pub(super) fn binding(context: &Context, evaluation: &Receipt, current: u64) -> Result<Digest32, Error> {
    let actual = super::super::wire::authenticate_completed(
        context, evaluation.snapshot().clone(), evaluation.attestation().clone(), current,
    )?;
    if &actual != evaluation { return Err(Error::Binding("full original T/E material binding")); }
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-evaluation-model-material.v1\0",
        context.binding(current)?.as_array(),
        &learning_iteration_receipt_signing_bytes_v1(evaluation.receipt())?,
        &evaluation.attestation().signing_bytes(), &evaluation.attestation().signature,
    ]))
}

pub(super) fn context_binding(context: &Context, current: u64) -> Result<Digest32, Error> {
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-evaluation-model-material-session.v1\0",
        context.binding(current)?.as_array(),
    ]))
}
