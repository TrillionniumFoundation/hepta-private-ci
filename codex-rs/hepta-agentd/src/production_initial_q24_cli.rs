//! Pure CLI pairing checks before any original descriptor is taken.

use super::Profile;
use super::invalid;
use crate::AgentdError;
use std::ffi::OsString;

pub(super) fn validate(
    profile: Profile,
    ordinary: &[OsString],
    deployment: Option<i32>,
    initial_handoff: Option<i32>,
    incompatible: &[Option<i32>],
) -> Result<(), AgentdError> {
    if profile != Profile::InitialQ24 {
        if deployment.is_some() {
            return Err(invalid(
                "Initial Q24 deployment requires its explicit profile",
            ));
        }
        return Ok(());
    }
    if deployment.is_none() || initial_handoff.is_none() || incompatible.iter().any(Option::is_some)
    {
        return Err(invalid(
            "Initial Q24 requires only its original Initial handoff and sealed deployment",
        ));
    }
    for flag in [
        "--authbus-trust-file",
        "--authbus-checkpoint-file",
        "--objective-profile-file",
    ] {
        let mut found = ordinary.chunks_exact(2).filter(|pair| pair[0] == flag);
        if found.next().is_none_or(|pair| pair[1].is_empty()) || found.next().is_some() {
            return Err(invalid(format!("Initial Q24 requires exactly one {flag}")));
        }
    }
    for pair in ordinary.chunks_exact(2) {
        if pair[0].to_str().is_some_and(|flag| {
            flag.starts_with("--plasticity-")
                || flag.starts_with("--neuron-generation-")
                || flag.starts_with("--intelligence-authority-")
        }) {
            return Err(invalid(
                "Initial Q24 cannot share another execution profile",
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "production_initial_q24_cli_tests.rs"]
mod tests;
