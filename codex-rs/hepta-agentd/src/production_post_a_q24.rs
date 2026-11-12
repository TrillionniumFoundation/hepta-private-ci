//! Explicit current-recipient post-A composition. Historical authority comes
//! from the actual Root receipt; descriptor data supplies only original files.

use super::initial_q24::files::OriginalFiles;
use super::*;

#[path = "production_post_a_q24_deployment.rs"]
mod deployment;
#[path = "production_post_a_q24_owners.rs"]
mod owners;

fn refused(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original post-A Q24: {message}"))
}
