//! Explicit typed proposals. These values carry no owner or signing authority.

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveScope;
use crate::CognitiveStoreError;
use crate::KgFactSetDraft;
use crate::LedgerSourceKind;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::SourceDraft;
use crate::StableMemoryId;

pub const TYPED_MEMORY_ADMISSION_PURPOSE_V1: &str = "hepta.memory.typed-admission.v1";

/// Persisted type of an admitted record. MetaMemory is a quality consumer and
/// deliberately has no fact-writing variant here.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TypedMemoryKindV1 {
    Episode,
    Fact,
    Preference,
    Procedure,
}

impl TypedMemoryKindV1 {
    pub const fn memory_kind(self) -> MemoryKind {
        match self {
            Self::Episode => MemoryKind::Episode,
            Self::Fact => MemoryKind::Fact,
            Self::Preference => MemoryKind::Preference,
            Self::Procedure => MemoryKind::Procedure,
        }
    }

    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Episode => "episode",
            Self::Fact => "fact",
            Self::Preference => "preference",
            Self::Procedure => "procedure",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, CognitiveStoreError> {
        match value {
            "episode" => Ok(Self::Episode),
            "fact" => Ok(Self::Fact),
            "preference" => Ok(Self::Preference),
            "procedure" => Ok(Self::Procedure),
            _ => Err(CognitiveStoreError::Corrupt("unknown memory kind".into())),
        }
    }
}

/// A separate envelope preserves the exact legacy draft serialization/hash.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "operation", rename_all = "snake_case")]
pub enum TypedMemoryChangeV1 {
    Create {
        draft: MemoryDraft,
    },
    Correct {
        memory_id: StableMemoryId,
        expected_revision: u64,
        draft: MemoryRevisionDraft,
    },
}

impl TypedMemoryChangeV1 {
    pub fn revision(&self) -> &MemoryRevisionDraft {
        match self {
            Self::Create { draft } => &draft.revision,
            Self::Correct { draft, .. } => draft,
        }
    }

    pub(crate) fn target(&self, owner: &AgentId) -> (StableMemoryId, u64) {
        match self {
            Self::Create { draft } => (
                StableMemoryId::for_key(owner, &draft.revision.scope, &draft.stable_key),
                1,
            ),
            Self::Correct {
                memory_id,
                expected_revision,
                ..
            } => (memory_id.clone(), expected_revision.saturating_add(1)),
        }
    }
}

/// A host must authorize the entire proposal, including original source bytes,
/// structured facts, predecessor, and the exact source/forget cut. A caller's
/// evidence digest is only a reference until the installed verifier resolves it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TypedMemoryProposalV1 {
    pub kind: TypedMemoryKindV1,
    pub change: TypedMemoryChangeV1,
    pub source: SourceDraft,
    pub facts: KgFactSetDraft,
    pub expected_owner_cut_sha256: Sha256Digest,
    pub expected_source_frontier: u64,
    pub expected_tombstone_frontier: u64,
    pub host_evidence_sha256: Sha256Digest,
}

impl TypedMemoryProposalV1 {
    pub fn scope(&self) -> &CognitiveScope {
        &self.change.revision().scope
    }

    pub(crate) fn validate(&self) -> Result<(), CognitiveStoreError> {
        let revision = self.change.revision();
        crate::cognitive_memory_store::validate_revision_draft(revision)?;
        if self.kind == TypedMemoryKindV1::Procedure {
            return Err(CognitiveStoreError::AccessDenied(
                "Procedure admission requires an independent outcome owner; no resolver is installed".into(),
            ));
        }
        if revision.verification != MemoryVerification::Verified
            || revision.lifecycle != MemoryLifecycleState::Active
            || !revision.citations.is_empty()
            || self.source.scope != revision.scope
            || self.source.content != revision.content.as_bytes()
        {
            return Err(CognitiveStoreError::Invalid(
                "typed admission requires a verified active draft with owner-bound exact source"
                    .into(),
            ));
        }
        if self.kind == TypedMemoryKindV1::Episode
            && (matches!(
                self.source.kind,
                LedgerSourceKind::AssistantConclusion | LedgerSourceKind::TurnSummary
            ) || self.source.observed_at_unix_seconds != revision.valid_from_unix_seconds)
        {
            return Err(CognitiveStoreError::Invalid(
                "Episode requires an original event source and its observed timestamp".into(),
            ));
        }
        if self.kind == TypedMemoryKindV1::Preference
            && !matches!(
                self.source.kind,
                LedgerSourceKind::UserMessage | LedgerSourceKind::ExplicitMemoryDirective
            )
        {
            return Err(CognitiveStoreError::Invalid(
                "Preference requires an explicit user source".into(),
            ));
        }
        if let TypedMemoryChangeV1::Correct {
            expected_revision, ..
        } = &self.change
            && (*expected_revision == 0 || *expected_revision >= i64::MAX as u64)
        {
            return Err(CognitiveStoreError::Invalid(
                "invalid typed predecessor".into(),
            ));
        }
        Ok(())
    }
}

/// Trusted host composition must resolve evidence through its independent
/// owner and check the complete proposed semantics. No implementation or
/// signing key is supplied by this crate; absence cannot become success.
/// Procedure is rejected before this interface until an actual outcome-owner
/// resolver for steps, environment and success criteria is implemented.
pub trait TypedMemoryEvidenceVerifierV1: Send + Sync {
    fn verify(&self, owner: &AgentId, proposal: &TypedMemoryProposalV1) -> Result<(), String>;
}
