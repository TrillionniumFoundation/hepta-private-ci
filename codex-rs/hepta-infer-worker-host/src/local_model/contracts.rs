#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelManifestEnvelope {
    pub schema_version: u32,
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_id: String,
    pub device_lease_id: String,
    pub maximum_memory_bytes: u64,
    pub manifest_digest: String,
}

impl ModelManifestEnvelope {
    fn expected_digest(&self) -> String {
        let mut hasher = Sha256::new();
        frame(&mut hasher, b"hepta.local-model.manifest.v1");
        frame_u32(&mut hasher, self.schema_version);
        for value in [
            self.model_id.as_bytes(),
            self.model_digest.as_bytes(),
            self.weights_digest.as_bytes(),
            self.tokenizer_digest.as_bytes(),
            self.preprocessor_digest.as_bytes(),
            self.quantization_digest.as_bytes(),
            self.runtime_digest.as_bytes(),
            self.device_id.as_bytes(),
            self.device_lease_id.as_bytes(),
        ] {
            frame(&mut hasher, value);
        }
        frame_u64(&mut hasher, self.maximum_memory_bytes);
        format!("{:x}", hasher.finalize())
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedModelManifest {
    envelope: ModelManifestEnvelope,
}

impl VerifiedModelManifest {
    pub fn verify(
        envelope: ModelManifestEnvelope,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalModelError> {
        let claims = grant.claims();
        if envelope.schema_version != MANIFEST_SCHEMA
            || envelope.maximum_memory_bytes == 0
            || envelope.maximum_memory_bytes > claims.maximum_model_memory_bytes
            || envelope.manifest_digest != envelope.expected_digest()
            || envelope.model_id != claims.model_id
            || envelope.model_digest != claims.model_digest
            || envelope.weights_digest != claims.weights_digest
            || envelope.tokenizer_digest != claims.tokenizer_digest
            || envelope.preprocessor_digest != claims.preprocessor_digest
            || envelope.quantization_digest != claims.quantization_digest
            || envelope.runtime_digest != claims.runtime_digest
            || envelope.device_id != claims.device_id
            || envelope.device_lease_id != claims.device_lease_id
        {
            return Err(LocalModelError::ManifestBinding);
        }
        validate_digest(&envelope.manifest_digest, "manifest")?;
        Ok(Self { envelope })
    }

    #[must_use]
    pub fn envelope(&self) -> &ModelManifestEnvelope {
        &self.envelope
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedInput {
    bytes: Vec<u8>,
    digest: String,
    maximum_tokens: u64,
}

impl VerifiedInput {
    pub fn verify(
        bytes: Vec<u8>,
        expected_digest: &str,
        maximum_tokens: u64,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalModelError> {
        validate_digest(expected_digest, "input")?;
        if bytes.is_empty()
            || bytes.len() > MAX_INPUT_BYTES
            || maximum_tokens == 0
            || maximum_tokens > grant.claims.maximum_tokens_per_request
            || digest(&bytes) != expected_digest
        {
            return Err(LocalModelError::InputBinding);
        }
        Ok(Self {
            bytes,
            digest: expected_digest.to_string(),
            maximum_tokens,
        })
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn digest(&self) -> &str {
        &self.digest
    }

    #[must_use]
    pub const fn maximum_tokens(&self) -> u64 {
        self.maximum_tokens
    }
}

#[derive(Clone, Debug)]
pub struct TrustedDeadline {
    instant: Instant,
    unix_ms: u64,
}

impl TrustedDeadline {
    pub fn from_absolute_unix_ms(unix_ms: u64) -> Result<Self, LocalModelError> {
        let now = unix_time_ms()?;
        if unix_ms <= now {
            return Err(LocalModelError::DeadlineExpired);
        }
        Ok(Self {
            instant: Instant::now() + Duration::from_millis(unix_ms - now),
            unix_ms,
        })
    }

    #[must_use]
    pub fn instant(&self) -> Instant {
        self.instant
    }

    #[must_use]
    pub const fn unix_ms(&self) -> u64 {
        self.unix_ms
    }

    fn ensure_live(&self) -> Result<(), LocalModelError> {
        if Instant::now() >= self.instant {
            Err(LocalModelError::DeadlineExpired)
        } else {
            Ok(())
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct OperationId(String);

impl OperationId {
    pub fn parse(value: impl Into<String>) -> Result<Self, LocalModelError> {
        let value = value.into();
        validate_identifier(&value, "operation")?;
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug)]
pub struct UnverifiedModelHandle {
    pub opaque_id: String,
    pub model_digest: String,
    pub device_id: String,
    pub observed_memory_bytes: u64,
    pub attestation_digest: String,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug)]
pub struct AttestedModelHandle {
    opaque_id: String,
    model_id: String,
    model_digest: String,
    device_id: String,
    observed_memory_bytes: u64,
    attestation_digest: String,
}

impl AttestedModelHandle {
    fn verify(
        handle: UnverifiedModelHandle,
        manifest: &VerifiedModelManifest,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalModelError> {
        validate_identifier(&handle.opaque_id, "driver handle")?;
        validate_digest(&handle.attestation_digest, "driver attestation")?;
        if !handle.terminal_observed
            || handle.model_digest != manifest.envelope.model_digest
            || handle.device_id != grant.claims.device_id
            || handle.observed_memory_bytes == 0
            || handle.observed_memory_bytes > manifest.envelope.maximum_memory_bytes
        {
            return Err(LocalModelError::DriverAttestation);
        }
        Ok(Self {
            opaque_id: handle.opaque_id,
            model_id: manifest.envelope.model_id.clone(),
            model_digest: handle.model_digest,
            device_id: handle.device_id,
            observed_memory_bytes: handle.observed_memory_bytes,
            attestation_digest: handle.attestation_digest,
        })
    }

    #[must_use]
    pub fn opaque_id(&self) -> &str {
        &self.opaque_id
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriverTerminalStatus {
    Succeeded,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug)]
pub struct DriverRunObservation {
    pub terminal_observed: bool,
    pub status: DriverTerminalStatus,
    pub output_digest: Option<String>,
    pub observed_usage_tokens: Option<u64>,
    pub observed_memory_bytes: u64,
    pub attestation_digest: String,
}

#[derive(Clone, Debug)]
pub struct DriverUnloadObservation {
    pub terminal_observed: bool,
    pub opaque_id: String,
    pub released_memory_bytes: u64,
    pub attestation_digest: String,
}

#[derive(Clone, Debug)]
pub enum DriverReconciliation {
    Run(DriverRunObservation),
    Unload(DriverUnloadObservation),
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DriverError {
    Rejected(String),
    Indeterminate(String),
}

impl fmt::Display for DriverError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DriverError {}

pub trait LocalModelDriver: Send + Sync {
    fn load<'a>(
        &'a self,
        operation: &'a OperationId,
        manifest: &'a VerifiedModelManifest,
        grant: &'a VerifiedResourceGrant,
        cancellation: &'a CancellationToken,
        deadline: TrustedDeadline,
    ) -> DriverFuture<'a, UnverifiedModelHandle>;

    fn run<'a>(
        &'a self,
        operation: &'a OperationId,
        handle: &'a AttestedModelHandle,
        input: VerifiedInput,
        cancellation: &'a CancellationToken,
        deadline: TrustedDeadline,
    ) -> DriverFuture<'a, DriverRunObservation>;

    fn inspect<'a>(
        &'a self,
        operation: &'a OperationId,
    ) -> DriverFuture<'a, DriverReconciliation>;

    fn unload<'a>(
        &'a self,
        operation: &'a OperationId,
        handle: &'a AttestedModelHandle,
        cancellation: &'a CancellationToken,
        deadline: TrustedDeadline,
    ) -> DriverFuture<'a, DriverUnloadObservation>;
}
