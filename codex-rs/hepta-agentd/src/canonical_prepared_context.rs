//! Private exact fields for the original canonical handoff codec.

use super::*;

impl Context {
    pub(in crate::intelligence_product::canonical_prepared) fn capture(request: &CompilationRequest, receipt: &ContextCompilationReceipt) -> Self {
        Self { compilation_id: request.compilation_id.to_string(), run_snapshot_digest: request.run_snapshot_digest.to_string(),
            objective_digest: request.objective_digest.to_string(), token_budget: request.token_budget,
            items: request.items.iter().map(|item| Item { item_id: item.item_id.to_string(), role: item.role as u8,
                content_digest: item.content_digest.to_string(), source_digest: item.source_digest.to_string(), token_count: item.token_count,
                contains_secret: item.contains_secret }).collect(), receipt: Receipt { compilation_id: receipt.compilation_id.to_string(),
                trusted_instruction_ids: receipt.trusted_instruction_ids.iter().map(ToString::to_string).collect(),
                untrusted_evidence_ids: receipt.untrusted_evidence_ids.iter().map(ToString::to_string).collect(),
                omitted_ids: receipt.omitted_ids.iter().map(ToString::to_string).collect(), used_tokens: receipt.used_tokens,
                context_digest: receipt.context_digest.to_string(), authority_denied: !receipt.authority.grants_any() } }
    }
    pub(in crate::intelligence_product::canonical_prepared) fn restore(self) -> anyhow::Result<(CompilationRequest, ContextCompilationReceipt)> {
        anyhow::ensure!(self.items.len() <= 4096 && self.receipt.authority_denied, "retained context bound/authority");
        let r = self.receipt;
        let ids = |values: Vec<String>| values.into_iter().map(StableId::new).collect::<Result<Vec<_>, _>>();
        Ok((CompilationRequest { compilation_id: StableId::new(self.compilation_id)?, run_snapshot_digest: self.run_snapshot_digest.parse()?,
            objective_digest: self.objective_digest.parse()?, token_budget: self.token_budget,
            items: self.items.into_iter().map(|item| Ok(codex_hepta_context_compiler::ContextItem { item_id: StableId::new(item.item_id)?,
                role: match item.role { 0 => codex_hepta_context_compiler::ContextRole::TrustedInstruction,
                    1 => codex_hepta_context_compiler::ContextRole::UntrustedEvidence, _ => anyhow::bail!("retained context role") },
                content_digest: item.content_digest.parse()?, source_digest: item.source_digest.parse()?, token_count: item.token_count,
                contains_secret: item.contains_secret })).collect::<anyhow::Result<_>>()? },
            ContextCompilationReceipt { compilation_id: StableId::new(r.compilation_id)?, trusted_instruction_ids: ids(r.trusted_instruction_ids)?,
                untrusted_evidence_ids: ids(r.untrusted_evidence_ids)?, omitted_ids: ids(r.omitted_ids)?, used_tokens: r.used_tokens,
                context_digest: r.context_digest.parse()?, authority: AuthorityPosture::DENY_ALL }))
    }
}
