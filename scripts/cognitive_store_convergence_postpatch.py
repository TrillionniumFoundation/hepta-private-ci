#!/usr/bin/env python3
"""Tighten generated cognitive.store boundaries before the one-shot commit."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value.rstrip() + "\n", encoding="utf-8")

def replace(path: str, old: str, new: str, count: int = 1) -> None:
    value = read(path)
    if value.count(old) != count:
        raise SystemExit(f"{path}: expected {count} matches for {old!r}")
    write(path, value.replace(old, new, count))

# Treat the extension crate as a delegated physical-owner implementation and
# recognise explicitly named qualification modules. Product Agentd consumers
# are still required to migrate to the read-only facade.
policy_path = ROOT / "docs/modules/cognitive.store/ARCHITECTURE_BOUNDARY.json"
policy = json.loads(policy_path.read_text(encoding="utf-8"))
policy["rawOwnerRoots"] = [
    "codex-rs/hepta-memory/src",
    "codex-rs/ext/hepta-memory/src",
]
if "qualification_" not in policy["qualificationMarkers"]:
    policy["qualificationMarkers"].append("qualification_")
policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")

# Shared Replay is a read consumer. It must not retain the raw mutable owner.
replace(
    "codex-rs/hepta-cognitive-store/src/durable.rs",
    '''    pub async fn revalidate_memory_candidates(
        &self,
        access: &CognitiveAccess,
        bindings: &[codex_hepta_memory::MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> Result<Vec<codex_hepta_memory::RevalidationStatus>, DurableCognitiveStoreError> {
        self.backend
            .revalidate_memory_candidates(access, bindings, now_unix_seconds)
            .await
    }

    pub async fn revalidate_lane_c_snapshot(''',
    '''    pub async fn revalidate_memory_candidates(
        &self,
        access: &CognitiveAccess,
        bindings: &[codex_hepta_memory::MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> Result<Vec<codex_hepta_memory::RevalidationStatus>, DurableCognitiveStoreError> {
        self.backend
            .revalidate_memory_candidates(access, bindings, now_unix_seconds)
            .await
    }

    pub async fn read_shared_experience(
        &self,
        consumer: &codex_hepta_memory::FederationConsumerAccess,
        key: &codex_hepta_contracts::Sha256Digest,
        purpose: &codex_hepta_memory::SharedExperiencePurposeV1,
    ) -> Result<codex_hepta_memory::SharedExperienceUseV1, DurableCognitiveStoreError> {
        self.backend
            .read_shared_experience(consumer, key, purpose)
            .await
    }

    pub async fn revalidate_lane_c_snapshot(''',
)
replace(
    "codex-rs/hepta-agentd/src/shared_terminal_cell.rs",
    "use codex_hepta_memory::CognitiveStore;",
    "use codex_hepta_cognitive_store::DurableCognitiveReadStore as CognitiveStore;\nuse codex_hepta_memory::CognitiveRuntime;",
)
replace(
    "codex-rs/hepta-agentd/src/shared_terminal_cell.rs",
    '''    pub fn new(
        source: Arc<CognitiveStore>,
        consumer: FederationConsumerAccess,
        parameter_scope: String,
        artifact_consumer: AgentId,
    ) -> Result<Self, SharedTerminalCellError> {
        if consumer.agent_id() != &artifact_consumer''',
    '''    pub fn new(
        source_runtime: &CognitiveRuntime,
        consumer: FederationConsumerAccess,
        parameter_scope: String,
        artifact_consumer: AgentId,
    ) -> Result<Self, SharedTerminalCellError> {
        let source = CognitiveStore::from_runtime(source_runtime)
            .ok_or(SharedTerminalCellError::Binding("cognitive runtime"))?;
        if consumer.agent_id() != &artifact_consumer''',
)
replace(
    "codex-rs/hepta-agentd/src/shared_terminal_cell.rs",
    "            source,\n            consumer,",
    "            source: Arc::new(source),\n            consumer,",
)

# Adapt the only callsite, an integration test that still uses the raw owner to
# create fixtures before exposing a read-only runtime to the product consumer.
replace(
    "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
    "    use codex_hepta_memory::CognitiveStore;",
    "    use codex_hepta_memory::CognitiveRuntime;\n    use codex_hepta_memory::CognitiveStore;",
)
replace(
    "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
    '''    let host = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),''',
    '''    let source_runtime = CognitiveRuntime::Available(Arc::clone(&source));
    let host = AgentdSharedReplayHostV1::new(
        &source_runtime,''',
)
replace(
    "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
    '''    let wrong_scope = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),''',
    '''    let wrong_scope = AgentdSharedReplayHostV1::new(
        &source_runtime,''',
)
replace(
    "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
    '''    let wrong_workspace = AgentdSharedReplayHostV1::new(
        Arc::clone(&source),''',
    '''    let wrong_workspace = AgentdSharedReplayHostV1::new(
        &source_runtime,''',
)

# Remove this transient helper from the result commit.
Path(__file__).unlink()
print('{"status":"postpatched"}')
