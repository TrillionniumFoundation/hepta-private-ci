//! Closed wire contract for an independently operated ordinary model issuer.
//! These proposals and responses are not authority until the kernel verifier
//! claims the signed grant against the exact final-use binding.

use serde::Deserialize;
use serde::Serialize;

use crate::FinalUseBinding;
use crate::FinalUseFrontier;
use crate::FinalUseRevocations;
use crate::SignedFinalUseGrant;

pub const MODEL_ISSUER_SCHEMA_VERSION: u32 = 1;
pub const MODEL_ISSUER_OPERATION: &str = "runtime.codex.turn_start";
pub const MODEL_ISSUER_MAX_REQUEST_BYTES: usize = 16 * 1024;
pub const MODEL_ISSUER_MAX_RESPONSE_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelIssuerRequest {
    pub schema_version: u32,
    pub operation: String,
    pub binding: FinalUseBinding,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelIssuerResponse {
    pub schema_version: u32,
    pub revocations: FinalUseRevocations,
    pub grant: Option<SignedFinalUseGrant>,
    pub denial_reason: Option<String>,
}

/// Published by the root issuer in a protected readable file. The client binds
/// this attestation to Linux SO_PEERCRED and rechecks live start/cgroup/boot.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelIssuerProcessIdentity {
    pub schema_version: u32,
    pub pid: u32,
    pub start_time_ticks: u64,
    pub executable_sha256: String,
    pub cgroup_sha256: String,
    pub boot_id_sha256: String,
}

/// Root-side rollback oracle for one enrolled workload's local nonce owner.
/// The server derives the subject from the Linux peer, not this DTO.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelTrustRequest {
    pub schema_version: u32,
    pub operation: String,
    pub signer_id: String,
    pub expected: Option<FinalUseFrontier>,
    pub next: Option<FinalUseFrontier>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelTrustResponse {
    pub schema_version: u32,
    pub frontier: FinalUseFrontier,
    pub revocations: FinalUseRevocations,
    pub now_unix_ms: u64,
}

pub const MODEL_TRUST_LOAD: &str = "runtime.codex.trust.load";
pub const MODEL_TRUST_CAS: &str = "runtime.codex.trust.cas";
