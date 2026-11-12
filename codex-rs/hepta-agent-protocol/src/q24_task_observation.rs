//! Data read from the original live task for an independent business Observer.
//! It carries neither an Outcome nor authority to sign, freeze, evaluate or use.

use serde::Deserialize;
use serde::Serialize;

pub const AGENTD_Q24_ORIGINAL_TASK_OBSERVATION_CAPABILITY: &str = "q24.original_task_observation";
pub const MAX_Q24_DECISION_PREIMAGE_BYTES: usize = 16_384;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Q24OriginalTaskObservationV1 {
    pub run_id: String,
    pub source_publication_digest: String,
    pub source_history_digest: String,
    pub decision_preimage_hex: String,
    pub decision_sequence: u64,
    pub decision_chain_digest: String,
    pub episode_id: String,
    pub selected_candidate_id: String,
    pub outcome_record_id: String,
    pub outcome_id: String,
    pub unit_profile_digest: String,
    pub expected_delay_profile_digest: String,
    pub observer_principal_id: String,
    pub observer_controller_id: String,
}
