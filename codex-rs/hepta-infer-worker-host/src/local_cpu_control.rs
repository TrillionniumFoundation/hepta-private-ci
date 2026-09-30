//! Physical CPU dispatch and original feature receipts share the existing
//! inference.control owner. Grant provisioning and artifact admission belong
//! to the installed Fleet and learning owners.
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::feature::DEFAULT_FEATURE_COLD_BYTE_LIMIT;
use codex_hepta_infer_core::durable_control::feature::FeatureHistoryMaintenanceReceipt;
use codex_hepta_infer_core::durable_control::feature::FeatureOperationStateV1;
use codex_hepta_neuron::DurableNeuronFeatureResolutionV2;
use codex_hepta_neuron::DurableNeuronInferenceControlPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_types::Digest32;

use crate::local_cpu_model::CpuNeuronModelDriver;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelManifest;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::WorkerRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;

#[derive(Clone)]
pub struct CpuNeuronControlConfigV1 {
    pub worker_id: String,
    pub generation: u64,
    pub grant: ResourceGrant,
    pub maximum_request_duration: Duration,
}

pub struct CpuNeuronInferenceControlV1 {
    worker: InferenceWorker<CpuNeuronModelDriver>,
    control: Arc<Mutex<DurableInferenceControl>>,
    manifest: ModelManifest,
    encoder: String,
    head: String,
    input_width: usize,
    output_width: usize,
    generation: u64,
    maximum_request_duration: Duration,
    clock: Arc<dyn AuthorityClock>,
}

impl CpuNeuronInferenceControlV1 {
    /// The caller supplies the real resource grant and protected clock. This
    /// constructor neither issues a grant nor qualifies the installed model.
    pub fn open(
        control: DurableInferenceControl,
        clock: Arc<dyn AuthorityClock>,
        installed_manifest: &Path,
        manifest_digest: Digest32,
        config: CpuNeuronControlConfigV1,
    ) -> Result<Self, crate::model_worker::Error> {
        Self::open_shared(
            Arc::new(Mutex::new(control)),
            clock,
            installed_manifest,
            manifest_digest,
            config,
        )
    }

    /// Multiple current/candidate/rollback generations borrow this sole journal
    /// owner. Each dispatch remains fenced under its original operation ID.
    pub fn open_shared(
        control: Arc<Mutex<DurableInferenceControl>>,
        clock: Arc<dyn AuthorityClock>,
        installed_manifest: &Path,
        manifest_digest: Digest32,
        config: CpuNeuronControlConfigV1,
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
        let mut worker = InferenceWorker::new(
            now,
            config.worker_id,
            config.generation,
            config.grant,
            driver,
        )?;
        worker.load_model(now, manifest.clone())?;
        Ok(Self {
            worker,
            control,
            manifest,
            encoder,
            head,
            input_width,
            output_width,
            generation: config.generation,
            maximum_request_duration: config.maximum_request_duration,
            clock,
        })
    }

    pub fn manifest(&self) -> &ModelManifest {
        &self.manifest
    }

    /// This is the same exclusive control owner used for physical dispatch.
    /// A full cold budget stops new work while original receipts remain usable.
    pub fn maintain_history(
        &self,
        maximum_records: usize,
        cold_limit_bytes: u64,
        budget: Duration,
    ) -> Result<FeatureHistoryMaintenanceReceipt, codex_hepta_infer_core::durable_control::Error>
    {
        self.control
            .try_lock()
            .map_err(|_| codex_hepta_infer_core::durable_control::Error::WriterUnavailable)?
            .maintain_feature_history(maximum_records, cold_limit_bytes, budget)
    }
}

