//! Current-recipient observation of an already completed original history.
//! Deserializing this DATA never grants access, resumes work or proves receipt
//! verification. The daemon supplies it only from its actual Root capability.

use serde::Deserialize;
use serde::Serialize;

pub const AGENTD_Q24_COMPLETED_HISTORY_CAPABILITY: &str = "q24.original_completed_history";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OriginalQ24CompletedHistoryDataV1 {
    pub schema: u8,
    pub identity_digest: String,
    pub root_profile: String,
    pub initial: String,
    pub frozen_scope: String,
    pub terminal_head: String,
    pub acceptance: String,
    pub current_head: String,
    pub successor_record: String,
    pub successor_cut: String,
}

impl OriginalQ24CompletedHistoryDataV1 {
    /// Validate the bounded canonical wire shape only, never its authority.
    pub fn validate_data(&self) -> Result<(), String> {
        if self.schema != 1 {
            return Err("unsupported completed-history DATA schema".into());
        }
        for (field, value) in [
            ("identity_digest", &self.identity_digest),
            ("root_profile", &self.root_profile),
            ("initial", &self.initial),
            ("frozen_scope", &self.frozen_scope),
            ("terminal_head", &self.terminal_head),
            ("acceptance", &self.acceptance),
            ("current_head", &self.current_head),
            ("successor_record", &self.successor_record),
            ("successor_cut", &self.successor_cut),
        ] {
            if value.len() != 64
                || !value
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                || value.bytes().all(|byte| byte == b'0')
            {
                return Err(format!("noncanonical completed-history digest: {field}"));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "q24_completed_history_tests.rs"]
mod tests;
