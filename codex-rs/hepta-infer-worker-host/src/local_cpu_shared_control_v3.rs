//! Goal scopes share the loaded physical worker and its original control owner.
//! Taking the worker out of its slot releases the short mutex before dispatch;
//! a competing scope reports unavailable without opening a second worker.
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::DurableNeuronFeatureResolutionV2;
use codex_hepta_neuron::DurableNeuronInferenceControlPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronRuntimeConfigV1;

use super::CpuNeuronInferenceControlV1;

#[derive(Clone)]
pub struct SharedCpuNeuronInferenceControlV3 {
    physical: Arc<Mutex<Option<CpuNeuronInferenceControlV1>>>,
}

struct PhysicalLease {
    owner: Arc<Mutex<Option<CpuNeuronInferenceControlV1>>>,
    physical: Option<CpuNeuronInferenceControlV1>,
}

impl SharedCpuNeuronInferenceControlV3 {
    /// Move an already loaded worker into the sole shared owner. This neither
    /// loads another model nor opens or grants a journal or resource lease.
    pub fn new(physical: CpuNeuronInferenceControlV1) -> Self {
        Self {
            physical: Arc::new(Mutex::new(Some(physical))),
        }
    }

    fn borrow(&self) -> Result<PhysicalLease, NeuronModelError> {
        let physical = self
            .physical
            .try_lock()
            .map_err(|_| NeuronModelError::Unavailable)?
            .take()
            .ok_or(NeuronModelError::Unavailable)?;
        Ok(PhysicalLease {
            owner: Arc::clone(&self.physical),
            physical: Some(physical),
        })
    }

    pub(crate) fn validate_runtime(
        &self,
        runtime: &NeuronRuntimeConfigV1,
    ) -> Result<(), NeuronModelError> {
        self.borrow()?
            .physical
            .as_ref()
            .ok_or(NeuronModelError::Unavailable)?
            .validate_runtime(runtime)
            .map_err(|_| NeuronModelError::Rejected)
    }
}

impl Drop for PhysicalLease {
    fn drop(&mut self) {
        // No caller receives the slot mutex. Recovering poison here preserves
        // the sole physical instance on unwinding; it never manufactures a
        // replacement for an unknown or partially executed dispatch.
        let mut slot = self
            .owner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *slot = self.physical.take();
    }
}

impl NeuronInferenceControlPort for SharedCpuNeuronInferenceControlV3 {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.borrow()?
            .physical
            .as_mut()
            .ok_or(NeuronModelError::Unavailable)?
            .execute_feature(request)
    }
}

impl DurableNeuronInferenceControlPort for SharedCpuNeuronInferenceControlV3 {
    fn reconcile_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<DurableNeuronFeatureResolutionV2, NeuronModelError> {
        self.borrow()?
            .physical
            .as_mut()
            .ok_or(NeuronModelError::Unavailable)?
            .reconcile_feature(request)
    }
}
