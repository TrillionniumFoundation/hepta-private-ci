//! Objective signing in the issuer service's existing trust domain.
//!
//! This child module reuses its parent's key, installed policy and durable
//! counter. It does not provide OS isolation: the host must keep this service
//! outside the Agentd/renderer trust domain when that isolation is required.

use std::io;

use codex_hepta_contracts::AuthorityFrontierStore;
use ed25519_dalek::Signer;

use super::DeploymentFinalUseIssuer;
use super::STATE_OWNER;
use crate::AgentdIdentity;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::authbus_objective_claims;
use crate::objective_runtime::objective_payload;
use crate::objective_runtime::objective_scope;

impl DeploymentFinalUseIssuer {
    pub const OBJECTIVE_DESTINATION: &'static str = "hepta.authbus.objective";

    /// Sign the original AuthBus claims for the installed subject and scope.
    /// The trusted service supplies the registered host identity; callers supply
    /// only a typed body, never a key, sequence, expiry or arbitrary preimage.
    /// Original host admission still validates the frozen profile, runtime
    /// bundle and current spawn; this signature alone grants no effect access.
    pub fn sign_objective(
        &self,
        identity: &AgentdIdentity,
        body: AuthBusObjectiveBody,
    ) -> io::Result<AuthBusObjectiveIngress> {
        objective_payload(identity, &body, identity.spawn_generation).map_err(io::Error::other)?;
        if identity.spawn_generation == 0 {
            return Err(io::Error::other("Objective requires a registered spawn"));
        }
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        if body.authority_epoch != state.head.authority_epoch {
            return Err(io::Error::other("Objective authority epoch mismatch"));
        }
        let scope = objective_scope(identity);
        let policy = state
            .policies
            .iter()
            .find(|policy| {
                policy.subject_id == identity.agent_id.as_str()
                    && policy.destination_id == Self::OBJECTIVE_DESTINATION
                    && policy.scope_sha256 == *scope.as_array()
            })
            .ok_or_else(|| io::Error::other("Objective route is not installed"))?;
        if !(1..=300_000).contains(&policy.lifetime_ms) {
            return Err(io::Error::other("invalid Objective lifetime"));
        }
        let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
        let mut next = state.clone();
        next.sequence = state
            .sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("issuer counter exhausted"))?;
        let mut request = AuthBusObjectiveIngress {
            issuer_id: state.signer_id.clone(),
            key_epoch: state.head.authority_epoch,
            message_id: format!(
                "{}:objective:{}:{}",
                state.signer_id, state.head.authority_epoch, next.sequence
            ),
            sequence: next.sequence,
            expires_at_ms: now
                .checked_add(policy.lifetime_ms)
                .ok_or_else(|| io::Error::other("issuer clock overflow"))?,
            signature_hex: String::new(),
            body,
        };
        let claims = authbus_objective_claims(identity, &request).map_err(io::Error::other)?;
        self.store
            .compare_and_set(STATE_OWNER, &state, &next)
            .map_err(io::Error::other)?;
        request.signature_hex = self
            .key
            .sign(&claims.signing_bytes())
            .to_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        // Durability I/O may stall. An expired response is discarded, while
        // its reserved sequence remains consumed and can never be reused.
        let after = self.clock.now_unix_ms().map_err(io::Error::other)?;
        if after < now || after >= request.expires_at_ms {
            return Err(io::Error::other("Objective expired during signing"));
        }
        Ok(request)
    }
}

#[cfg(test)]
#[path = "deployment_authbus_tests.rs"]
mod tests;
