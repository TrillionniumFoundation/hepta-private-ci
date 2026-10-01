//! Current resource observation on the already enrolled model issuer ingress.
//! This route reads the Fleet owner and its external frontier; it never signs,
//! mutates client trust, initializes resource state, or supplies missing grants.

use anyhow::Context;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_fleet::FLEET_RESOURCE_OBSERVATION_OPERATION;
use codex_hepta_fleet::FleetExecutionResourceObservationV1;
use codex_hepta_fleet::FleetResourceObservationRequestV1;
use codex_hepta_fleet::FleetResourceObservationResponseV1;
use serde::Deserialize;

use super::Issuer;
use super::Peer;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceFrontier {
    owner_id: String,
    frontier: AuthorityLeaseFrontier,
}

pub(super) async fn observe(
    issuer: &Issuer,
    request: FleetResourceObservationRequestV1,
    peer: &Peer,
) -> anyhow::Result<FleetResourceObservationResponseV1> {
    let host = issuer
        .config
        .host_principals()?
        .context("resource host is not enrolled")?;
    let path = host
        .resource_authority_frontier
        .context("resource frontier is not enrolled")?;
    let frontier: ResourceFrontier = serde_json::from_slice(&super::read_protected(
        &path, /*maximum*/ 4096, /*private*/ true,
    )?)?;
    anyhow::ensure!(
        frontier.owner_id == "local-supervisor-resources"
            && frontier.frontier.authority_epoch > 0
            && frontier.frontier.state_sha256 != [0; 32],
        "invalid original resource frontier"
    );
    let observation = issuer
        .verifier
        .observe_bound_local_resources(&peer.subject, peer.pid)
        .await?;
    let now = issuer.clock.now_unix_ms()?;
    validate_current(
        &request,
        peer,
        &observation,
        frontier.frontier.authority_epoch,
        now,
    )?;
    // A concurrent epoch transition must not be accepted using the old head.
    let after: ResourceFrontier = serde_json::from_slice(&super::read_protected(
        &path, /*maximum*/ 4096, /*private*/ true,
    )?)?;
    anyhow::ensure!(
        after.owner_id == frontier.owner_id
            && after.frontier.authority_epoch == frontier.frontier.authority_epoch,
        "resource authority epoch changed during observation"
    );
    Ok(FleetResourceObservationResponseV1 {
        schema_version: 1,
        operation: FLEET_RESOURCE_OBSERVATION_OPERATION.into(),
        observed_at_ms: now,
        observation,
    })
}

fn validate_current(
    request: &FleetResourceObservationRequestV1,
    peer: &Peer,
    observation: &FleetExecutionResourceObservationV1,
    authority_epoch: u64,
    now: u64,
) -> anyhow::Result<()> {
    let context = &observation.context;
    anyhow::ensure!(
        request.schema_version == 1
            && request.operation == FLEET_RESOURCE_OBSERVATION_OPERATION
            && request.subject_id == peer.subject
            && request.subject_id == context.principal_id
            && request.execution_id == context.execution_id
            && request.manifest_digest == context.manifest_digest
            && observation.process_id == peer.pid
            && observation.process_start_ticks == peer.start_ticks,
        "resource request differs from the enrolled execution witness"
    );
    let grant = observation
        .allocation
        .as_ref()
        .context("resource allocation is no longer active")?;
    anyhow::ensure!(
        !grant.revoked && grant.expires_at_ms > now && grant.authority_epoch == authority_epoch,
        "resource allocation is expired, revoked, or from another authority epoch"
    );
    Ok(())
}

#[cfg(test)]
#[path = "local_model_resources_tests.rs"]
mod tests;
