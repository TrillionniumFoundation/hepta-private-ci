//! Original Chain task settlement observed alongside exact packet membership.

use serde::Deserialize;
use serde::Serialize;

/// A read-only observation of the existing reserve/receipt/accept transaction
/// path. An accepted task commits bytes; it grants no Hepta installation or
/// execution authority and is not independent evaluation of those bytes.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationAcceptedTaskObservation {
    pub schema_version: u32,
    pub task_id: String,
    pub owner: String,
    pub provider: String,
    pub output_sha256: String,
    pub accept_tx_id: String,
    pub accepted_in_exact_packet: bool,
    pub current_status: String,
}
