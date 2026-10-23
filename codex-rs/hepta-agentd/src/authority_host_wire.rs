//! Closed shared wire values for the protected host and trusted original client.
//! These values are not grants by deserialization. The host/client separately
//! verify the pinned peer, exact registration, live lease, version and bounds.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::HostAuthorityClockProjection;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use serde::Deserialize;
use serde::Serialize;

pub const HOST_AUTHORITY_OBSERVATION_V2: &str = "runtime.authority.observation.v2";
pub const HOST_WRITER_AUTHORIZATION_V1: &str = "runtime.authority.writer_authorization.v1";
const WRITER_SIGNING_DOMAIN: &[u8] = b"hepta:root-authority:production-writer:v1\0";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityObservationRequestV2 {
    pub schema_version: u32,
    pub operation: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityObservationResponseV2 {
    pub schema_version: u32,
    pub operation: String,
    pub authority_epoch: u64,
    pub revocations: FinalUseRevocations,
    pub clock: HostAuthorityClockProjection,
    pub observed_unix_ms: u64,
    pub registered_agent_id: AgentId,
    pub spawn_generation: u64,
    pub writer: HostAuthorityWriterObservationV2,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityWriterObservationV2 {
    pub authority_lease: AuthorityLease,
    /// Actual original registry global revision. It may advance for unrelated
    /// leases: require non-regression, not equality to the installed revision.
    pub store_revision: u64,
    pub authority_lease_sha256: Sha256Digest,
    pub owner_epoch: u64,
    pub local_lease_id: String,
    pub local_lease_generation: u64,
    pub writer_authorization_sha256: Sha256Digest,
}

/// The trusted root registration selects every field. Order is the shared
/// typed signing contract; no arbitrary caller-provided preimage is signed.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostWriterAuthorizationClaimsV1 {
    pub schema_version: u32,
    pub issuer_id: String,
    pub sequence: u64,
    pub registered_agent_id: AgentId,
    pub spawn_generation: u64,
    pub owner_epoch: u64,
    pub local_lease_id: String,
    pub local_lease_generation: u64,
    pub authority_lease: AuthorityLease,
    pub authority_lease_sha256: Sha256Digest,
}

impl HostWriterAuthorizationClaimsV1 {
    /// Domain-separated canonical typed bytes only. This does not verify the
    /// signature, registration, original token, currentness or field validity.
    pub fn signing_bytes(&self) -> serde_json::Result<Vec<u8>> {
        let mut bytes = WRITER_SIGNING_DOMAIN.to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(self)?);
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostSignedWriterAuthorizationV1 {
    pub claims: HostWriterAuthorizationClaimsV1,
    #[serde(deserialize_with = "deserialize_signature")]
    pub signature_hex: String,
}

fn deserialize_signature<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<String, D::Error> {
    let value = String::deserialize(deserializer)?;
    if value.len() != 128
        || !value
            .bytes()
            .all(|byte| matches!(byte,b'0'..=b'9'|b'a'..=b'f'))
    {
        return Err(serde::de::Error::custom(
            "signature must be 128 lowercase hex characters",
        ));
    }
    Ok(value)
}

impl HostSignedWriterAuthorizationV1 {
    /// The original digest of the complete canonical signed proof, including
    /// its exact signature spelling. This hash alone is not authorization.
    pub fn sha256(&self) -> serde_json::Result<Sha256Digest> {
        Ok(Sha256Digest::for_bytes(&serde_json::to_vec(self)?))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostWriterAuthorizationReadRequestV1 {
    pub schema_version: u32,
    pub operation: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostWriterAuthorizationReadResponseV1 {
    pub schema_version: u32,
    pub operation: String,
    pub proof: HostSignedWriterAuthorizationV1,
}

/// The owner and original frontier type are fixed by trusted root registration;
/// no remote initialize, reset, arbitrary namespace or epoch endpoint exists.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "operation", deny_unknown_fields)]
pub enum HostConsumerFrontierRequestV1 {
    #[serde(rename = "runtime.final_use.frontier.load.v1")]
    Load {
        schema_version: u32,
        request_id: u64,
    },
    #[serde(rename = "runtime.final_use.frontier.cas.v1")]
    CompareAndSet {
        schema_version: u32,
        request_id: u64,
        expected: FinalUseFrontier,
        next: FinalUseFrontier,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HostConsumerFrontierStatusV1 {
    Ack,
    Conflict,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostConsumerFrontierResponseV1 {
    pub schema_version: u32,
    pub request_id: u64,
    pub status: HostConsumerFrontierStatusV1,
    pub frontier: Option<FinalUseFrontier>,
}

#[cfg(test)]
#[path = "authority_host_wire_tests.rs"]
mod tests;
