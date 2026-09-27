#!/usr/bin/env python3
"""Bridge the reviewed V4 relation layout into the publisher migration."""

from pathlib import Path

path = Path(__file__).resolve().parents[1] / "codex-rs/hepta-prompt-registry/src/durable.rs"
text = path.read_text(encoding="utf-8")
method = """    pub fn register_factor(
        &mut self,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| registry.register_factor(factor))
    }

    pub fn register_factor_final_use(
        &mut self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        actor_id: &StableId,
        scope_digest: Digest32,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.ensure_available()?;
        let expected = final_use_register_factor_binding(&factor, actor_id, scope_digest)
            .map_err(DurableRegistryError::Admission)?;
        let token = authority
            .claim(signed, &expected)
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?;
        authority
            .with_verified_use(token, &expected, || {
                self.commit(|registry| registry.register_factor(factor))
            })
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?
    }

"""
if method in text:
    raise SystemExit(0)
anchor = """    pub fn register_factor(
        &mut self,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| registry.register_factor(factor))
    }

    /// Register one governed factor relation in the same durable image
"""
replacement = method + "    /// Register one governed factor relation in the same durable image\n"
if text.count(anchor) != 1:
    raise SystemExit(f"durable.rs: expected one V4 publisher bridge anchor, found {text.count(anchor)}")
path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
