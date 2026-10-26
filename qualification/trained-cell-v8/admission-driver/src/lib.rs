//! Host-pinned research admission, with no installed or default study profile.
//! All publication, recovery and serving use the unchanged V7 owner composition.
pub mod admission;
mod census;
mod measurements;
mod payload;
pub mod profile;
pub mod report;
pub use hepta_handoff_recovery_v7::handoff_version;

pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
pub(crate) fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(message.to_owned().into())
    }
}