impl NeuronInferenceControlPort for CpuNeuronInferenceControlV1 {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        if request.request_id.as_str().len() > 128
            || request.generation.get() != self.generation
            || request.model_id.as_str() != self.manifest.model_id
            || request.weights_digest.to_string() != self.manifest.weights_digest
            || request.encoder_digest.to_string() != self.encoder
            || request.head_digest.to_string() != self.head
            || request.feature_vector_q24.len() != self.input_width
            || request.expected_output_width != self.output_width
        {
            return Err(NeuronModelError::Rejected);
        }
        let record = {
            let mut control = self
                .control
                .try_lock()
                .map_err(|_| NeuronModelError::Indeterminate)?;
            match control
                .feature_record(request)
                .map_err(|_| NeuronModelError::Indeterminate)?
            {
                Some(record) => record,
                None => {
                    let threshold = (control.resident_record_capacity() / 2).clamp(1, 64);
                    if control.resident_feature_records() >= threshold {
                        let limit = control
                            .feature_history_cold_byte_limit()
                            .unwrap_or(DEFAULT_FEATURE_COLD_BYTE_LIMIT);
                        control
                            .maintain_feature_history(8, limit, Duration::from_millis(100))
                            .map_err(|_| NeuronModelError::Indeterminate)?;
                    }
                    control
                        .reserve_feature(request.clone())
                        .map_err(|_| NeuronModelError::Indeterminate)?
                }
            }
        };
        match record.state {
            FeatureOperationStateV1::Observed(receipt) => return Ok(*receipt),
            FeatureOperationStateV1::Dispatched => return Err(NeuronModelError::Indeterminate),
            FeatureOperationStateV1::Reserved => {}
        }
        let now = self
            .clock
            .now_unix_ms()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        let deadline = now
            .checked_add(
                u64::try_from(self.maximum_request_duration.as_millis())
                    .map_err(|_| NeuronModelError::Rejected)?,
            )
            .ok_or(NeuronModelError::Rejected)?;
        let permit = self
            .control
            .try_lock()
            .map_err(|_| NeuronModelError::Indeterminate)?
            .dispatch_feature(request)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        let request = permit.into_request();
        let mut physical = NeuronFeatureRequest {
            authorization: WorkerRequest {
                request_id: request.request_id.to_string(),
                reservation_id: format!(
                    "feature:{}",
                    codex_hepta_infer_core::neuron_feature_request_digest_v1(&request)
                        .map_err(|_| NeuronModelError::Rejected)?
                ),
                model_digest: self.manifest.model_digest.clone(),
                payload_digest: String::new(),
                maximum_tokens: self.manifest.maximum_tokens,
                deadline_ms: deadline,
                lease_payload_digest: String::new(),
                reservation_model_digest: self.manifest.model_digest.clone(),
                reservation_maximum_tokens: self.manifest.maximum_tokens,
                cancelled: false,
            },
            encoder_digest: self.encoder.clone(),
            head_digest: self.head.clone(),
            weights_digest: self.manifest.weights_digest.clone(),
            input_digest: request.input_digest.to_string(),
            feature_vector_q24: request.feature_vector_q24.clone(),
            expected_output_width: request.expected_output_width,
        };
        let digest = canonical_neuron_feature_payload_digest(&physical);
        physical.authorization.payload_digest = digest.clone();
        physical.authorization.lease_payload_digest = digest;
        // Dispatch fsync can outlast the lease or request deadline. Physical
        // worker admission uses the protected current clock at this boundary.
        let now = self
            .clock
            .now_unix_ms()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        let receipt = self
            .worker
            .run_neuron_features_receipt(now, &self.manifest.model_id, physical)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        // A late physical result is still recorded as original truth. The
        // enclosing Neuron owner checks deadlines/authority before result use.
        self.control
            .try_lock()
            .map_err(|_| NeuronModelError::Indeterminate)?
            .observe_feature(&request, &receipt)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        Ok(receipt)
    }
}

impl DurableNeuronInferenceControlPort for CpuNeuronInferenceControlV1 {
    fn reconcile_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<DurableNeuronFeatureResolutionV2, NeuronModelError> {
        let record = self
            .control
            .try_lock()
            .map_err(|_| NeuronModelError::Indeterminate)?
            .feature_record(request)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        Ok(match record.map(|record| record.state) {
            Some(FeatureOperationStateV1::Reserved) => DurableNeuronFeatureResolutionV2::NotStarted,
            Some(FeatureOperationStateV1::Observed(receipt)) => {
                DurableNeuronFeatureResolutionV2::Observed(receipt)
            }
            Some(FeatureOperationStateV1::Dispatched) | None => {
                DurableNeuronFeatureResolutionV2::Unknown
            }
        })
    }
}
