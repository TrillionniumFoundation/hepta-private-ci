//! Explicit, qualification-only bridge from legacy ModelDriver to shared Stem + Cell heads.
//!
//! No production call site instantiates this type. Callers must register every
//! full base/head/normalization tuple and supply a bounded resource grant.
//! The driver reports WORKER-WIDE resident memory, not per-Cell cloned weights.

use std::collections::BTreeMap;

use crate::composition::CompositionDriver;
use crate::composition::CompositionError;
use crate::composition::CompositionKey;
use crate::composition::CompositionManifestV1;
use crate::composition::CompositionRequest;
use crate::composition::CompositionWorker;
use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::WorkerRequest;

#[derive(Clone)]
struct Binding {
    model: ModelManifest,
    composition: CompositionManifestV1,
}

#[derive(Clone)]
struct ActiveBinding {
    binding: Binding,
    handle: DriverModelHandle,
}

/// Opt-in verification bridge. Does NOT change InferenceWorker's default loader.
/// The authoritative total resident memory must still be verified by the
/// underlying driver's real allocation receipts before production selection.
pub struct CompositionModelDriverAdapter<D: CompositionDriver> {
    worker: CompositionWorker<D>,
    registered: BTreeMap<String, Binding>,
    active: BTreeMap<String, ActiveBinding>,
    maximum_memory_bytes: u64,
    maximum_models: usize,
    next_handle: u64,
}

impl<D: CompositionDriver> CompositionModelDriverAdapter<D> {
    /// Construction is explicit and requires a nonrevoked, generation-bound
    /// resource grant; actual grant expiry remains owned by InferenceWorker.
    pub fn new_qualification(
        now_ms: u64,
        worker: CompositionWorker<D>,
        grant: &ResourceGrant,
    ) -> Result<Self, Error> {
        if grant.revoked {
            return Err(Error::GrantRevoked);
        }
        if now_ms >= grant.expires_at_ms {
            return Err(Error::GrantExpired);
        }
        if !valid_id(&grant.grant_id)
            || !valid_digest(&grant.semantic_digest)
            || grant.authority_epoch == 0
            || grant.generation == 0
            || grant.maximum_memory_bytes == 0
            || grant.maximum_models == 0
            || grant.maximum_active_requests == 0
        {
            return Err(Error::InvalidGrant);
        }
        Ok(Self {
            worker,
            registered: BTreeMap::new(),
            active: BTreeMap::new(),
            maximum_memory_bytes: grant.maximum_memory_bytes,
            maximum_models: grant.maximum_models.min(8),
            next_handle: 0,
        })
    }

    /// ModelDriver::load has no place to convey normalization, Cell head,
    /// private bytes, or explicit shared bytes. Register them here; never
    /// fabricate them from a base ModelManifest or a prompt.
    pub fn register_qualification_binding(
        &mut self,
        model: ModelManifest,
        composition: CompositionManifestV1,
    ) -> Result<(), Error> {
        composition.validate().map_err(map_error)?;
        if !valid_id(&model.model_id)
            || model.maximum_tokens == 0
            || model.maximum_tokens > 1_000_000
            || composition.shared_memory_bytes == 0
            || !valid_digest(&composition.normalization_digest)
            || !valid_digest(&composition.head_digest)
            || [
                &model.model_digest,
                &model.weights_digest,
                &model.tokenizer_digest,
                &model.preprocessor_digest,
                &model.quantization_digest,
                &model.runtime_digest,
                &model.device_digest,
            ]
            .iter()
            .any(|digest| !valid_digest(digest))
        {
            return Err(Error::InvalidManifest);
        }
        if composition.encoder_digest != model.model_digest
            || composition.weights_digest != model.weights_digest
            || composition.tokenizer_digest != model.tokenizer_digest
            || composition.preprocessor_digest != model.preprocessor_digest
            || composition.quantization_digest != model.quantization_digest
            || composition.runtime_digest != model.runtime_digest
            || composition.device_digest != model.device_digest
            || composition.maximum_tokens != model.maximum_tokens
        {
            return Err(Error::ModelMismatch);
        }
        if self.registered.contains_key(&model.model_id)
            || self
                .registered
                .values()
                .any(|existing| existing.composition.cell_id == composition.cell_id)
        {
            return Err(Error::ModelAlreadyLoaded);
        }
        self.registered
            .insert(model.model_id.clone(), Binding { model, composition });
        Ok(())
    }

    pub fn active_model_count(&self) -> usize {
        self.active.len()
    }

    pub fn resident_encoder_count(&self) -> usize {
        self.worker.resident_encoder_count()
    }

