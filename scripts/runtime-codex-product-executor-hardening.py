#!/usr/bin/env python3
"""Make Agentd lookup the only public runtime.codex intelligence binding constructor."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def native_run_control(text: str) -> str:
    marker = "runtime.codex-agentd-admitted-loader-v1"
    if marker in text:
        return text
    old_imports = '''use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
'''
    new_imports = '''use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdClient;
'''
    if old_imports not in text:
        raise RuntimeError("Agentd loader import anchor absent")
    text = text.replace(old_imports, new_imports, 1)
    old_struct = '''pub struct NativeIntelligenceRunBinding {
    pub run_id: String,
    pub expected_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

impl NativeIntelligenceRunBinding {
    /// Construct the product binding from Agentd's durable run owner.
'''
    new_struct = '''pub struct NativeIntelligenceRunBinding {
    run_id: String,
    expected_revision: u64,
    context_digest: String,
    envelope_digest: String,
}

impl NativeIntelligenceRunBinding {
    /// Load the immutable product binding through the exact Agentd generation.
    ///
    /// runtime.codex-agentd-admitted-loader-v1: this is the only public
    /// constructor. Callers select a durable run ID but cannot supply its
    /// revision, context or compilation identity.
    pub async fn load_from_agentd(
        socket_path: std::path::PathBuf,
        agent_id: codex_hepta_contracts::AgentId,
        generation: u64,
        run_id: String,
    ) -> Result<Self> {
        let receipt = AgentdClient::new(socket_path, agent_id, generation)?
            .run_status(run_id.clone())
            .await?
            .ok_or("Agentd has no durable admitted work for the requested run")?;
        Self::from_agentd_receipt(&run_id, generation, receipt)
    }

    /// Validate a receipt already obtained through the exact Agentd client.
'''
    if old_struct not in text:
        raise RuntimeError("Agentd loader binding anchor absent")
    text = text.replace(old_struct, new_struct, 1)
    text = text.replace(
        "    pub fn from_agentd_receipt(\n",
        "    fn from_agentd_receipt(\n",
        1,
    )
    return text


def worker_cli(text: str) -> str:
    marker = "runtime.codex-agentd-admitted-loader-v1"
    if marker in text:
        return text
    text = text.replace("use codex_hepta_agentd::AgentdClient;\n", "", 1)
    old = '''        (Some("agentd-admitted"), Some(run_id)) => {
            let receipt = AgentdClient::new(agentd_socket, agent_id, generation)?
                .run_status(run_id.clone())
                .await?
                .ok_or("Agentd has no durable admitted work for --intelligence-run-id")?;
            Some(NativeIntelligenceRunBinding::from_agentd_receipt(
                &run_id,
                generation,
                receipt,
            )?)
        }
'''
    new = '''        (Some("agentd-admitted"), Some(run_id)) => {
            // runtime.codex-agentd-admitted-loader-v1
            Some(
                NativeIntelligenceRunBinding::load_from_agentd(
                    agentd_socket,
                    agent_id,
                    generation,
                    run_id,
                )
                .await?,
            )
        }
'''
    if old not in text:
        raise RuntimeError("Agentd loader CLI anchor absent")
    return text.replace(old, new, 1)


def product_e2e(text: str) -> str:
    marker = "runtime.codex-agentd-admitted-loader-v1"
    if marker in text:
        return text
    old = '''    let intelligence = NativeIntelligenceRunBinding::from_agentd_receipt(
        REQUEST_ID,
        1,
        attached,
    )
    .map_err(|error| anyhow::anyhow!(error.to_string()))?;
'''
    new = '''    // runtime.codex-agentd-admitted-loader-v1: the product caller may
    // name the durable run, but it cannot manufacture the bound identities.
    let intelligence = NativeIntelligenceRunBinding::load_from_agentd(
        agent.layout.agentd_control_socket().to_path_buf(),
        agent.agent_id.clone(),
        1,
        REQUEST_ID.to_string(),
    )
    .await
    .map_err(|error| anyhow::anyhow!(error.to_string()))?;
'''
    if old not in text:
        raise RuntimeError("Agentd loader product E2E anchor absent")
    return text.replace(old, new, 1)


def main() -> None:
    rewrite("codex-rs/hepta-infer-worker-host/src/native_run_control.rs", native_run_control)
    rewrite("codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs", worker_cli)
    rewrite("codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs", product_e2e)


if __name__ == "__main__":
    main()
