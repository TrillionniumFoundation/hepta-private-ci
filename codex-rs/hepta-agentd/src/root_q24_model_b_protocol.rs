//! Data on the original Model factory lane. Neither serde decoding nor these
//! public pins recreate the native B borrow or the daemon's sole writer.

use serde::Deserialize;
use serde::Serialize;

use crate::authority_host_service::q24_model::FactoryLease;
use crate::authority_host_service::q24_model::Reply;
use crate::cell_q24_model_proposal::RootQ24ModelProjectionDataV1;

pub(crate) const PURPOSE: &str = "runtime.learning.q24-model-proposal.root-b.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Request {
    pub(crate) schema: u8,
    pub(crate) operation: String,
    pub(crate) request_id: u64,
    pub(crate) binding: String,
    pub(crate) original_b: String,
    pub(crate) training_head: String,
    pub(crate) expected: FactoryLease,
    pub(crate) action: Action,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Action {
    Bind {},
    Read {},
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Response {
    pub(crate) schema: u8,
    pub(crate) operation: String,
    pub(crate) request_id: u64,
    pub(crate) binding: String,
    pub(crate) original_b: String,
    pub(crate) reply: Reply,
    pub(crate) projection: RootQ24ModelProjectionDataV1,
}

#[cfg(test)]
#[path = "root_q24_model_b_protocol_tests.rs"]
mod tests;
