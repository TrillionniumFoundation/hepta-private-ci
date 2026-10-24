// Same original canonical Objective claim wrappers for both source roots.
pub(crate) fn objective_payload(
    identity: &AgentdIdentity,
    body: &AuthBusObjectiveBody,
    current_generation: u64,
) -> Result<Vec<u8>, AgentdError> {
    codex_hepta_authority_client::objective_payload(identity, body, current_generation)
        .map_err(objective_claims_error)
}

/// Build the same complete canonical claims through the finite implementation.
/// This supplies no signature, replay admission or effect authority.
pub fn authbus_objective_claims(
    identity: &AgentdIdentity,
    request: &AuthBusObjectiveIngress,
) -> Result<SignedMessageClaims, AgentdError> {
    codex_hepta_authority_client::authbus_objective_claims(identity, request)
        .map_err(objective_claims_error)
}

pub(crate) fn objective_scope(identity: &AgentdIdentity) -> Digest32 {
    codex_hepta_authority_client::objective_scope(identity)
}

fn objective_claims_error(
    error: codex_hepta_authority_client::ObjectiveClaimsError,
) -> AgentdError {
    match error {
        codex_hepta_authority_client::ObjectiveClaimsError::Invalid(message) => {
            AgentdError::Invalid(message)
        }
        codex_hepta_authority_client::ObjectiveClaimsError::Json(error) => AgentdError::Json(error),
    }
}
