use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use crate::CognitiveScope;
use crate::LedgerSourceKind;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::SourceDraft;

pub(crate) fn agent_id(suffix: u8) -> AgentId {
    AgentId::parse(format!("00000000-0000-4000-8000-{suffix:012x}")).expect("valid agent id")
}

pub(crate) fn workspace(value: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(value.as_bytes())
}

pub(crate) fn layout(temp: &TempDir, agent_id: &AgentId) -> codex_hepta_paths::HeptaAgentLayout {
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).expect("create fleet root");
    HeptaFleetRoot::parse(fleet)
        .expect("fleet root")
        .layout()
        .agent(agent_id)
}

pub(crate) fn source(scope: CognitiveScope, event_key: &str, content: &str) -> SourceDraft {
    SourceDraft {
        scope,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: event_key.to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 100,
    }
}

pub(crate) fn memory_revision(
    scope: CognitiveScope,
    content: &str,
    citation: crate::SourceRevisionId,
) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: vec![citation],
    }
}
