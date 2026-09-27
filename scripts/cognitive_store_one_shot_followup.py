#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs"
text = PATH.read_text(encoding="utf-8")
old = """#[tokio::test(flavor = \"multi_thread\", worker_threads = 6)]
async fn running_consumer_observes_owner_control_grant_and_revoke_without_restart() -> Result<()> {
"""
new = """#[tokio::test(flavor = \"multi_thread\", worker_threads = 6)]
#[ignore = \"requires an externally verified production writer bootstrap; success is qualified by cognitive_store_product_writer\"]
async fn running_consumer_observes_owner_control_grant_and_revoke_without_restart() -> Result<()> {
"""
if text.count(old) != 1:
    raise SystemExit("expected one unguarded federation success E2E")
text = text.replace(old, new, 1)
append = r'''

/// Normal Agentd startup retains a cognitive read capability but no mutation
/// capability. Federation grant must therefore fail closed until a trusted host
/// supplies the exact-cut recovered writer and live authority verifier.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn running_owner_control_rejects_federation_mutation_without_writer_bootstrap() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let owner = fleet.register(AGENT_A, "workspace-owner-no-writer")?;
    let consumer = fleet.register(AGENT_B, "workspace-consumer-no-writer")?;
    let owner_model = responses::start_mock_server().await;
    MockResponsesConfig::new(&owner_model.uri()).write(owner.layout.home_root())?;

    fleet.start(&owner)?;
    let (owner_control, _) = fleet.wait_ready(&owner, 1).await?;
    let error = owner_control
        .memory_federation_grant(
            consumer.agent_id,
            MemoryFederationScopeKind::AgentPrivate,
            3_600,
        )
        .await
        .expect_err("normal read-only Agentd must reject federation mutation")
        .to_string();
    ensure!(
        error.to_ascii_lowercase().contains("cognitive")
            && error.to_ascii_lowercase().contains("unavailable"),
        "unexpected fail-closed federation error: {error}"
    );
    Ok(())
}
'''
if "running_owner_control_rejects_federation_mutation_without_writer_bootstrap" in text:
    raise SystemExit("fail-closed federation E2E already exists")
PATH.write_text(text + append, encoding="utf-8")
