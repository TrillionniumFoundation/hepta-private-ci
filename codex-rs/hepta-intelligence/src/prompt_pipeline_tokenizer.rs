//! Exact-tokenizer delivery preparation using the original registry owner.
//!
//! This entry does not admit new continuation content or supply a tokenizer.
//! The caller supplies the existing profile-bound tokenizer and retains the
//! provider/admission responsibilities of the original serialization path.

use codex_hepta_context_compiler::ExactTokenizerV2;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_registry::DurablePromptRegistry;

use crate::PreparedPromptContextV1;
use crate::PreparedPromptDeliveryV1;
use crate::PromptDeliveryPrepareRequestV1;
use crate::PromptPipelineErrorV1;

/// Revalidate the portfolio, registered item counts and final payload count.
///
/// The tokenizer must be the original model-profile implementation. Estimates,
/// bytes-per-token ratios and independently chosen byte tokenizers do not meet
/// this contract. Selected-item counts must agree with the admitted registry
/// realizations, and the complete serialization (including framing) must fit
/// the V2 budget. Provider input reservations and terminal usage are separate.
///
/// This function preserves the existing selected-byte/materialization checks;
/// it does not authenticate additional caller bytes as admitted continuation,
/// grant effects, create a prompt store, or perform provider I/O.
pub fn prepare_prompt_delivery_with_tokenizer_v1(
    registry: &DurablePromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    prepared: &PreparedPromptContextV1,
    request: PromptDeliveryPrepareRequestV1,
    tokenizer: &impl ExactTokenizerV2,
) -> Result<PreparedPromptDeliveryV1, PromptPipelineErrorV1> {
    crate::prompt_pipeline::prepare_prompt_delivery_internal_v1(
        registry,
        portfolio,
        prepared,
        request,
        Some(tokenizer),
    )
}
