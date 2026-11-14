//! Revalidate the admitted query and actual owners at decoder entry.

use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelOutputV1;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::NeuronTickInputV1;

use super::NativeMemoryContextAuthorityV1;
use super::NativeMemoryModelPort;
use crate::NativeMemoryContextBindingV1;

pub(super) struct NativeCurrentModel<'a, C> {
    pub(super) inner: &'a mut NativeMemoryModelPort,
    pub(super) context: &'a mut C,
    pub(super) input: &'a NeuronTickInputV1,
    pub(super) binding: Option<&'a NativeMemoryContextBindingV1>,
}

impl<C: NativeMemoryContextAuthorityV1> NeuronModelPort for NativeCurrentModel<'_, C> {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let context = &mut *self.context;
        let input = self.input;
        let binding = self.binding;
        self.inner.execute_with_current_guard(request, |query| {
            context
                .validate_query(query)
                .map_err(|error| error.to_string())?;
            let current = context.current().map_err(|error| error.to_string())?;
            if !current.matches(input) || context.binding() != binding {
                return Err("current owners changed before decoder entry".to_string());
            }
            Ok(())
        })
    }
}

#[cfg(all(test, unix))]
#[path = "native_memory_current_model_tests.rs"]
mod tests;
