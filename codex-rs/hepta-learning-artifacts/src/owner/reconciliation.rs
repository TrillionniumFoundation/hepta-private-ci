use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::path::Path;
use std::str::FromStr;
use std::sync::Arc;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerDurabilityV1;
use crate::DirectoryDurabilityError;

use super::capability_validation::LearningArtifactHostActionV1;
use super::capability_validation::VerifiedLearningArtifactHostCommandV1;
use super::capability_validation::push_id;

const AUDIT_MAGIC: &str = "HEPTA-LEARNING-ARTIFACT-HOST-AUDIT-V1";
const MAX_AUDIT_EVENTS: usize = 4_096;
const MAX_AUDIT_EVENT_BYTES: usize = 16 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningArtifactHostLifecycleV1 {
    Recovering(StableId),
    Ready,
    Draining,
    Faulted,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct LearningArtifactHostMetricsV1 {
    pub commands_applied: u64,
    pub commands_rejected: u64,
    pub authentication_rejected: u64,
    pub replay_rejected: u64,
    pub durability_indeterminate: u64,
    pub recovery_completions: u64,
    pub audit_events: u64,
    pub backup_manifests: u64,
    pub policy_rotations: u64,
    pub schema_migrations: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactHostHealthV1 {
    pub lifecycle: LearningArtifactHostLifecycleV1,
    pub ready: bool,
    pub live: bool,
    pub schema_version: u32,
    pub registry_head_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub access_policy_digest: Digest32,
    pub audit_head_digest: Digest32,
    pub audit_events: usize,
    pub metrics: LearningArtifactHostMetricsV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum LearningArtifactAuditOutcomeV1 {
    Applied,
    Rejected,
    Indeterminate,
}

impl LearningArtifactAuditOutcomeV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Applied => 1,
            Self::Rejected => 2,
            Self::Indeterminate => 3,
        }
    }

    const fn from_tag(value: u8) -> Option<Self> {
        match value {
            1 => Some(Self::Applied),
            2 => Some(Self::Rejected),
            3 => Some(Self::Indeterminate),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct LearningArtifactAuditEventV1 {
    sequence: u64,
    command_id: StableId,
    principal_id: StableId,
    action: LearningArtifactHostActionV1,
    request_digest: Digest32,
    command_digest: Digest32,
    outcome: LearningArtifactAuditOutcomeV1,
    result_digest: Digest32,
    occurred_at: u64,
    previous_digest: Digest32,
    event_digest: Digest32,
}

impl LearningArtifactAuditEventV1 {
    fn digest_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-artifacts.host-audit-event.v1".to_vec();
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        push_id(&mut bytes, &self.command_id);
        push_id(&mut bytes, &self.principal_id);
        bytes.push(self.action.tag());
        bytes.extend_from_slice(self.request_digest.as_array());
        bytes.extend_from_slice(self.command_digest.as_array());
        bytes.push(self.outcome.tag());
        bytes.extend_from_slice(self.result_digest.as_array());
        bytes.extend_from_slice(&self.occurred_at.to_be_bytes());
        bytes.extend_from_slice(self.previous_digest.as_array());
        bytes
    }

    fn canonical_line(&self) -> String {
        format!(
            "{AUDIT_MAGIC}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
            self.sequence,
            self.command_id,
            self.principal_id,
            self.action.tag(),
            self.request_digest,
            self.command_digest,
            self.outcome.tag(),
            self.result_digest,
            self.occurred_at,
            self.previous_digest,
            self.event_digest,
        )
    }

    fn parse(bytes: &[u8]) -> Result<Self, LearningArtifactAuditError> {
        if bytes.is_empty() || bytes.len() > MAX_AUDIT_EVENT_BYTES {
            return Err(LearningArtifactAuditError::Corrupt);
        }
        let text = std::str::from_utf8(bytes).map_err(|_| LearningArtifactAuditError::Corrupt)?;
        if !text.ends_with('\n') || text[..text.len() - 1].contains('\n') {
            return Err(LearningArtifactAuditError::Corrupt);
        }
        let parts: Vec<&str> = text[..text.len() - 1].split('|').collect();
        if parts.len() != 12 || parts[0] != AUDIT_MAGIC {
            return Err(LearningArtifactAuditError::Corrupt);
        }
        let action_tag = parts[4]
            .parse::<u8>()
            .map_err(|_| LearningArtifactAuditError::Corrupt)?;
        let outcome_tag = parts[7]
            .parse::<u8>()
            .map_err(|_| LearningArtifactAuditError::Corrupt)?;
        let value = Self {
            sequence: parts[1]
                .parse()
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
            command_id: StableId::new(parts[2].to_owned())
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
            principal_id: StableId::new(parts[3].to_owned())
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
            action: LearningArtifactHostActionV1::from_tag(action_tag)
                .ok_or(LearningArtifactAuditError::Corrupt)?,
            request_digest: Digest32::from_str(parts[5])
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
            command_digest: Digest32::from_str(parts[6])
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
            outcome: LearningArtifactAuditOutcomeV1::from_tag(outcome_tag)
                .ok_or(LearningArtifactAuditError::Corrupt)?,
            result_digest: Digest32::from_str(parts[8])
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
            occurred_at: parts[9]
                .parse()
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
            previous_digest: Digest32::from_str(parts[10])
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
            event_digest: Digest32::from_str(parts[11])
                .map_err(|_| LearningArtifactAuditError::Corrupt)?,
        };
        if value.request_digest.is_zero()
            || value.command_digest.is_zero()
            || value.result_digest.is_zero()
            || Digest32::of_bytes(&value.digest_bytes()) != value.event_digest
            || value.canonical_line().as_bytes() != bytes
        {
            return Err(LearningArtifactAuditError::Corrupt);
        }
        Ok(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct SeenCommandV1 {
    command_digest: Digest32,
}

pub(super) struct LearningArtifactAuditJournalV1 {
    sequence: u64,
    head_digest: Digest32,
    seen: BTreeMap<StableId, SeenCommandV1>,
}

impl fmt::Debug for LearningArtifactAuditJournalV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LearningArtifactAuditJournalV1")
            .field("sequence", &self.sequence)
            .field("head_digest", &self.head_digest)
            .field("seen", &self.seen.len())
            .finish()
    }
}

impl LearningArtifactAuditJournalV1 {
    pub(super) fn open(control_root: &Path) -> Result<Self, LearningArtifactAuditError> {
        let audit_root = control_root.join("audit");
        let mut entries = Vec::new();
        for entry in fs::read_dir(&audit_root).map_err(LearningArtifactAuditError::Io)? {
            let entry = entry.map_err(LearningArtifactAuditError::Io)?;
            let file_type = entry.file_type().map_err(LearningArtifactAuditError::Io)?;
            if file_type.is_symlink() || !file_type.is_file() {
                return Err(LearningArtifactAuditError::Corrupt);
            }
            entries.push(entry.path());
        }
        entries.sort();
        if entries.len() > MAX_AUDIT_EVENTS {
            return Err(LearningArtifactAuditError::Capacity);
        }
        let mut journal = Self {
            sequence: 0,
            head_digest: Digest32::ZERO,
            seen: BTreeMap::new(),
        };
        for path in entries {
            let bytes = fs::read(&path).map_err(LearningArtifactAuditError::Io)?;
            let event = LearningArtifactAuditEventV1::parse(&bytes)?;
            let expected_name = format!(
                "{:020}-{}.receipt",
                event.sequence, event.event_digest
            );
            if event.sequence != journal.sequence + 1
                || event.previous_digest != journal.head_digest
                || path.file_name().and_then(|name| name.to_str())
                    != Some(expected_name.as_str())
                || journal
                    .seen
                    .insert(
                        event.command_id.clone(),
                        SeenCommandV1 {
                            command_digest: event.command_digest,
                        },
                    )
                    .is_some()
            {
                return Err(LearningArtifactAuditError::Corrupt);
            }
            journal.sequence = event.sequence;
            journal.head_digest = event.event_digest;
        }
        Ok(journal)
    }

    pub(super) fn require_fresh(
        &self,
        verified: &VerifiedLearningArtifactHostCommandV1,
    ) -> Result<(), LearningArtifactAuditError> {
        if let Some(existing) = self.seen.get(verified.command_id()) {
            return if existing.command_digest == verified.command_digest() {
                Err(LearningArtifactAuditError::Replay)
            } else {
                Err(LearningArtifactAuditError::ReplayConflict)
            };
        }
        if self.seen.len() >= MAX_AUDIT_EVENTS {
            return Err(LearningArtifactAuditError::Capacity);
        }
        Ok(())
    }

    pub(super) fn record(
        &mut self,
        control_root: &Path,
        durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
        verified: &VerifiedLearningArtifactHostCommandV1,
        outcome: LearningArtifactAuditOutcomeV1,
        result_digest: Digest32,
        occurred_at: u64,
    ) -> Result<Digest32, LearningArtifactAuditError> {
        self.require_fresh(verified)?;
        if result_digest.is_zero() {
            return Err(LearningArtifactAuditError::Corrupt);
        }
        let mut event = LearningArtifactAuditEventV1 {
            sequence: self.sequence + 1,
            command_id: verified.command_id().clone(),
            principal_id: verified.principal_id().clone(),
            action: verified.action(),
            request_digest: verified.request_digest(),
            command_digest: verified.command_digest(),
            outcome,
            result_digest,
            occurred_at,
            previous_digest: self.head_digest,
            event_digest: Digest32::ZERO,
        };
        event.event_digest = Digest32::of_bytes(&event.digest_bytes());
        let relative = std::path::PathBuf::from("audit").join(format!(
            "{:020}-{}.receipt",
            event.sequence, event.event_digest
        ));
        durability
            .create_control_file(control_root, &relative, event.canonical_line().as_bytes())
            .map_err(LearningArtifactAuditError::Durability)?;
        durability
            .sync_control_root(&control_root.join("audit"))
            .map_err(LearningArtifactAuditError::Durability)?;
        durability
            .sync_control_root(control_root)
            .map_err(LearningArtifactAuditError::Durability)?;
        self.sequence = event.sequence;
        self.head_digest = event.event_digest;
        self.seen.insert(
            event.command_id,
            SeenCommandV1 {
                command_digest: event.command_digest,
            },
        );
        Ok(event.event_digest)
    }

    pub(super) const fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    pub(super) fn len(&self) -> usize {
        self.seen.len()
    }
}

#[derive(Debug)]
pub enum LearningArtifactAuditError {
    Io(std::io::Error),
    Durability(DirectoryDurabilityError),
    Corrupt,
    Capacity,
    Replay,
    ReplayConflict,
}

impl fmt::Display for LearningArtifactAuditError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningArtifactAuditError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Durability(error) => Some(error),
            Self::Corrupt | Self::Capacity | Self::Replay | Self::ReplayConflict => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    use crate::FilesystemArtifactOwnerDurabilityV1;

    static NEXT_ROOT: AtomicU64 = AtomicU64::new(1);

    fn root() -> PathBuf {
        std::env::temp_dir().join(format!(
            "hepta-artifact-host-audit-{}-{}",
            std::process::id(),
            NEXT_ROOT.fetch_add(1, Ordering::Relaxed)
        ))
    }

    #[cfg(unix)]
    #[test]
    fn audit_reopen_preserves_replay_fence() {
        let control_root = root();
        fs::create_dir_all(control_root.join("audit")).expect("create audit root");
        let durability: Arc<dyn ArtifactOwnerDurabilityV1> =
            Arc::new(FilesystemArtifactOwnerDurabilityV1);
        let verified = VerifiedLearningArtifactHostCommandV1 {
            command_id: StableId::new("command".to_owned()).expect("id"),
            principal_id: StableId::new("principal".to_owned()).expect("id"),
            action: LearningArtifactHostActionV1::Publish,
            request_digest: Digest32::of_bytes(b"request"),
            command_digest: Digest32::of_bytes(b"command"),
            policy_digest: Digest32::of_bytes(b"policy"),
            authority: AuthorityPosture::DENY_ALL,
        };
        let mut journal = LearningArtifactAuditJournalV1::open(&control_root).expect("open");
        journal
            .record(
                &control_root,
                &durability,
                &verified,
                LearningArtifactAuditOutcomeV1::Applied,
                Digest32::of_bytes(b"result"),
                10,
            )
            .expect("record");
        let reopened = LearningArtifactAuditJournalV1::open(&control_root).expect("reopen");
        assert_eq!(
            reopened.require_fresh(&verified),
            Err(LearningArtifactAuditError::Replay)
        );
        fs::remove_dir_all(control_root).expect("cleanup");
    }
}
