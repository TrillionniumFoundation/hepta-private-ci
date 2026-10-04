//! Complete original candidate/rollback correspondence. This is a factual
//! frontier check; each consumer still verifies its original E1/S3 admission.
use super::*;
use std::collections::BTreeSet;

impl InstalledRoundBundleV1 {
    pub(crate) fn rollback_sources(
        &self,
    ) -> Result<Vec<&PreparedCandidateAdmissionV1>, AgentdError> {
        sources(&self.candidates, &self.rollback, &self.rollbacks)
    }
}

fn sources<'a>(
    candidates: &'a [PreparedCandidateAdmissionV1],
    legacy: &'a PreparedCandidateAdmissionV1,
    rollbacks: &'a [PreparedCandidateAdmissionV1],
) -> Result<Vec<&'a PreparedCandidateAdmissionV1>, AgentdError> {
    let expected: BTreeSet<_> = candidates
        .iter()
        .map(|entry| entry.candidate_id.as_str())
        .collect();
    if !(1..=32).contains(&candidates.len())
        || expected.len() != candidates.len()
        || legacy.candidate_id != candidates[0].candidate_id
    {
        return Err(invalid(
            "original candidate frontier or compatibility pair changed",
        ));
    }
    if rollbacks.is_empty() {
        if candidates.len() != 1 {
            return Err(invalid(
                "every Update requires its own complete rollback admission",
            ));
        }
        return Ok(vec![legacy]);
    }
    let actual: BTreeSet<_> = rollbacks
        .iter()
        .map(|entry| entry.candidate_id.as_str())
        .collect();
    if rollbacks.len() != candidates.len()
        || actual.len() != rollbacks.len()
        || actual != expected
        || rollbacks
            .iter()
            .find(|entry| entry.candidate_id == legacy.candidate_id)
            != Some(legacy)
    {
        return Err(invalid("whole original candidate rollback map changed"));
    }
    Ok(rollbacks.iter().collect())
}

#[cfg(test)]
#[path = "installed_self_iteration_bundle_tests.rs"]
mod tests;
