use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;

#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PlatformAction {
    OpenPath,
    RevealPath,
    CopyText,
    Notify,
}

impl PlatformAction {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::OpenPath => "open_path",
            Self::RevealPath => "reveal_path",
            Self::CopyText => "copy_text",
            Self::Notify => "notify",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PlatformPayload {
    Path { path: PathBuf },
    Text { text: String },
    Notification { title: String, body: String },
}

#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OperationKey {
    pub session_id: String,
    pub session_generation: u64,
    pub operation_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DecisionStatus {
    Rejected,
    Indeterminate,
    Succeeded,
    Failed,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PlatformDecision {
    pub schema: String,
    pub key: OperationKey,
    pub action: PlatformAction,
    pub status: DecisionStatus,
    pub terminal_observed: bool,
    pub outcome_digest: Option<String>,
    pub authority_granted: bool,
    pub filesystem_authority: bool,
    pub notification_authority: bool,
    pub update_authority: bool,
}

impl PlatformDecision {
    pub fn new(
        key: OperationKey,
        action: PlatformAction,
        status: DecisionStatus,
        terminal_observed: bool,
        outcome_digest: Option<String>,
    ) -> Self {
        Self {
            schema: "hepta.native.platform-decision.v1".to_string(),
            key,
            action,
            status,
            terminal_observed,
            outcome_digest,
            authority_granted: false,
            filesystem_authority: false,
            notification_authority: false,
            update_authority: false,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeManifest {
    pub endpoint: String,
    pub endpoint_id: String,
    pub manifest_digest: String,
    pub protocol_version: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeSession {
    pub endpoint_id: String,
    pub manifest_digest: String,
    pub protocol_version: u32,
    pub session_id: String,
    pub generation: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeView {
    pub session_id: String,
    pub session_generation: u64,
    pub generation: u64,
    pub revision: u64,
    pub digest: String,
    pub modules: Vec<String>,
    pub body: Value,
    pub stale: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GrantBinding {
    pub session_id: String,
    pub session_generation: u64,
    pub operation_id: String,
    pub action: PlatformAction,
    pub resource_digest: String,
    pub payload_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PlatformGrant {
    pub schema_version: u32,
    pub signer_id: String,
    pub key_id: String,
    pub grant_id: String,
    pub nonce: String,
    pub binding: GrantBinding,
    pub not_before_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedPlatformGrant {
    pub grant: PlatformGrant,
    pub signature_b64: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UpdateManifest {
    pub schema_version: u32,
    pub key_id: String,
    pub version: String,
    pub channel: String,
    pub platform: String,
    pub architecture: String,
    pub package_sha256: String,
    pub predecessor_sha256: String,
    pub backend_protocol_version: u32,
    pub selected_by: String,
    pub generator_principal: String,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedUpdateManifest {
    pub manifest: UpdateManifest,
    pub signature_b64: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct StagedUpdate {
    pub manifest: SignedUpdateManifest,
    pub staged_path: PathBuf,
    pub staged_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UpdateRequest {
    pub schema: String,
    pub parent_pid: u32,
    pub signed_manifest: SignedUpdateManifest,
    pub staged_path: PathBuf,
    pub target_path: PathBuf,
    pub backup_path: PathBuf,
    pub ready_marker: PathBuf,
    pub result_path: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UpdateResult {
    pub schema: String,
    pub status: String,
    pub package_sha256: String,
    pub predecessor_sha256: String,
    pub detail: String,
}
