use std::fmt;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;

use crate::error::ShellError;

pub const MAX_STABLE_ID_BYTES: usize = 128;
pub const MAX_COPY_TEXT_BYTES: usize = 256 * 1024;
pub const MAX_NOTIFICATION_TITLE_BYTES: usize = 256;
pub const MAX_NOTIFICATION_BODY_BYTES: usize = 4096;

pub fn validate_stable_id(value: &str, name: &'static str) -> Result<(), ShellError> {
    if value.is_empty()
        || value.len() > MAX_STABLE_ID_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        return Err(ShellError::InvalidInput(format!(
            "{name} must be a bounded stable identifier"
        )));
    }
    Ok(())
}

pub fn validate_digest(value: &str, name: &'static str) -> Result<(), ShellError> {
    if value.len() != 64
        || value == "0".repeat(64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(ShellError::InvalidInput(format!(
            "{name} must be a non-zero lowercase SHA-256 digest"
        )));
    }
    Ok(())
}

pub fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    let digest = Sha256::digest(bytes.as_ref());
    let mut out = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut out, "{byte:02x}");
    }
    out
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SessionIncarnation {
    pub endpoint_id: String,
    pub session_id: String,
    pub generation: u64,
}

impl SessionIncarnation {
    pub fn validate(&self) -> Result<(), ShellError> {
        validate_stable_id(&self.endpoint_id, "endpoint_id")?;
        validate_stable_id(&self.session_id, "session_id")?;
        if self.generation == 0 {
            return Err(ShellError::InvalidInput(
                "session generation must be positive".to_owned(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct OperationKey {
    pub session_id: String,
    pub session_generation: u64,
    pub operation_id: String,
}

impl OperationKey {
    pub fn new(session: &SessionIncarnation, operation_id: &str) -> Result<Self, ShellError> {
        validate_stable_id(operation_id, "operation_id")?;
        Ok(Self {
            session_id: session.session_id.clone(),
            session_generation: session.generation,
            operation_id: operation_id.to_owned(),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EndpointManifest {
    pub endpoint_id: String,
    pub address: String,
    pub manifest_digest: String,
    pub protocol_version: u32,
}

impl EndpointManifest {
    pub fn validate(&self) -> Result<(), ShellError> {
        validate_stable_id(&self.endpoint_id, "endpoint_id")?;
        validate_digest(&self.manifest_digest, "manifest_digest")?;
        if self.protocol_version == 0 {
            return Err(ShellError::InvalidInput(
                "protocol_version must be positive".to_owned(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeView {
    pub session_id: String,
    pub session_generation: u64,
    pub generation: u64,
    pub revision: u64,
    pub digest: String,
    #[serde(default)]
    pub modules: Vec<String>,
}

impl RuntimeView {
    pub fn validate(&self) -> Result<(), ShellError> {
        validate_stable_id(&self.session_id, "view.session_id")?;
        validate_digest(&self.digest, "view.digest")?;
        if self.session_generation == 0 || self.generation == 0 || self.revision == 0 {
            return Err(ShellError::InvalidInput(
                "view generations and revision must be positive".to_owned(),
            ));
        }
        for module in &self.modules {
            validate_stable_id(module, "view.module")?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlatformAction {
    OpenPath,
    RevealPath,
    CopyText,
    Notify,
}

impl fmt::Display for PlatformAction {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::OpenPath => "open_path",
            Self::RevealPath => "reveal_path",
            Self::CopyText => "copy_text",
            Self::Notify => "notify",
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PlatformPayload {
    OpenPath { path: PathBuf },
    RevealPath { path: PathBuf },
    CopyText { text: String },
    Notify { title: String, body: String },
}

impl PlatformPayload {
    pub fn action(&self) -> PlatformAction {
        match self {
            Self::OpenPath { .. } => PlatformAction::OpenPath,
            Self::RevealPath { .. } => PlatformAction::RevealPath,
            Self::CopyText { .. } => PlatformAction::CopyText,
            Self::Notify { .. } => PlatformAction::Notify,
        }
    }

    pub fn validate(&self) -> Result<(), ShellError> {
        match self {
            Self::OpenPath { path } | Self::RevealPath { path } => {
                if !path.is_absolute() {
                    return Err(ShellError::InvalidInput(
                        "platform paths must be absolute".to_owned(),
                    ));
                }
            }
            Self::CopyText { text } => {
                if text.len() > MAX_COPY_TEXT_BYTES {
                    return Err(ShellError::InvalidInput(format!(
                        "copy text exceeds {MAX_COPY_TEXT_BYTES} bytes"
                    )));
                }
            }
            Self::Notify { title, body } => {
                if title.len() > MAX_NOTIFICATION_TITLE_BYTES
                    || body.len() > MAX_NOTIFICATION_BODY_BYTES
                {
                    return Err(ShellError::InvalidInput(
                        "notification text exceeds bounded native limits".to_owned(),
                    ));
                }
            }
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<String, ShellError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self)
            .map_err(|error| ShellError::InvalidInput(error.to_string()))?;
        Ok(sha256_hex(bytes))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlatformRequest {
    pub operation_id: String,
    pub displayed_revision: u64,
    pub payload: PlatformPayload,
    pub grant: SignedPlatformGrantV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedPlatformGrantV1 {
    pub key_id: String,
    pub session_id: String,
    pub session_generation: u64,
    pub operation_id: String,
    pub action: PlatformAction,
    pub payload_digest: String,
    pub expires_unix_ms: u64,
    pub signature_base64: String,
}

impl SignedPlatformGrantV1 {
    pub fn signing_message(&self) -> String {
        format!(
            "hepta.platform-grant.v1\nkey_id={}\nsession_id={}\nsession_generation={}\noperation_id={}\naction={}\npayload_digest={}\nexpires_unix_ms={}\n",
            self.key_id,
            self.session_id,
            self.session_generation,
            self.operation_id,
            self.action,
            self.payload_digest,
            self.expires_unix_ms
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalStatus {
    Succeeded,
    Failed,
    Rejected,
    Quarantined,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlatformReceipt {
    pub key: OperationKey,
    pub action: PlatformAction,
    pub payload_digest: String,
    pub terminal_status: Option<TerminalStatus>,
    pub outcome_digest: Option<String>,
    pub terminal_observed: bool,
}

impl PlatformReceipt {
    pub fn indeterminate(
        key: OperationKey,
        action: PlatformAction,
        payload_digest: String,
    ) -> Self {
        Self {
            key,
            action,
            payload_digest,
            terminal_status: None,
            outcome_digest: None,
            terminal_observed: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlatformObservation {
    pub terminal_status: Option<TerminalStatus>,
    pub outcome_digest: Option<String>,
}

impl PlatformObservation {
    pub fn indeterminate() -> Self {
        Self {
            terminal_status: None,
            outcome_digest: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PresentationState {
    pub session_id: String,
    pub session_generation: u64,
    pub generation: u64,
    pub revision: u64,
    pub digest: String,
    pub modules: Vec<String>,
    pub stale: bool,
}
