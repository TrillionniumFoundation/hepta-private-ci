//! Explicit, qualification-only bridge from legacy ModelDriver to shared Stem + Cell heads.
//!
//! No production call site instantiates this type. Callers must register every
//! full base/head/normalization tuple and supply a bounded resource grant.
//! The driver reports WORKER-WIDE resident memory, not per-Cell cloned weights.

use std::collections::BTreeMap;

use crate::composition::{
    CompositionDriver, CompositionError, CompositionKey, CompositionManifestV1,
    CompositionRequest, CompositionWorker,
};
use crate::model_worker::{
    DriverModelHandle, DriverRunObservation, Error, ModelDriver, ModelManifest,
    ResourceGrant, WorkerRequest,
};

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
        worker: CompositionWorker<D>,
        grant: &ResourceGrant,
    ) -> Result<Self, Error> {
        if grant.revoked
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
            || self.registered.values().any(|existing| {
                existing.composition.cell_id == composition.cell_id
            })
        {
            return Err(Error::ModelAlreadyLoaded);
        }
        self.registered.insert(
            model.model_id.clone(),
            Binding { model, composition },
        );
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
        let next = self.next_handle.checked_add(1).ok_or(Error::ArithmeticOverflow)?;
        self.worker
            .attach_manifest(binding.composition.clone())
            .map_err(map_error)?;
        let actual = self.worker.total_resident_memory_bytes().map_err(map_error)?;
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
        let active = self.active.get(&model_id).ok_or(Error::ModelNotLoaded)?.clone();
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
mod tests {
    use std::cell::RefCell;
    use std::rc::Rc;

    use super::*;
    use crate::composition::{
        CellHeadManifest, CompositionKey, CompositionRunObservation, SharedEncoderPool,
    };

    #[derive(Default)]
    struct Counters {
        loads: u32,
        unloads: u32,
        runs: u32,
    }

    struct CountingDriver {
        counters: Rc<RefCell<Counters>>,
    }

    impl CompositionDriver for CountingDriver {
        type Handle = String;

        fn load_encoder(&mut self, key: &CompositionKey) -> Result<String, CompositionError> {
            self.counters.borrow_mut().loads += 1;
            Ok(key.weights_digest.clone())
        }

        fn unload_encoder(
            &mut self,
            _key: &CompositionKey,
            _handle: String,
        ) -> Result<(), CompositionError> {
            self.counters.borrow_mut().unloads += 1;
            Ok(())
        }

        fn run_head(
            &mut self,
            _handle: &String,
            head: &CellHeadManifest,
            request: &CompositionRequest,
        ) -> Result<CompositionRunObservation, CompositionError> {
            assert_eq!(head.cell_id, request.cell_id);
            self.counters.borrow_mut().runs += 1;
            Ok(CompositionRunObservation {
                output_digest: "e".repeat(64),
                consumed_tokens: request.maximum_tokens,
            })
        }
    }

    fn model(model_id: &str) -> ModelManifest {
        ModelManifest {
            model_id: model_id.to_owned(),
            model_digest: "a".repeat(64),
            weights_digest: "b".repeat(64),
            tokenizer_digest: "c".repeat(64),
            preprocessor_digest: "d".repeat(64),
            quantization_digest: "1".repeat(64),
            runtime_digest: "2".repeat(64),
            device_digest: "3".repeat(64),
            maximum_tokens: 128,
        }
    }

    fn composition(value: &ModelManifest, cell_id: &str) -> CompositionManifestV1 {
        CompositionManifestV1::from_model_manifest(
            value,
            cell_id.to_owned(),
            "4".repeat(64),
            "5".repeat(64),
            100,
            20,
        )
    }

    fn adapter(
        maximum_memory_bytes: u64,
    ) -> (CompositionModelDriverAdapter<CountingDriver>, Rc<RefCell<Counters>>) {
        let counters = Rc::new(RefCell::new(Counters::default()));
        let worker = CompositionWorker::new(
            SharedEncoderPool::new(2, 8).expect("pool"),
            CountingDriver {
                counters: counters.clone(),
            },
        );
        let grant = ResourceGrant {
            grant_id: "grant.1".into(),
            authority_epoch: 1,
            generation: 1,
            expires_at_ms: 100_000,
            revoked: false,
            maximum_models: 8,
            maximum_active_requests: 8,
            maximum_memory_bytes,
            semantic_digest: "6".repeat(64),
        };
        (
            CompositionModelDriverAdapter::new_qualification(worker, &grant)
                .expect("qualification"),
            counters,
        )
    }

    fn request() -> WorkerRequest {
        WorkerRequest {
            request_id: "request.1".into(),
            reservation_id: "reservation.1".into(),
            model_digest: "a".repeat(64),
            payload_digest: "7".repeat(64),
            maximum_tokens: 16,
            deadline_ms: 1000,
            lease_payload_digest: "7".repeat(64),
            reservation_model_digest: "a".repeat(64),
            reservation_maximum_tokens: 16,
            cancelled: false,
        }
    }

    #[test]
    fn one_encoder_two_heads_and_worker_wide_memory_receipts() {
        let (mut adapter, counts) = adapter(140);
        let model_a = model("model.a");
        let model_b = model("model.b");
        adapter.register_qualification_binding(
            model_a.clone(), composition(&model_a, "cell.a")
        ).expect("register a");
        adapter.register_qualification_binding(
            model_b.clone(), composition(&model_b, "cell.b")
        ).expect("register b");
        let a = adapter.load(&model_a).expect("load a");
        assert_eq!(a.observed_memory_bytes, 120);
        let b = adapter.load(&model_b).expect("load b");
        assert_eq!(b.observed_memory_bytes, 140);
        assert_eq!(adapter.resident_encoder_count(), 1);
        assert_eq!(counts.borrow().loads, 1);
        let observed = adapter.run(&b, &request()).expect("run b");
        assert_eq!(observed.observed_memory_bytes, 140);
        assert_eq!(observed.output_digest, Some("e".repeat(64)));
        assert_eq!(counts.borrow().runs, 1);
        adapter.unload(a).expect("unload a");
        assert_eq!(counts.borrow().unloads, 0);
        adapter.unload(b).expect("unload b");
        assert_eq!(counts.borrow().unloads, 1);
        assert_eq!(adapter.active_model_count(), 0);
    }

    #[test]
    fn grant_blocks_third_head_before_any_mutation() {
        let (mut adapter, counts) = adapter(140);
        let mut handles = Vec::new();
        for i in 0..3 {
            let m = model(&format!("model.{i}"));
            adapter.register_qualification_binding(
                m.clone(), composition(&m, &format!("cell.{i}"))
            ).expect("register");
            if i < 2 {
                handles.push(adapter.load(&m).expect("load"));
            } else {
                assert_eq!(adapter.load(&m), Err(Error::ModelCapacity));
            }
        }
        assert_eq!(adapter.active_model_count(), 2);
        assert_eq!(adapter.resident_encoder_count(), 1);
        assert_eq!(counts.borrow().loads, 1);
        for handle in handles {
            adapter.unload(handle).expect("unload");
        }
        assert_eq!(counts.borrow().unloads, 1);
    }

    #[test]
    fn mismatched_explicit_binding_rejected() {
        let (mut adapter, _) = adapter(140);
        let m = model("model.a");
        let mut c = composition(&m, "cell.a");
        c.runtime_digest = "9".repeat(64);
        assert_eq!(
            adapter.register_qualification_binding(m, c),
            Err(Error::ModelMismatch)
        );
    }

    #[test]
    fn fake_handle_and_mismatched_request_are_denied() {
        let (mut adapter, _) = adapter(140);
        let m = model("model.a");
        adapter.register_qualification_binding(
            m.clone(), composition(&m, "cell.a")
        ).expect("register");
        let handle = adapter.load(&m).expect("load");
        let fake = DriverModelHandle {
            opaque_id: "composition.handle.999".into(),
            observed_memory_bytes: 120,
        };
        assert_eq!(adapter.run(&fake, &request()), Err(Error::ModelNotLoaded));
        let mut wrong = request();
        wrong.model_digest = "f".repeat(64);
        assert_eq!(adapter.run(&handle, &wrong), Err(Error::ModelMismatch));
        let mut cancelled = request();
        cancelled.cancelled = true;
        assert_eq!(adapter.run(&handle, &cancelled), Err(Error::FeatureContract));
        adapter.unload(handle).expect("unload");
    }
}
