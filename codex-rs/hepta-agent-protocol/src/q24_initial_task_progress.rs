//! Initial task progress is data from the original live owners. It cannot
//! admit, retry or reconcile work, grant learning authority, or acknowledge a
//! lost ObjectiveStart response on behalf of its original sender.

use serde::Deserialize;
use serde::Serialize;

use crate::ObjectiveAdmissionPublication;
use crate::Q24OriginalTaskObservationV1;

/// Completed means the actual canonical Circuit trace succeeded with no
/// unresolved computation and matches this original Source/Decision read.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Q24OriginalInitialTaskCompletionV1 {
    pub admission: ObjectiveAdmissionPublication,
    pub observation: Q24OriginalTaskObservationV1,
    pub circuit_revision: u64,
    pub circuit_history_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum Q24OriginalInitialTaskProgressV1 {
    /// The original Initial pipeline still has admitted/supervised work.
    /// This is not a promise of completion or a retry/recovery permission.
    InFlight {},
    Completed {
        data: Box<Q24OriginalInitialTaskCompletionV1>,
    },
}