    /// A single shareable encoder is charged once for its exact CompositionKey,
    /// while every private Cell head is charged once. Checked arithmetic only.
    fn expected_memory_with(
        &self,
        candidate: Option<&CompositionManifestV1>,
    ) -> Result<u64, Error> {
        let mut shared: BTreeMap<CompositionKey, u64> = BTreeMap::new();
        let mut private = 0_u64;
        let active = self
            .active
            .values()
            .map(|item| &item.binding.composition)
            .chain(candidate);
        for manifest in active {
            let key = manifest.key();
            if let Some(previous) = shared.insert(key, manifest.shared_memory_bytes) {
                if previous != manifest.shared_memory_bytes {
                    return Err(Error::ModelMismatch);
                }
            }
            private = private
                .checked_add(manifest.private_memory_bytes)
                .ok_or(Error::ArithmeticOverflow)?;
        }
        shared.values().try_fold(private, |total, bytes| {
            total.checked_add(*bytes).ok_or(Error::ArithmeticOverflow)
        })
    }

    fn observed_memory(&self) -> Result<u64, Error> {
        let observed = self
            .worker
            .total_resident_memory_bytes()
            .map_err(map_error)?;
        if observed != self.expected_memory_with(None)? {
            return Err(Error::FeatureContract);
        }
        if observed > self.maximum_memory_bytes {
            return Err(Error::ModelCapacity);
        }
        Ok(observed)
    }
}

impl<D: CompositionDriver> ModelDriver for CompositionModelDriverAdapter<D> {
    fn load(&mut self, model: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.active.contains_key(&model.model_id) {
            return Err(Error::ModelAlreadyLoaded);
        }
        if self.active.len() >= self.maximum_models {
            return Err(Error::ModelCapacity);
        }
        let binding = self
            .registered
            .get(&model.model_id)
            .ok_or(Error::InvalidManifest)?
            .clone();
        if binding.model != *model {
            return Err(Error::ModelMismatch);
        }
        // Check both the logical total and physical pool before touching state.
        self.observed_memory()?;
        let projected = self.expected_memory_with(Some(&binding.composition))?;
        if projected > self.maximum_memory_bytes {
            return Err(Error::ModelCapacity);
        }
        let next = self
            .next_handle
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.worker
            .attach_manifest(binding.composition.clone())
            .map_err(map_error)?;
        let actual = self
            .worker
            .total_resident_memory_bytes()
            .map_err(map_error)?;
        if actual != projected {
            self.worker
                .detach_cell(&binding.composition.cell_id)
                .map_err(map_error)?;
            return Err(Error::FeatureContract);
        }
        let handle = DriverModelHandle {
            opaque_id: format!("composition.handle.{next}"),
            // This is a WORKER-WIDE total. It is not a private per-Cell charge.
            observed_memory_bytes: actual,
        };
        self.next_handle = next;
        self.active.insert(
            model.model_id.clone(),
            ActiveBinding {
                binding,
                handle: handle.clone(),
            },
        );
        Ok(handle)
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        let active = self
            .active
            .values()
            .find(|entry| entry.handle.opaque_id == handle.opaque_id)
            .ok_or(Error::ModelNotLoaded)?
            .clone();
        if active.handle != *handle
            || request.model_digest != active.binding.model.model_digest
            || request.reservation_model_digest != active.binding.model.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        if !valid_digest(&request.payload_digest)
            || request.payload_digest != request.lease_payload_digest
        {
            return Err(Error::PayloadMismatch);
        }
        if request.cancelled {
            // Cancellation is owned by InferenceWorker and must never be
            // represented as a successful backend execution.
            return Err(Error::FeatureContract);
        }
        if request.maximum_tokens == 0
            || request.maximum_tokens > active.binding.composition.maximum_tokens
            || request.maximum_tokens > request.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        self.observed_memory()?;
        let observed = self
            .worker
            .run(CompositionRequest {
                cell_id: active.binding.composition.cell_id,
                input_digest: request.payload_digest.clone(),
                maximum_tokens: request.maximum_tokens,
            })
            .map_err(map_error)?;
        if !valid_digest(&observed.output_digest) {
            return Err(Error::MissingTerminalOutput);
        }
        if observed.consumed_tokens > request.maximum_tokens {
            return Err(Error::TokenLimit);
        }
        let total = self.observed_memory()?;
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: true,
            output_digest: Some(observed.output_digest),
            consumed_tokens: observed.consumed_tokens,
            observed_memory_bytes: total,
        })
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        let model_id = self
            .active
            .iter()
            .find(|(_, entry)| entry.handle.opaque_id == handle.opaque_id)
            .map(|(id, _)| id.clone())
            .ok_or(Error::ModelNotLoaded)?;
        let active = self
            .active
            .get(&model_id)
            .ok_or(Error::ModelNotLoaded)?
            .clone();
        if active.handle != handle {
            return Err(Error::ModelMismatch);
        }
        self.observed_memory()?;
        self.worker
            .detach_cell(&active.binding.composition.cell_id)
            .map_err(map_error)?;
        self.active.remove(&model_id);
        self.observed_memory()?;
        Ok(())
    }
}

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn map_error(error: CompositionError) -> Error {
    match error {
        CompositionError::ArithmeticOverflow => Error::ArithmeticOverflow,
        CompositionError::InvalidTokens => Error::TokenLimit,
        other => Error::DriverFailure(format!("composition: {other}")),
    }
}

#[cfg(test)]
#[allow(clippy::expect_used)]
#[path = "composition_model_adapter_tests.rs"]
mod tests;
