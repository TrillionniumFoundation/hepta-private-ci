//! Durable one-shot native inference; recovery reads the original result.
use crate::model::bits_digest;
use crate::model::decode;
use crate::model::Features;
use crate::model::Head;
use crate::model::WIDTH;
use crate::*;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Observed {
    request_sha256: [u8; 32],
    pub raw_bits_u64: Vec<[u64; 2]>,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub latency_micros: u64,
    memory_bytes: u64,
    transient_bytes: u64,
    receipt_sha256: [u8; 32],
}
impl Observed {
    pub fn raw(&self) -> Vec<[f64; 2]> {
        self.raw_bits_u64
            .iter()
            .map(|v| v.map(f64::from_bits))
            .collect()
    }
}

pub struct Control {
    pub root: PathBuf,
    pub head: Head,
    pub features: Features,
    pub carrier: Vec<i64>,
    pub runtime: NeuronModelRuntimeTupleV1,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub retained_bytes: u64,
    pub executions: usize,
    pub reads: usize,
    pub lose_ack: bool,
}

impl Control {
    fn receipt(
        &self,
        request: &NeuronFeatureRequestV1,
        value: &Observed,
    ) -> Result<NeuronFeatureReceiptV1> {
        if neuron_feature_request_digest_v1(request)?.into_array() != value.request_sha256 {
            return Err("original inference request mismatch".into());
        }
        Ok(build_neuron_feature_receipt_v1(
            request,
            self.runtime.clone(),
            NeuronFeatureObservationV1 {
                encoder_digest: self.encoder_digest,
                head_digest: self.head_digest,
                drive_q24: value.drive_q24.clone(),
                prediction_q24: value.prediction_q24.clone(),
                observed_memory_bytes: value.memory_bytes,
                transient_allocation_bytes: value.transient_bytes,
                queue_age_micros: 0,
                latency_micros: value.latency_micros,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )?)
    }

    pub fn observed(&self) -> Result<Observed> {
        let bytes = read(&self.root.join("head-receipt.json"), 65536)
            .map_err(|_| "original trained output receipt unavailable")?;
        if read(&self.root.join("head-receipt.sha256"), 32)?
            != Digest32::of_bytes(&bytes).as_array()
        {
            return Err("retained inference bytes mismatch".into());
        }
        let value: Observed = serde_json::from_slice(&bytes)?;
        let (drive, prediction, _) = self.features.vectors(&self.head, &value.raw())?;
        if drive != value.drive_q24
            || prediction != value.prediction_q24
            || read(&self.root.join("head-claim.bin"), 32)? != value.request_sha256
        {
            return Err("retained trained output mismatch".into());
        }
        Ok(value)
    }

    pub fn verify_committed(
        &self,
        observed: &Observed,
        committed: &CellDecisionReceiptV1,
    ) -> Result<()> {
        let r = &self.runtime;
        let receipt = LocalModelRuntimeReceiptV1 {
            model_id: r.model_id.clone(),
            model_manifest_digest: r.model_manifest_digest,
            weights_digest: r.weights_digest,
            tokenizer_digest: r.tokenizer_digest,
            preprocessor_digest: r.preprocessor_digest,
            quantization_id: id(&format!("quantization:{}", r.quantization_digest))?,
            quantization_digest: r.quantization_digest,
            backend_id: id(&format!("runtime:{}", r.runtime_digest))?,
            runtime_digest: r.runtime_digest,
            device_identity_digest: r.device_digest,
            latency_micros: observed.latency_micros,
            resident_bytes: observed.memory_bytes,
        };
        if canonical_model_output_digest_v1(
            &observed.drive_q24,
            &observed.prediction_q24,
            &receipt,
        )? != committed.model_output_digest
        {
            return Err("committed trained output mismatch".into());
        }
        Ok(())
    }

    fn execute(&mut self, request: &NeuronFeatureRequestV1) -> Result<NeuronFeatureReceiptV1> {
        if request.encoder_digest != self.encoder_digest
            || request.head_digest != self.head_digest
            || request.weights_digest != self.runtime.weights_digest
            || request.expected_output_width != WIDTH
            || request.feature_vector_q24 != self.carrier
        {
            return Err("native trained head input binding mismatch".into());
        }
        let rows = decode(&request.feature_vector_q24)?;
        if bits_digest(&rows).to_string() != self.features.feature_rows_sha256 {
            return Err("decoded native feature bits mismatch".into());
        }
        let request_sha256 = neuron_feature_request_digest_v1(request)?.into_array();
        write(&self.root.join("head-claim.bin"), &request_sha256)?;
        self.executions += 1;
        let started = Instant::now();
        let raw = self.head.infer(&rows)?;
        let (drive_q24, prediction_q24, _) = self.features.vectors(&self.head, &raw)?;
        let mut value = Observed {
            request_sha256,
            raw_bits_u64: raw.iter().map(|r| r.map(f64::to_bits)).collect(),
            drive_q24,
            prediction_q24,
            latency_micros: u64::try_from(started.elapsed().as_micros())?,
            memory_bytes: self.head.parameter_bytes() + self.retained_bytes,
            transient_bytes: ((rows.iter().map(Vec::len).sum::<usize>()
                + self.carrier.len()
                + WIDTH * 2
                + 512)
                * 8) as u64,
            receipt_sha256: [0; 32],
        };
        let receipt = self.receipt(request, &value)?;
        value.receipt_sha256 = receipt.receipt_digest.into_array();
        let bytes = serde_json::to_vec(&value)?;
        write(&self.root.join("head-receipt.json"), &bytes)?;
        write(
            &self.root.join("head-receipt.sha256"),
            Digest32::of_bytes(&bytes).as_array(),
        )?;
        Ok(receipt)
    }
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> std::result::Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let receipt = self
            .execute(request)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        if self.lose_ack {
            Err(NeuronModelError::Indeterminate)
        } else {
            Ok(receipt)
        }
    }
}
impl CellInferenceReadbackPortV1 for Control {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> std::result::Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.reads += 1;
        let result = (|| -> Result<_> {
            let value = self.observed()?;
            let receipt = self.receipt(request, &value)?;
            if receipt.receipt_digest.into_array() != value.receipt_sha256 {
                return Err("retained inference receipt mismatch".into());
            }
            Ok(receipt)
        })();
        result
            .map(Some)
            .map_err(|_| NeuronModelError::Indeterminate)
    }
}
