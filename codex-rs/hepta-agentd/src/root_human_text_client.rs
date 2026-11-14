//! Read-only verification over the already held original Root issuer channel.
use super::*;
use crate::AuthBusTextIngress;
use crate::text_session::TextOwnerReceipt;
use codex_hepta_types::Digest32;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Response {
    schema_version: u32,
    operation: String,
    ingress_sha256: String,
    owner: TextOwnerReceipt,
}

impl AgentdUnixFinalUseGrantProvider {
    /// Verify that this exact original text signature was retained atomically
    /// by this Root's authenticated human UI lane. This neither signs text nor
    /// prepares an Objective, issues a grant, renews authority or retries I/O.
    pub fn verify_original_human_text(
        &self,
        ingress: &AuthBusTextIngress,
    ) -> Result<TextOwnerReceipt, AgentdFinalUseIssuerError> {
        if self.protected_root.is_none()
            || ingress.issuer_id.len() > 192
            || ingress.message_id.len() > 192
            || ingress.signature_hex.len() != 128
            || ingress.body.thread_id.len() > 128
            || ingress.body.text.len() > 8192
        {
            return Err(AgentdFinalUseIssuerError::InvalidConfiguration);
        }
        let encoded =
            serde_json::to_vec(ingress).map_err(|_| AgentdFinalUseIssuerError::InvalidGrant)?;
        let digest = Digest32::of_bytes(&encoded).to_string();
        let request = serde_json::to_vec(&serde_json::json!({
            "schema_version":1,
            "operation":"runtime.authbus.human_text.verify.v1",
            "ingress":ingress,
        }))
        .map_err(|_| AgentdFinalUseIssuerError::InvalidGrant)?;
        if request.len() > 32 * 1024 {
            return Err(AgentdFinalUseIssuerError::InvalidGrant);
        }
        self.exchange_guarded(|stream, deadline| {
            let response: Response =
                serde_json::from_slice(&exchange_frame(stream, &request, deadline)?)
                    .map_err(|_| AgentdFinalUseIssuerError::MalformedResponse)?;
            if response.schema_version != 1
                || response.operation != "runtime.authbus.human_text.verified.v1"
                || response.ingress_sha256 != digest
                || !response.owner.validate()
                || response.owner.route.thread_id != ingress.body.thread_id
                || response.owner.route.spawn_generation != ingress.body.spawn_generation
            {
                return Err(AgentdFinalUseIssuerError::MalformedResponse);
            }
            Ok(response.owner)
        })
    }
}
