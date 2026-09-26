#!/usr/bin/env python3
"""Add authenticated retire/revoke product ingress to Agentd prompt owner."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "codex-rs/hepta-agentd/src/prompt_runtime.rs"


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    marker = "    /// Enumerate candidates from this owner's exact current durable registry.\n"
    if "    pub fn revoke_factor(" in text and "    pub fn retire_factor(" in text:
        return
    if text.count(marker) != 1:
        raise SystemExit("prompt_runtime.rs: exact enumeration marker missing or duplicated")
    methods = """    pub fn retire_factor(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        factor_id: &StableId,
        actor_id: &StableId,
        scope_digest: Digest32,
        reason_digest: Digest32,
    ) -> Result<RegistryReceipt, AgentdPromptPipelineError> {
        self.registry
            .lock()
            .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?
            .retire_factor_final_use(
                authority,
                signed,
                factor_id,
                actor_id,
                scope_digest,
                reason_digest,
            )
            .map_err(|error| AgentdPromptPipelineError::Publisher(error.to_string()))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn revoke_factor(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        factor_id: &StableId,
        actor_id: &StableId,
        scope_digest: Digest32,
        reason_digest: Digest32,
        cutoff_unix_ms: u64,
    ) -> Result<RegistryReceipt, AgentdPromptPipelineError> {
        self.registry
            .lock()
            .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?
            .revoke_factor_final_use(
                authority,
                signed,
                factor_id,
                actor_id,
                scope_digest,
                reason_digest,
                cutoff_unix_ms,
            )
            .map_err(|error| AgentdPromptPipelineError::Publisher(error.to_string()))
    }

"""
    PATH.write_text(text.replace(marker, methods + marker, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
