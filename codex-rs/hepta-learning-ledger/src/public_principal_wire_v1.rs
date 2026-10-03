//! Original public principal transfer only; decoding grants no authority.
use crate::AuthenticatedPrincipalV1;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
type ReviewResult<T> = Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PrincipalWire {
    pub principal_id: String,
    pub credential_chain_digest: String,
    pub signing_key_digest: String,
    pub scope_digest: String,
    pub authority_epoch: u64,
    pub authenticated_at: u64,
    pub expires_at: u64,
}
impl PrincipalWire {
    pub fn from_principal(p: &AuthenticatedPrincipalV1) -> Self {
        Self {
            principal_id: p.principal_id.to_string(),
            credential_chain_digest: p.credential_chain_digest.to_string(),
            signing_key_digest: p.signing_key_digest.to_string(),
            scope_digest: p.scope_digest.to_string(),
            authority_epoch: p.authority_epoch,
            authenticated_at: p.authenticated_at,
            expires_at: p.expires_at,
        }
    }
    pub fn principal(&self) -> ReviewResult<AuthenticatedPrincipalV1> {
        Ok(AuthenticatedPrincipalV1 {
            principal_id: StableId::new(self.principal_id.clone())?,
            credential_chain_digest: self.credential_chain_digest.parse()?,
            signing_key_digest: self.signing_key_digest.parse()?,
            scope_digest: self.scope_digest.parse()?,
            authority_epoch: self.authority_epoch,
            authenticated_at: self.authenticated_at,
            expires_at: self.expires_at,
        })
    }
}
