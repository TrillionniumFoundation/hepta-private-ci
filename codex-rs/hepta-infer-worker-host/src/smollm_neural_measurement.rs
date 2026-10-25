//! Bounded observations from actual worker bytes, never caller expectations.
//! These values are historical evidence, not live model or effect authority.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;

use super::Exchange;
use super::Response;
use super::profile::Ready;
use super::profile::SCHEMA;
use crate::smollm_neural_read::Admitted;

#[derive(Default)]
pub(in crate::smollm_neural_read) struct MailboxState {
    pub(in crate::smollm_neural_read) exchange: Option<Exchange>,
    pub(in crate::smollm_neural_read) measurements: Measurements,
    pub(in crate::smollm_neural_read) first_failure: Option<super::SmolLmFirstExchangeFailureV1>,
}

#[derive(Default)]
pub(in crate::smollm_neural_read) struct Measurements {
    available: bool,
    ready: Option<SmolLmMeasuredLoadV1>,
    forward: Option<SmolLmMeasuredForwardV1>,
}

/// Actual worker Ready roots, bound to its original settled control load.
/// No raw upstream model-file digest is returned by the current worker protocol.
#[derive(Debug)]
pub struct SmolLmMeasuredLoadV1 {
    ready_digest: Digest32,
    parameter_file_digest: Digest32,
    adapter_digest: Digest32,
    contract_digest: Digest32,
    backbone_digest: Digest32,
    tokenizer_digest: Digest32,
    generation: u64,
    sources: BTreeMap<String, Digest32>,
    load_ids: Option<(String, String)>,
}

/// Last actual forward that passed the original admission and terminal settle.
#[derive(Debug)]
pub struct SmolLmMeasuredForwardV1 {
    ready_digest: Digest32,
    request_id: String,
    reservation_id: String,
    response_digest: Digest32,
    input_digest: Digest32,
    logits_digest: Digest32,
    execution_ns: u64,
    input_tokens: usize,
    observed_rss_bytes: u64,
}

/// A borrowed proof of the fixed initial backbone/tokenizer/contract only.
/// Matching selected positive-zero parameters and all installation gates remain
/// required. This cannot certify that a trained adapter is initial material.
pub struct SmolLmFixedInitialBackboneProofV1<'a> {
    measured: &'a SmolLmMeasuredLoadV1,
}

impl SmolLmMeasuredLoadV1 {
    pub fn ready_digest(&self) -> Digest32 {
        self.ready_digest
    }
    pub fn parameter_file_digest(&self) -> Digest32 {
        self.parameter_file_digest
    }
    pub fn adapter_digest(&self) -> Digest32 {
        self.adapter_digest
    }
    pub fn contract_digest(&self) -> Digest32 {
        self.contract_digest
    }
    pub fn backbone_digest(&self) -> Digest32 {
        self.backbone_digest
    }
    pub fn tokenizer_digest(&self) -> Digest32 {
        self.tokenizer_digest
    }
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn sources(&self) -> &BTreeMap<String, Digest32> {
        &self.sources
    }
    pub fn control_load_ids(&self) -> Option<(&str, &str)> {
        self.load_ids
            .as_ref()
            .map(|(request, reservation)| (request.as_str(), reservation.as_str()))
    }

    /// Check code-fixed roots against actual Ready values, not supplied pins.
    pub fn fixed_initial_backbone(&self) -> Result<SmolLmFixedInitialBackboneProofV1<'_>, String> {
        if self.load_ids.is_none()
            || self.backbone_digest.to_string()
                != "c320c094769446c21d7e4a33795d7f9310b5e4c8ca5a6fecca40207b1f735b7c"
            || self.tokenizer_digest.to_string()
                != "a1883207efeacecee399f4dc699d2b547eb2d6ddb7500522933ed76c1521fb93"
            || self.contract_digest.to_string()
                != "2bb480a2becd44b7f4e4b03e557e270ed92a4bb952e0a634562d23d7f0f97e46"
        {
            return Err(
                "actual Ready does not prove the fixed initial backbone profile".to_owned(),
            );
        }
        Ok(SmolLmFixedInitialBackboneProofV1 { measured: self })
    }
}

impl SmolLmFixedInitialBackboneProofV1<'_> {
    pub fn measured(&self) -> &SmolLmMeasuredLoadV1 {
        self.measured
    }
}

impl SmolLmMeasuredForwardV1 {
    pub fn ready_digest(&self) -> Digest32 {
        self.ready_digest
    }
    pub fn control_ids(&self) -> (&str, &str) {
        (&self.request_id, &self.reservation_id)
    }
    pub fn response_digest(&self) -> Digest32 {
        self.response_digest
    }
    pub fn input_digest(&self) -> Digest32 {
        self.input_digest
    }
    pub fn logits_digest(&self) -> Digest32 {
        self.logits_digest
    }
    pub fn execution_ns(&self) -> u64 {
        self.execution_ns
    }
    pub fn input_tokens(&self) -> usize {
        self.input_tokens
    }
    pub fn observed_rss_bytes(&self) -> u64 {
        self.observed_rss_bytes
    }
}

