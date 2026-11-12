//! Historical Q24 is an explicit ordinary profile. All descriptor pairing and
//! conflicting-profile checks run before any inherited descriptor is taken.

use std::ffi::OsString;

use super::Profile;
use super::invalid;
use crate::AgentdError;

pub(super) fn validate(
    profile: Profile,
    ordinary: &[OsString],
    deployment: Option<i32>,
    historical_learning_model_publication_b: &[Option<i32>; 5],
    incompatible: &[Option<i32>],
) -> Result<(), AgentdError> {
    if profile != Profile::PostAQ24 {
        if deployment.is_some() {
            return Err(invalid(
                "post-A deployment requires its explicit Q24 profile",
            ));
        }
        return Ok(());
    }
    if deployment.is_none()
        || historical_learning_model_publication_b
            .iter()
            .any(Option::is_none)
        || incompatible.iter().any(Option::is_some)
    {
        return Err(invalid(
            "post-A Q24 requires original historical, learning, model, publication and independent B handoffs plus its sealed deployment",
        ));
    }
    for flag in [
        "--authbus-trust-file",
        "--authbus-checkpoint-file",
        "--objective-profile-file",
    ] {
        let mut found = ordinary.chunks_exact(2).filter(|pair| pair[0] == flag);
        if found.next().is_none_or(|pair| pair[1].is_empty()) || found.next().is_some() {
            return Err(invalid(format!("post-A Q24 requires exactly one {flag}")));
        }
    }
    for pair in ordinary.chunks_exact(2) {
        if pair[0].to_str().is_some_and(|flag| {
            flag.starts_with("--plasticity-")
                || flag.starts_with("--neuron-generation-")
                || flag.starts_with("--intelligence-authority-")
        }) {
            return Err(invalid("post-A Q24 cannot share another execution profile"));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "production_post_a_q24_cli_tests.rs"]
mod tests;
