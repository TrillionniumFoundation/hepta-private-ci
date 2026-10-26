//! Bounded preparation of the original policy owner before generation exists.
//!
//! Only the original StateRuntime/governance constructor is used. This phase
//! has run/turn identities, but no generation binding, attempt lease or send.

use crate::evidence::Evidence;
use crate::policy::QualificationPolicy;
use anyhow::Result;
use codex_core::config::Config;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde_json::json;
use std::fmt;
use std::future::Future;
use std::time::Duration;
use std::time::Instant;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum BootstrapFailure {
    InvalidAllowance,
    Deadline,
    Setup,
    Evidence,
}

impl fmt::Display for BootstrapFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidAllowance => "qualification policy bootstrap allowance invalid",
            Self::Deadline => "qualification policy bootstrap deadline",
            Self::Setup => "qualification policy bootstrap failed",
            Self::Evidence => "qualification policy bootstrap evidence failed",
        })
    }
}

impl std::error::Error for BootstrapFailure {}

pub(crate) struct Ready<T> {
    pub(crate) owner: T,
    pub(crate) evidence_digest: Digest32,
    pub(crate) elapsed_ms: u128,
}

pub(crate) async fn prepare(
    config: &Config,
    evidence: &Evidence,
    run_id: &StableId,
    turn_id: &StableId,
    maximum_seconds: u64,
) -> Result<Ready<QualificationPolicy>> {
    if !(1..=300).contains(&maximum_seconds) {
        return Err(BootstrapFailure::InvalidAllowance.into());
    }
    let path = evidence.directory().join("provider-policy");
    observe(
        evidence,
        run_id,
        turn_id,
        Duration::from_secs(maximum_seconds),
        QualificationPolicy::bootstrap(config, &path, run_id, turn_id),
    )
    .await
}

async fn observe<T>(
    evidence: &Evidence,
    run_id: &StableId,
    turn_id: &StableId,
    maximum_elapsed: Duration,
    setup: impl Future<Output = Result<T>>,
) -> Result<Ready<T>> {
    let mut record = json!({
        "schema":"hepta-native-policy-bootstrap:v1", "status":"started",
        "run_id":run_id.as_str(), "turn_id":turn_id.as_str(),
        "maximum_owner_setup_ms":maximum_elapsed.as_millis(),
        "generation_binding_created":false, "provider_attempt_admitted":false,
        "provider_transport_invoked":false, "automatic_retry":false,
        "owner":"original_StateRuntime_and_Hepta_governance_Enforce",
    });
    evidence
        .record("policy-bootstrap-started.json", &record)
        .map_err(|_| BootstrapFailure::Evidence)?;
    let started = Instant::now();
    let result = tokio::time::timeout(maximum_elapsed, setup).await;
    let elapsed_ms = started.elapsed().as_millis();
    record["owner_setup_elapsed_ms"] = json!(elapsed_ms);
    record["status"] = json!(match &result {
        Ok(Ok(_)) => "ready",
        Ok(Err(_)) => "failed",
        Err(_) => "deadline",
    });
    // A ready owner cannot escape before the matching private receipt is
    // durable. Setup errors never enter public diagnostics verbatim.
    let evidence_digest = evidence
        .record("policy-bootstrap-result.json", &record)
        .map_err(|_| BootstrapFailure::Evidence)?;
    match result {
        Ok(Ok(owner)) => Ok(Ready {
            owner,
            evidence_digest,
            elapsed_ms,
        }),
        Ok(Err(_)) => Err(BootstrapFailure::Setup.into()),
        Err(_) => Err(BootstrapFailure::Deadline.into()),
    }
}

#[cfg(test)]
#[path = "bootstrap_tests.rs"]
mod tests;
