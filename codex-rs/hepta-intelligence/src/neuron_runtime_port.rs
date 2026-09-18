//! Authority-free product consumer for canonical neuron runtime signals.
//!
//! Intelligence owns composition, not neuron state. This port invokes the neuron
//! owner's host boundary and converts the returned canonical tick into an
//! advisory/slow-path observation. It cannot write the neuron journal directly
//! and cannot turn a neural signal into effect authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_neuron::FrozenModelExecutor;
use codex_hepta_neuron::LineagePolicy;
use codex_hepta_neuron::NeuronRuntimeHost;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::RecoveryWitnessStore;
use codex_hepta_neuron::RuntimeTickObservationV1;
use codex_hepta_neuron::RuntimeTickResultV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronConsumerDispositionV1 {
    AdvisorySignal,
    SlowPath,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronConsumerReceiptV1 {
    pub tick_id: StableId,
    pub checkpoint_digest: Digest32,
    pub neuron_signal_digest: Digest32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub disposition: NeuronConsumerDispositionV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronConsumerErrorV1 {
    Runtime(String),
    AuthorityViolation,
    ReceiptMismatch,
}

impl fmt::Display for NeuronConsumerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronConsumerErrorV1 {}

pub fn consume_neuron_tick<E, W, L>(
    runtime: &mut NeuronRuntimeHost<E, W, L>,
    input: NeuronTickInputV1,
    observation: RuntimeTickObservationV1,
) -> Result<NeuronConsumerReceiptV1, NeuronConsumerErrorV1>
where
    E: FrozenModelExecutor,
    W: RecoveryWitnessStore,
    L: LineagePolicy,
{
    let expected_tick = input.tick_id.clone();
    let result = runtime
        .tick(input, observation)
        .map_err(|error| NeuronConsumerErrorV1::Runtime(error.to_string()))?;
    convert_runtime_result(expected_tick, result)
}

fn convert_runtime_result(
    expected_tick: StableId,
    result: RuntimeTickResultV1,
) -> Result<NeuronConsumerReceiptV1, NeuronConsumerErrorV1> {
    if result.authority.grants_any()
        || result.sparse_receipt.authority.grants_any()
        || result.tick_receipt.tick_id != expected_tick
        || result.signal_receipt.signal_set_id != expected_tick
        || result.tick_receipt.checkpoint_after != result.signal_receipt.temporal_state_digest
    {
        return Err(
            if result.authority.grants_any() || result.sparse_receipt.authority.grants_any() {
                NeuronConsumerErrorV1::AuthorityViolation
            } else {
                NeuronConsumerErrorV1::ReceiptMismatch
            },
        );
    }
    let signal_digest = digest_signal(&result);
    let disposition = if result.tick_receipt.abstain || result.signal_receipt.abstain {
        NeuronConsumerDispositionV1::SlowPath
    } else {
        NeuronConsumerDispositionV1::AdvisorySignal
    };
    let receipt_digest = digest_consumer_receipt(
        &expected_tick,
        result.tick_receipt.checkpoint_after,
        signal_digest,
        result.tick_receipt.confidence_ppm,
        result.tick_receipt.ood_ppm,
        disposition,
    );
    Ok(NeuronConsumerReceiptV1 {
        tick_id: expected_tick,
        checkpoint_digest: result.tick_receipt.checkpoint_after,
        neuron_signal_digest: signal_digest,
        confidence_ppm: result.tick_receipt.confidence_ppm,
        ood_ppm: result.tick_receipt.ood_ppm,
        disposition,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn digest_signal(result: &RuntimeTickResultV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence.neuron-signal-consumer.v1".to_vec();
    for digest in [
        result.signal_receipt.model_runtime_digest,
        result.signal_receipt.temporal_state_digest,
        result.tick_receipt.activation_digest,
        result.tick_receipt.threshold_digest,
        result.tick_receipt.eligibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&result.signal_receipt.activation_sparsity_ppm.to_be_bytes());
    bytes.extend_from_slice(&result.signal_receipt.ood_ppm.to_be_bytes());
    bytes.push(u8::from(result.signal_receipt.abstain));
    Digest32::of_bytes(&bytes)
}

fn digest_consumer_receipt(
    tick_id: &StableId,
    checkpoint: Digest32,
    signal: Digest32,
    confidence_ppm: u32,
    ood_ppm: u32,
    disposition: NeuronConsumerDispositionV1,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.neuron-consumer-receipt.v1".to_vec();
    let raw = tick_id.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
    bytes.extend_from_slice(checkpoint.as_array());
    bytes.extend_from_slice(signal.as_array());
    bytes.extend_from_slice(&confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&ood_ppm.to_be_bytes());
    bytes.push(match disposition {
        NeuronConsumerDispositionV1::AdvisorySignal => 0,
        NeuronConsumerDispositionV1::SlowPath => 1,
    });
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "neuron_runtime_port_tests.rs"]
mod tests;
