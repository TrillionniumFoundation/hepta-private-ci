//! Typed handoff from the existing generation actor to the learning ledger.
//! This adapter creates no decision, quality value, signature or adoption right.

use codex_hepta_intelligence::FrozenGenerationEpisodeV1;
use codex_hepta_intelligence::GenerationEpisodeErrorV1;
use codex_hepta_intelligence::ObservedOutcomeRequestV2;
use codex_hepta_intelligence::OutcomeCreditClosureReceiptV2;
use codex_hepta_intelligence::OutcomeCreditClosureRequestV2;
use codex_hepta_intelligence::append_generation_outcome_credit_v1;
use codex_hepta_intelligence::append_generation_outcome_v1;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::LedgerWriter;

use crate::NeuronGenerationRuntimeHandleV2;

/// Sample one healthy owner cut, then submit its already independently signed
/// outcome through the existing LedgerWriter. If the sampled costs or delivery
/// differ from the signed observation, the support digest differs and nothing is appended.
///
/// The sample and ledger append are separate owner operations. This records a
/// fact about the sampled cut; it does not claim that cut remains the latest at
/// append time, freeze the generation owner, or make a cross-owner transaction.
/// Exact retries retain the original request and the ledger's idempotent receipt.
pub async fn append_neuron_generation_outcome_v1(
    generation: &NeuronGenerationRuntimeHandleV2,
    ledger: &mut LedgerWriter,
    frozen: &FrozenGenerationEpisodeV1,
    request: ObservedOutcomeRequestV2,
    now: u64,
) -> Result<AppendReceipt, GenerationEpisodeErrorV1> {
    let observation = generation
        .observe_generation()
        .await
        .map_err(GenerationEpisodeErrorV1::Generation)?;
    append_generation_outcome_v1(ledger, frozen, &observation, request, now)
}

/// Record terminal utility and credit for one settled, delivered actor cut.
/// Both independent signatures must come from the existing learning owners.
/// A failure after Outcome commit returns its original durable receipt; retrying
/// the same request on the same cut appends no duplicate Outcome or credit.
///
/// Like the Outcome-only adapter, this samples the actor and then appends to the
/// ledger. It does not create an atomic cross-owner transaction or freeze costs.
/// Later owner changes require a newly authenticated observation/correction;
/// stale support is never silently rebound to a different generation cut.
pub async fn append_neuron_generation_outcome_credit_v1(
    generation: &NeuronGenerationRuntimeHandleV2,
    ledger: &mut LedgerWriter,
    frozen: &FrozenGenerationEpisodeV1,
    request: OutcomeCreditClosureRequestV2,
    now: u64,
) -> Result<OutcomeCreditClosureReceiptV2, GenerationEpisodeErrorV1> {
    let observation = generation
        .observe_generation()
        .await
        .map_err(GenerationEpisodeErrorV1::Generation)?;
    append_generation_outcome_credit_v1(ledger, frozen, &observation, request, now)
}
