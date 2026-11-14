//! Closed original-consumer frontier wire shared by root service and client.

use crate::FinalUseFrontier;
use serde::Deserialize;
use serde::Serialize;

/// The owner and original frontier type are fixed by trusted root registration;
/// no remote initialize, reset, arbitrary namespace or epoch endpoint exists.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "operation", deny_unknown_fields)]
pub enum HostConsumerFrontierRequestV1 {
    #[serde(rename = "runtime.final_use.frontier.load.v1")]
    Load {
        schema_version: u32,
        request_id: u64,
    },
    #[serde(rename = "runtime.final_use.frontier.cas.v1")]
    CompareAndSet {
        schema_version: u32,
        request_id: u64,
        expected: FinalUseFrontier,
        next: FinalUseFrontier,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HostConsumerFrontierStatusV1 {
    Ack,
    Conflict,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostConsumerFrontierResponseV1 {
    pub schema_version: u32,
    pub request_id: u64,
    pub status: HostConsumerFrontierStatusV1,
    pub frontier: Option<FinalUseFrontier>,
}

#[cfg(test)]
#[path = "authority_consumer_wire_tests.rs"]
mod tests;
