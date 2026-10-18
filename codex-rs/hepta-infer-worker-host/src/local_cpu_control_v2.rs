//! Installed CPU model generation does not reuse a worker or lease generation.
use super::*;
use codex_hepta_types::Generation;

#[derive(Clone)]
pub struct CpuNeuronControlConfigV2 {
    pub resources: Arc<crate::FleetWorkerResourcePortV2>,
    pub model_generation: Generation,
    pub maximum_request_duration: Duration,
}

impl CpuNeuronInferenceControlV1 {
    /// The journal was opened once by the installed model owner. This CPU
    /// adapter receives the same owner and an authenticated current Fleet port.
    pub fn open_shared_v2(
        control: Arc<tokio::sync::Mutex<DurableInferenceControl>>,
        clock: Arc<dyn AuthorityClock>,
        installed_manifest: &Path,
        manifest_digest: Digest32,
        config: CpuNeuronControlConfigV2,
    ) -> Result<Self, crate::model_worker::Error> {
        if config.maximum_request_duration.is_zero()
            || config.maximum_request_duration > Duration::from_secs(60)
        {
            return Err(crate::model_worker::Error::InvalidGrant);
        }
        let driver = CpuNeuronModelDriver::open(installed_manifest, manifest_digest)?;
        let manifest = driver.manifest().clone();
        let encoder = driver.encoder_digest.clone();
        let head = driver.head_digest.clone();
        let (input_width, output_width) = driver.feature_dimensions()?;
        let now = clock
            .now_unix_ms()
            .map_err(|error| crate::model_worker::Error::DriverFailure(error.to_string()))?;
        let mut worker =
            InferenceWorker::new_with_fleet_resources_v2(now, config.resources, driver)?;
        worker.load_model(now, manifest.clone())?;
        Ok(Self {
            worker,
            control: CpuControlOwner::Shared(control),
            manifest,
            encoder,
            head,
            input_width,
            output_width,
            generation: config.model_generation.get(),
            maximum_request_duration: config.maximum_request_duration,
            clock,
        })
    }
}
