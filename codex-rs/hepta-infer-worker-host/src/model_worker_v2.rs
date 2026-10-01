//! Original Fleet worker identity and CPU model generation remain separate.
use super::*;

impl<D: ModelDriver> InferenceWorker<D> {
    /// The installed V2 worker freezes its real process identity while every
    /// operation asks the existing Root owner for the current original lease.
    pub fn new_with_fleet_resources_v2(
        now_ms: u64,
        resources: std::sync::Arc<crate::FleetWorkerResourcePortV2>,
        driver: D,
    ) -> Result<Self, Error> {
        let worker_id = resources.binding().context.principal_id.clone();
        let generation = resources.binding().worker_generation.get();
        let grant = WorkerResources::Fleet(resources);
        grant.current_limits(now_ms, &worker_id, generation)?;
        Ok(Self {
            worker_id,
            generation,
            grant,
            driver,
            models: BTreeMap::new(),
            active_requests: BTreeMap::new(),
        })
    }
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    /// Model generation is an explicit V2 input. The physical observation still
    /// records the original native worker generation; neither is a Fleet lease generation.
    pub fn run_neuron_features_receipt_for_model_v2(
        &mut self,
        now_ms: u64,
        model_id: &str,
        model_generation: Generation,
        request: NeuronFeatureRequest,
    ) -> Result<NeuronFeatureReceiptV1, Error> {
        let copy = request.clone();
        let observed = self.run_neuron_features(now_ms, model_id, request)?;
        build_feature_receipt(copy, observed, model_generation)
    }
}
