use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::OwnerDurableStoreV1;
use super::transaction::OwnerJournalError;

static NEXT_STATUS: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerRuntimePhaseV1 {
    Starting,
    Recovering,
    Ready,
    Draining,
    Stopped,
    Failed,
}

impl ArtifactOwnerRuntimePhaseV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Starting => "starting",
            Self::Recovering => "recovering",
            Self::Ready => "ready",
            Self::Draining => "draining",
            Self::Stopped => "stopped",
            Self::Failed => "failed",
        }
    }

    #[must_use]
    pub const fn is_live(self) -> bool {
        matches!(self, Self::Starting | Self::Recovering | Self::Ready | Self::Draining)
    }

    #[must_use]
    pub const fn is_ready(self) -> bool {
        matches!(self, Self::Ready)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerRuntimeStatusV1 {
    pub phase: ArtifactOwnerRuntimePhaseV1,
    pub process_id: u32,
    pub started_at: u64,
    pub observed_at: u64,
    pub keyring_generation: u64,
    pub keyring_digest: Digest32,
    pub trust_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub recovery_operation_id: Option<StableId>,
    pub detail: String,
}

impl ArtifactOwnerRuntimeStatusV1 {
    pub fn persist(
        &self,
        store: &dyn OwnerDurableStoreV1,
    ) -> Result<PathBuf, ArtifactOwnerStatusError> {
        validate_detail(&self.detail)?;
        let sequence = NEXT_STATUS.fetch_add(1, Ordering::Relaxed);
        let relative = PathBuf::from("host/status").join(format!(
            "{:020}-{:020}-{:010}-{}.status",
            self.observed_at,
            sequence,
            self.process_id,
            self.phase.as_str()
        ));
        store.write_new(&relative, &self.encode())?;
        Ok(relative)
    }

    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        format!(
            concat!(
                "HEPTA-LEARNING-ARTIFACTD-STATUS-V1\n",
                "phase={}\n",
                "process_id={}\n",
                "started_at={}\n",
                "observed_at={}\n",
                "keyring_generation={}\n",
                "keyring_digest={}\n",
                "trust_digest={}\n",
                "registry_head_digest={}\n",
                "withdrawal_head_digest={}\n",
                "recovery_operation_id={}\n",
                "detail={}\n"
            ),
            self.phase.as_str(),
            self.process_id,
            self.started_at,
            self.observed_at,
            self.keyring_generation,
            self.keyring_digest,
            self.trust_digest,
            self.registry_head_digest,
            self.withdrawal_head_digest,
            self.recovery_operation_id
                .as_ref()
                .map_or("-", StableId::as_str),
            self.detail,
        )
        .into_bytes()
    }

    #[must_use]
    pub fn response_json(&self) -> String {
        format!(
            concat!(
                "{{\"schema\":\"hepta.learning-artifactd.status.v1\",",
                "\"phase\":\"{}\",\"live\":{},\"ready\":{},",
                "\"processId\":{},\"startedAt\":{},\"observedAt\":{},",
                "\"keyringGeneration\":{},\"keyringDigest\":\"{}\",",
                "\"trustDigest\":\"{}\",\"registryHeadDigest\":\"{}\",",
                "\"withdrawalHeadDigest\":\"{}\",",
                "\"recoveryOperationId\":{},\"detail\":\"{}\"}}"
            ),
            self.phase.as_str(),
            self.phase.is_live(),
            self.phase.is_ready(),
            self.process_id,
            self.started_at,
            self.observed_at,
            self.keyring_generation,
            self.keyring_digest,
            self.trust_digest,
            self.registry_head_digest,
            self.withdrawal_head_digest,
            self.recovery_operation_id.as_ref().map_or_else(
                || "null".to_owned(),
                |value| format!("\"{}\"", value.as_str())
            ),
            escape_json(&self.detail),
        )
    }
}

fn validate_detail(value: &str) -> Result<(), ArtifactOwnerStatusError> {
    if value.len() > 1024 || value.contains(['\n', '\r']) {
        return Err(ArtifactOwnerStatusError::InvalidDetail);
    }
    Ok(())
}

fn escape_json(value: &str) -> String {
    let mut output = String::with_capacity(value.len());
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            character if character.is_control() => output.push('?'),
            character => output.push(character),
        }
    }
    output
}

#[derive(Debug)]
pub enum ArtifactOwnerStatusError {
    Journal(OwnerJournalError),
    InvalidDetail,
}

impl fmt::Display for ArtifactOwnerStatusError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOwnerStatusError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Journal(error) => Some(error),
            Self::InvalidDetail => None,
        }
    }
}

impl From<OwnerJournalError> for ArtifactOwnerStatusError {
    fn from(value: OwnerJournalError) -> Self {
        Self::Journal(value)
    }
}
