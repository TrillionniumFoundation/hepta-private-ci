//! Bounded read protocol for the existing root-owned resource verifier.
//! Responses describe the current owner record and never create authority.

use serde::Deserialize;
use serde::Serialize;

use crate::FleetExecutionResourceObservationV1;

pub const FLEET_RESOURCE_OBSERVATION_OPERATION: &str = "fleet.resource.observe";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetResourceObservationRequestV1 {
    pub schema_version: u32,
    pub operation: String,
    pub subject_id: String,
    pub execution_id: String,
    /// The original Fleet launch manifest digest, distinct from a CPU body digest.
    pub manifest_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetResourceObservationResponseV1 {
    pub schema_version: u32,
    pub operation: String,
    pub observed_at_ms: u64,
    pub observation: FleetExecutionResourceObservationV1,
}
