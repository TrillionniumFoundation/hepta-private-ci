//! Private purpose-specific wire. The request has no material or signing body.

use super::evidence_wire;
use crate::cell_q24_dataset::OriginalCellQ24MaterialWireV1;
use serde::Deserialize;
use serde::Serialize;

pub(super) const OPERATION: &str = "runtime.learning.material.readback.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub scope: String,
    pub operation_id: String,
    pub dataset_head: String,
    pub experience_receipt: String,
    pub dataset_receipt: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub scope: String,
    pub operation_id: String,
    pub dataset_head: String,
    pub experience_receipt: String,
    pub dataset_receipt: String,
    pub material: OriginalCellQ24MaterialWireV1,
    pub experience: evidence_wire::Evidence,
    pub dataset: evidence_wire::Evidence,
}
