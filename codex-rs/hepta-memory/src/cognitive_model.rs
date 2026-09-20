use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::framing::frame_part;

pub const COGNITIVE_SCHEMA_VERSION: u32 = 1;
pub const SOURCE_REVISION: u64 = 1;
pub(crate) const MAX_MEMORY_BYTES: usize = 64 * 1024;
pub(crate) const MAX_SOURCE_BYTES: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct ProjectionGeneration(pub(crate) u64);

impl ProjectionGeneration {
    pub fn get(self) -> u64 {
        self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveAccess {
    agent_id: AgentId,
    workspace_sha256: Option<Sha256Digest>,
}

impl CognitiveAccess {
    pub fn agent_private(agent_id: AgentId) -> Self {
        Self {
            agent_id,
            workspace_sha256: None,
        }
    }

    pub fn workspace_private(agent_id: AgentId, workspace_sha256: Sha256Digest) -> Self {
        Self {
            agent_id,
            workspace_sha256: Some(workspace_sha256),
        }
    }

    pub fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }

    pub fn workspace_sha256(&self) -> Option<&Sha256Digest> {
        self.workspace_sha256.as_ref()
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(tag = "scope", rename_all = "snake_case")]
pub enum CognitiveScope {
    #[default]
    AgentPrivate,
    WorkspacePrivate {
        workspace_sha256: Sha256Digest,
    },
}

impl CognitiveScope {
    pub(crate) fn permits(&self, access: &CognitiveAccess) -> bool {
        match self {
            Self::AgentPrivate => true,
            Self::WorkspacePrivate { workspace_sha256 } => {
                access.workspace_sha256.as_ref() == Some(workspace_sha256)
            }
        }
    }

    pub(crate) fn database_parts(&self) -> (&'static str, Option<&str>) {
        match self {
            Self::AgentPrivate => ("agent_private", None),
            Self::WorkspacePrivate { workspace_sha256 } => {
                ("workspace_private", Some(workspace_sha256.as_str()))
            }
        }
    }

    pub(crate) fn projection_key(&self) -> String {
        match self {
            Self::AgentPrivate => "agent_private".to_string(),
            Self::WorkspacePrivate { workspace_sha256 } => {
                format!("workspace_private:{}", workspace_sha256.as_str())
            }
        }
    }

    pub(crate) fn parse(kind: &str, workspace: Option<String>) -> Result<Self, String> {
        match (kind, workspace) {
            ("agent_private", None) => Ok(Self::AgentPrivate),
            ("workspace_private", Some(workspace)) => Ok(Self::WorkspacePrivate {
                workspace_sha256: Sha256Digest::parse(workspace)?,
            }),
            _ => Err("invalid cognitive scope binding".to_string()),
        }
    }

    fn identity_parts(&self) -> (&'static [u8], Option<&[u8]>) {
        match self {
            Self::AgentPrivate => (b"agent_private", None),
            Self::WorkspacePrivate { workspace_sha256 } => (
                b"workspace_private",
                Some(workspace_sha256.as_str().as_bytes()),
            ),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LedgerSourceKind {
    UserMessage,
    AssistantConclusion,
    ExplicitMemoryDirective,
    PersistedToolResult,
    FileObservation,
    TurnSummary,
}

impl LedgerSourceKind {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::UserMessage => "user_message",
            Self::AssistantConclusion => "assistant_conclusion",
            Self::ExplicitMemoryDirective => "explicit_memory_directive",
            Self::PersistedToolResult => "persisted_tool_result",
            Self::FileObservation => "file_observation",
            Self::TurnSummary => "turn_summary",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, String> {
        match value {
            "user_message" => Ok(Self::UserMessage),
            "assistant_conclusion" => Ok(Self::AssistantConclusion),
            "explicit_memory_directive" => Ok(Self::ExplicitMemoryDirective),
            "persisted_tool_result" => Ok(Self::PersistedToolResult),
            "file_observation" => Ok(Self::FileObservation),
            "turn_summary" => Ok(Self::TurnSummary),
            _ => Err("invalid ledger source kind".to_string()),
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct SourceEventId(String);

impl SourceEventId {
    pub(crate) fn for_event(
        agent_id: &AgentId,
        scope: &CognitiveScope,
        kind: LedgerSourceKind,
        event_key: &str,
    ) -> Self {
        Self(stable_id(
            "source:v1:",
            b"hepta:cognitive:source:v1",
            agent_id,
            scope,
            &[kind.as_str().as_bytes(), event_key.as_bytes()],
        ))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub(crate) fn parse(value: String) -> Result<Self, String> {
        parse_stable_id(&value, "source:v1:")?;
        Ok(Self(value))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SourceRevisionId {
    pub source_id: SourceEventId,
    pub revision: u64,
}

impl SourceRevisionId {
    pub fn new(source_id: SourceEventId) -> Self {
        Self {
            source_id,
            revision: SOURCE_REVISION,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceDraft {
    pub scope: CognitiveScope,
    pub kind: LedgerSourceKind,
    pub event_key: String,
    pub content: Vec<u8>,
    pub observed_at_unix_seconds: i64,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct StableMemoryId(String);

impl StableMemoryId {
    pub(crate) fn for_key(agent_id: &AgentId, scope: &CognitiveScope, stable_key: &str) -> Self {
        Self(stable_id(
            "memory:v2:",
            b"hepta:cognitive:memory:v2",
            agent_id,
            scope,
            &[stable_key.as_bytes()],
        ))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        parse_stable_id(&value, "memory:v2:")?;
        Ok(Self(value))
    }
}

impl TryFrom<String> for StableMemoryId {
    type Error = String;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl TryFrom<&str> for StableMemoryId {
    type Error = String;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryRevisionId {
    pub memory_id: StableMemoryId,
    pub revision: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryVerification {
    Verified,
    Provisional,
}

impl MemoryVerification {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Verified => "verified",
            Self::Provisional => "provisional",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, String> {
        match value {
            "verified" => Ok(Self::Verified),
            "provisional" => Ok(Self::Provisional),
            _ => Err("invalid memory verification state".to_string()),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum MemoryLifecycleState {
    Active,
    Tombstoned { reason: String },
}

impl MemoryLifecycleState {
    pub(crate) fn database_parts(&self) -> (&'static str, Option<&str>) {
        match self {
            Self::Active => ("active", None),
            Self::Tombstoned { reason } => ("tombstoned", Some(reason)),
        }
    }

    pub(crate) fn parse(state: &str, reason: Option<String>) -> Result<Self, String> {
        match (state, reason) {
            ("active", None) => Ok(Self::Active),
            ("tombstoned", Some(reason)) if !reason.is_empty() => Ok(Self::Tombstoned { reason }),
            _ => Err("invalid memory lifecycle state".to_string()),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryDraft {
    pub stable_key: String,
    pub revision: MemoryRevisionDraft,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryRevisionDraft {
    pub scope: CognitiveScope,
    pub content: String,
    pub verification: MemoryVerification,
    pub lifecycle: MemoryLifecycleState,
    pub valid_from_unix_seconds: i64,
    pub valid_to_unix_seconds: Option<i64>,
    pub citations: Vec<SourceRevisionId>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryRevisionRecord {
    pub id: MemoryRevisionId,
    pub scope: CognitiveScope,
    pub content: String,
    pub content_sha256: Sha256Digest,
    pub verification: MemoryVerification,
    pub lifecycle: MemoryLifecycleState,
    pub valid_from_unix_seconds: i64,
    pub valid_to_unix_seconds: Option<i64>,
    pub supersedes_revision: Option<u64>,
    pub citations: Vec<SourceRevisionId>,
}

/// A model-proposed entity occurrence for one immutable memory revision.
///
/// `key` is canonicalized by the store before it is hashed. The resulting
/// canonical entity identity is stable for the owning agent and scope, while
/// the materialized projection node remains revision-local so provenance is
/// never collapsed to a representative memory.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct KgEntityFactDraft {
    pub key: String,
    pub entity_type: String,
    pub label: String,
}

/// A model-proposed relation whose endpoints must both be declared by the
/// same revision's [`KgEntityFactDraft`] set.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct KgRelationFactDraft {
    pub key: String,
    pub from_entity_key: String,
    pub to_entity_key: String,
    pub relation: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct KgFactSetDraft {
    pub entities: Vec<KgEntityFactDraft>,
    pub relations: Vec<KgRelationFactDraft>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CognitiveProjectionReceipt {
    pub generation: ProjectionGeneration,
    pub fact_set_sha256: Sha256Digest,
    pub input_heads_sha256: Sha256Digest,
    pub output_sha256: Sha256Digest,
    pub entity_count: u64,
    pub relation_count: u64,
    pub node_count: u64,
    pub edge_count: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CognitiveWriteReceipt {
    pub memory: MemoryRevisionRecord,
    pub source: SourceRevisionId,
    pub projection: CognitiveProjectionReceipt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KgNode {
    pub node_id: String,
    pub entity_type: String,
    pub label: String,
    pub valid_from_unix_seconds: i64,
    pub valid_to_unix_seconds: Option<i64>,
    pub memory: MemoryRevisionId,
    pub source: SourceRevisionId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KgEdge {
    pub edge_id: String,
    pub from_node_id: String,
    pub to_node_id: String,
    pub relation: String,
    pub valid_from_unix_seconds: i64,
    pub valid_to_unix_seconds: Option<i64>,
    pub memory: MemoryRevisionId,
    pub source: SourceRevisionId,
}

fn stable_id(
    prefix: &str,
    domain: &[u8],
    agent_id: &AgentId,
    scope: &CognitiveScope,
    suffix: &[&[u8]],
) -> String {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, domain);
    frame_part(&mut hasher, agent_id.as_str().as_bytes());
    let (scope_kind, workspace) = scope.identity_parts();
    frame_part(&mut hasher, scope_kind);
    frame_part(&mut hasher, workspace.unwrap_or_default());
    for part in suffix {
        frame_part(&mut hasher, part);
    }
    format!("{prefix}{:x}", hasher.finalize())
}

fn parse_stable_id(value: &str, prefix: &str) -> Result<(), String> {
    let digest = value
        .strip_prefix(prefix)
        .ok_or_else(|| format!("stable id must start with {prefix}"))?;
    Sha256Digest::parse(digest.to_string()).map(|_| ())
}