fn digest(value: &str) -> Result<Digest32, String> {
    let parsed = value
        .parse::<Digest32>()
        .map_err(|error| error.to_string())?;
    Ok(parsed)
}

impl Measurements {
    // Called only after the original complete Ready checks and startup deadline.
    pub(super) fn retain_ready(&mut self, raw: &[u8]) -> Result<(), String> {
        self.available = false;
        self.ready = None;
        self.forward = None;
        if raw.len() > 65536 {
            return Err("Ready measurement bound".to_owned());
        }
        let ready: Ready = serde_json::from_slice(raw).map_err(|error| error.to_string())?;
        let mut sources = ready
            .source_pins
            .iter()
            .map(|(name, value)| Ok((name.clone(), digest(value)?)))
            .collect::<Result<BTreeMap<_, _>, String>>()?;
        if sources
            .insert(
                "llm_neural_read_worker.py".to_owned(),
                digest(&ready.worker_source)?,
            )
            .is_some()
            || ready.schema != SCHEMA
            || !ready.authority.denied()
            || ready.generation == 0
            || ready.observed_rss_bytes == 0
        {
            return Err("incomplete actual Ready measurement".to_owned());
        }
        self.ready = Some(SmolLmMeasuredLoadV1 {
            ready_digest: Digest32::of_bytes(raw),
            parameter_file_digest: digest(&ready.file_sha256)?,
            adapter_digest: digest(&ready.actual_loaded_parent)?,
            contract_digest: digest(&ready.contract)?,
            backbone_digest: digest(&ready.backbone)?,
            tokenizer_digest: digest(&ready.tokenizer)?,
            generation: ready.generation,
            sources,
            load_ids: None,
        });
        Ok(())
    }

    pub(in crate::smollm_neural_read) fn settle_load(&mut self, admitted: &Admitted) {
        if let Some(ready) = &mut self.ready
            && ready.load_ids.is_none()
        {
            ready.load_ids = Some((admitted.request_id.clone(), admitted.reservation_id.clone()));
            self.available = true;
        }
    }

    pub(in crate::smollm_neural_read) fn clear_forward(&mut self) {
        self.forward = None;
    }
    pub(in crate::smollm_neural_read) fn suspend(&mut self) {
        self.available = false;
    }
    pub(in crate::smollm_neural_read) fn clear(&mut self) {
        self.available = false;
        self.ready = None;
        self.forward = None;
    }

    pub(in crate::smollm_neural_read) fn retain_forward(
        &mut self,
        admitted: &Admitted,
        raw: &[u8],
        receipt: Digest32,
    ) -> Result<(), String> {
        self.forward = None;
        if raw.len() > 128 * 1024 || Digest32::of_bytes(raw) != receipt {
            return Err("actual forward byte receipt mismatch".to_owned());
        }
        let response: Response = serde_json::from_slice(raw).map_err(|error| error.to_string())?;
        let ready = self
            .ready
            .as_ref()
            .ok_or("actual Ready measurement unavailable")?;
        if !self.available
            || ready.load_ids.is_none()
            || response.schema != SCHEMA
            || response.request_id != admitted.request_id
            || digest(&response.file_sha256)? != ready.parameter_file_digest
            || digest(&response.artifact)? != ready.adapter_digest
            || digest(&response.contract)? != ready.contract_digest
            || !response.authority.denied()
            || receipt.is_zero()
            || response.execution_ns == 0
            || response.input_tokens == 0
            || response.observed_rss_bytes == 0
        {
            return Err("forward observation differs from original loaded execution".to_owned());
        }
        self.forward = Some(SmolLmMeasuredForwardV1 {
            ready_digest: ready.ready_digest,
            request_id: response.request_id.clone(),
            reservation_id: admitted.reservation_id.clone(),
            response_digest: receipt,
            input_digest: digest(&response.input_sha256)?,
            logits_digest: digest(&response.logits_sha256)?,
            execution_ns: response.execution_ns,
            input_tokens: response.input_tokens,
            observed_rss_bytes: response.observed_rss_bytes,
        });
        Ok(())
    }

    pub(in crate::smollm_neural_read) fn observe<T>(
        &self,
        consume: impl FnOnce(&SmolLmMeasuredLoadV1, Option<&SmolLmMeasuredForwardV1>) -> T,
    ) -> Result<T, String> {
        let ready = self
            .ready
            .as_ref()
            .filter(|ready| self.available && ready.load_ids.is_some())
            .ok_or("original settled load measurement unavailable")?;
        Ok(consume(ready, self.forward.as_ref()))
    }
}

#[cfg(test)]
#[path = "smollm_neural_measurement_tests.rs"]
mod tests;
