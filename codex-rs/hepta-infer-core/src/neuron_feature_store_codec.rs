#[derive(Serialize, Deserialize)]
#[serde(tag = "event", content = "body", rename_all = "snake_case", deny_unknown_fields)]
enum Event {
    Reserve(RequestDto),
    Dispatch {
        request_id: String,
        request_digest: String,
    },
    Observe {
        request_id: String,
        request_digest: String,
        receipt: Box<ReceiptDto>,
    },
}

fn encode_event(event: &Event) -> Result<Vec<u8>, NeuronFeatureStoreError> {
    serde_json::to_vec(event).map_err(|_| NeuronFeatureStoreError::InvalidRecord)
}

fn decode_event(payload: &[u8]) -> Result<Event, NeuronFeatureStoreError> {
    serde_json::from_slice(payload).map_err(|_| NeuronFeatureStoreError::Corrupt)
}

fn apply_event(
    records: &mut BTreeMap<StableId, NeuronFeatureExecutionRecordV1>,
    context: &NeuronFeatureStoreContextV1,
    event: Event,
) -> Result<(), NeuronFeatureStoreError> {
    match event {
        Event::Reserve(dto) => {
            let request = dto.into_request()?;
            if request.generation != context.generation {
                return Err(NeuronFeatureStoreError::Corrupt);
            }
            let digest = request_digest(&request)?;
            if records.contains_key(&request.request_id) || records.len() >= context.max_records {
                return Err(NeuronFeatureStoreError::Corrupt);
            }
            records.insert(
                request.request_id.clone(),
                NeuronFeatureExecutionRecordV1 {
                    request,
                    request_digest: digest,
                    state: NeuronFeatureExecutionStateV1::Reserved,
                    receipt: None,
                },
            );
        }
        Event::Dispatch {
            request_id,
            request_digest,
        } => {
            let request_id = parse_id(&request_id)?;
            let request_digest = parse_digest(&request_digest)?;
            let record = records
                .get_mut(&request_id)
                .ok_or(NeuronFeatureStoreError::Corrupt)?;
            if record.request_digest != request_digest
                || record.state != NeuronFeatureExecutionStateV1::Reserved
            {
                return Err(NeuronFeatureStoreError::Corrupt);
            }
            record.state = NeuronFeatureExecutionStateV1::Dispatched;
        }
        Event::Observe {
            request_id,
            request_digest,
            receipt,
        } => {
            let request_id = parse_id(&request_id)?;
            let request_digest = parse_digest(&request_digest)?;
            let record = records
                .get_mut(&request_id)
                .ok_or(NeuronFeatureStoreError::Corrupt)?;
            if record.request_digest != request_digest
                || record.state != NeuronFeatureExecutionStateV1::Dispatched
            {
                return Err(NeuronFeatureStoreError::Corrupt);
            }
            let receipt = (*receipt).into_receipt()?;
            verify_neuron_feature_receipt_v1(&record.request, &receipt)
                .map_err(|_| NeuronFeatureStoreError::Corrupt)?;
            record.state = state_from_status(receipt.status);
            record.receipt = Some(receipt);
        }
    }
    Ok(())
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RequestDto {
    request_id: String,
    generation: u64,
    model_id: String,
    encoder_digest: String,
    head_digest: String,
    weights_digest: String,
    input_digest: String,
    feature_vector_q24: Vec<i64>,
    expected_output_width: usize,
}

impl RequestDto {
    fn from_request(value: &NeuronFeatureRequestV1) -> Self {
        Self {
            request_id: value.request_id.to_string(),
            generation: value.generation.get(),
            model_id: value.model_id.to_string(),
            encoder_digest: value.encoder_digest.to_string(),
            head_digest: value.head_digest.to_string(),
            weights_digest: value.weights_digest.to_string(),
            input_digest: value.input_digest.to_string(),
            feature_vector_q24: value.feature_vector_q24.clone(),
            expected_output_width: value.expected_output_width,
        }
    }

    fn into_request(self) -> Result<NeuronFeatureRequestV1, NeuronFeatureStoreError> {
        let request = NeuronFeatureRequestV1 {
            request_id: parse_id(&self.request_id)?,
            generation: Generation::new(self.generation)
                .map_err(|_| NeuronFeatureStoreError::Corrupt)?,
            model_id: parse_id(&self.model_id)?,
            encoder_digest: parse_digest(&self.encoder_digest)?,
            head_digest: parse_digest(&self.head_digest)?,
            weights_digest: parse_digest(&self.weights_digest)?,
            input_digest: parse_digest(&self.input_digest)?,
            feature_vector_q24: self.feature_vector_q24,
            expected_output_width: self.expected_output_width,
        };
        request_digest(&request)?;
        Ok(request)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeTupleDto {
    model_id: String,
    model_manifest_digest: String,
    weights_digest: String,
    tokenizer_digest: String,
    preprocessor_digest: String,
    quantization_digest: String,
    runtime_digest: String,
    device_digest: String,
}

impl RuntimeTupleDto {
    fn from_tuple(value: &NeuronModelRuntimeTupleV1) -> Self {
        Self {
            model_id: value.model_id.to_string(),
            model_manifest_digest: value.model_manifest_digest.to_string(),
            weights_digest: value.weights_digest.to_string(),
            tokenizer_digest: value.tokenizer_digest.to_string(),
            preprocessor_digest: value.preprocessor_digest.to_string(),
            quantization_digest: value.quantization_digest.to_string(),
            runtime_digest: value.runtime_digest.to_string(),
            device_digest: value.device_digest.to_string(),
        }
    }

    fn into_tuple(self) -> Result<NeuronModelRuntimeTupleV1, NeuronFeatureStoreError> {
        Ok(NeuronModelRuntimeTupleV1 {
            model_id: parse_id(&self.model_id)?,
            model_manifest_digest: parse_digest(&self.model_manifest_digest)?,
            weights_digest: parse_digest(&self.weights_digest)?,
            tokenizer_digest: parse_digest(&self.tokenizer_digest)?,
            preprocessor_digest: parse_digest(&self.preprocessor_digest)?,
            quantization_digest: parse_digest(&self.quantization_digest)?,
            runtime_digest: parse_digest(&self.runtime_digest)?,
            device_digest: parse_digest(&self.device_digest)?,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReceiptDto {
    request_digest: String,
    runtime_tuple: RuntimeTupleDto,
    runtime_tuple_digest: String,
    encoder_digest: String,
    head_digest: String,
    output_digest: String,
    drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
    observed_memory_bytes: u64,
    transient_allocation_bytes: u64,
    queue_age_micros: u64,
    latency_micros: u64,
    status: String,
    receipt_digest: String,
}

impl ReceiptDto {
    fn from_receipt(value: &NeuronFeatureReceiptV1) -> Self {
        Self {
            request_digest: value.request_digest.to_string(),
            runtime_tuple: RuntimeTupleDto::from_tuple(&value.runtime_tuple),
            runtime_tuple_digest: value.runtime_tuple_digest.to_string(),
            encoder_digest: value.encoder_digest.to_string(),
            head_digest: value.head_digest.to_string(),
            output_digest: value.output_digest.to_string(),
            drive_q24: value.drive_q24.clone(),
            prediction_q24: value.prediction_q24.clone(),
            observed_memory_bytes: value.observed_memory_bytes,
            transient_allocation_bytes: value.transient_allocation_bytes,
            queue_age_micros: value.queue_age_micros,
            latency_micros: value.latency_micros,
            status: status_name(value.status).to_owned(),
            receipt_digest: value.receipt_digest.to_string(),
        }
    }

    fn into_receipt(self) -> Result<NeuronFeatureReceiptV1, NeuronFeatureStoreError> {
        Ok(NeuronFeatureReceiptV1 {
            request_digest: parse_digest(&self.request_digest)?,
            runtime_tuple: self.runtime_tuple.into_tuple()?,
            runtime_tuple_digest: parse_digest(&self.runtime_tuple_digest)?,
            encoder_digest: parse_digest(&self.encoder_digest)?,
            head_digest: parse_digest(&self.head_digest)?,
            output_digest: parse_digest(&self.output_digest)?,
            drive_q24: self.drive_q24,
            prediction_q24: self.prediction_q24,
            observed_memory_bytes: self.observed_memory_bytes,
            transient_allocation_bytes: self.transient_allocation_bytes,
            queue_age_micros: self.queue_age_micros,
            latency_micros: self.latency_micros,
            status: parse_status(&self.status)?,
            receipt_digest: parse_digest(&self.receipt_digest)?,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

const fn status_name(value: NeuronFeatureTerminalStatusV1) -> &'static str {
    match value {
        NeuronFeatureTerminalStatusV1::Succeeded => "succeeded",
        NeuronFeatureTerminalStatusV1::Failed => "failed",
        NeuronFeatureTerminalStatusV1::Cancelled => "cancelled",
        NeuronFeatureTerminalStatusV1::Indeterminate => "indeterminate",
    }
}

fn parse_status(value: &str) -> Result<NeuronFeatureTerminalStatusV1, NeuronFeatureStoreError> {
    match value {
        "succeeded" => Ok(NeuronFeatureTerminalStatusV1::Succeeded),
        "failed" => Ok(NeuronFeatureTerminalStatusV1::Failed),
        "cancelled" => Ok(NeuronFeatureTerminalStatusV1::Cancelled),
        "indeterminate" => Ok(NeuronFeatureTerminalStatusV1::Indeterminate),
        _ => Err(NeuronFeatureStoreError::Corrupt),
    }
}

fn parse_id(value: &str) -> Result<StableId, NeuronFeatureStoreError> {
    StableId::new(value).map_err(|_| NeuronFeatureStoreError::Corrupt)
}

fn parse_digest(value: &str) -> Result<Digest32, NeuronFeatureStoreError> {
    Digest32::from_str(value).map_err(|_| NeuronFeatureStoreError::Corrupt)
}
