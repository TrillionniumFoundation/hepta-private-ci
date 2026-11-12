//! DATA from a fresh daemon's completed original Root acceptance exchange.
//! This is not C Finalized history and cannot create or renew a capability.

use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OriginalQ24TerminalAcceptanceDataV1 {
    pub schema: u8,
    pub identity_digest: String,
    pub root_profile: String,
    pub initial: String,
    pub frozen_scope: String,
    pub terminal_head: String,
    pub acceptance: String,
    pub data_cut: String,
}

impl OriginalQ24TerminalAcceptanceDataV1 {
    pub fn validate_data(&self) -> Result<(), String> {
        if self.schema != 1 {
            return Err("unsupported terminal-acceptance DATA schema".into());
        }
        for (field, value) in [
            ("identity_digest", &self.identity_digest),
            ("root_profile", &self.root_profile),
            ("initial", &self.initial),
            ("frozen_scope", &self.frozen_scope),
            ("terminal_head", &self.terminal_head),
            ("acceptance", &self.acceptance),
            ("data_cut", &self.data_cut),
        ] {
            if value.len() != 64
                || !value
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                || value.bytes().all(|byte| byte == b'0')
            {
                return Err(format!("noncanonical terminal-acceptance digest: {field}"));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "q24_terminal_acceptance_tests.rs"]
mod tests;
