/// Strong generation identity for Agentd Neuron control-plane calls.
///
/// The wrapper deliberately cannot be constructed from an execution epoch or
/// an arbitrary counter without passing the non-zero generation check.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct AgentdNeuronGenerationIdV2(Generation);

impl AgentdNeuronGenerationIdV2 {
    pub fn new(value: u64) -> Result<Self, AgentdNeuronIdentityErrorV2> {
        Generation::new(value)
            .map(Self)
            .map_err(|_| AgentdNeuronIdentityErrorV2::InvalidGeneration)
    }

    pub const fn from_generation(value: Generation) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0.get()
    }

    pub const fn as_generation(self) -> Generation {
        self.0
    }
}

impl Serialize for AgentdNeuronGenerationIdV2 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_u64(self.get())
    }
}

/// Strong lifecycle epoch captured by a prepared invocation.
///
/// It is intentionally a distinct type from a model generation. Comparing the
/// two requires an explicit extraction at a wire/projection boundary.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct AgentdNeuronExecutionEpochV2(u64);

impl AgentdNeuronExecutionEpochV2 {
    pub fn new(value: u64) -> Result<Self, AgentdNeuronIdentityErrorV2> {
        if value == 0 {
            Err(AgentdNeuronIdentityErrorV2::InvalidExecutionEpoch)
        } else {
            Ok(Self(value))
        }
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

impl Serialize for AgentdNeuronExecutionEpochV2 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_u64(self.get())
    }
}

/// Exact durable operation identity. Tick identity and canonical input digest
/// travel together so generation, epoch and provider receipt digests cannot be
/// accidentally passed as an operation key.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdNeuronOperationIdentityV2 {
    tick_id: StableId,
    input_semantic_digest: Digest32,
}

impl AgentdNeuronOperationIdentityV2 {
    pub fn new(
        tick_id: StableId,
        input_semantic_digest: Digest32,
    ) -> Result<Self, AgentdNeuronIdentityErrorV2> {
        if input_semantic_digest.is_zero() {
            return Err(AgentdNeuronIdentityErrorV2::ZeroInputSemanticDigest);
        }
        Ok(Self {
            tick_id,
            input_semantic_digest,
        })
    }

    pub fn from_input(input: &NeuronTickInputV1) -> Result<Self, NeuronRuntimeV2Error> {
        let input_semantic_digest = input.semantic_digest()?;
        Self::new(input.tick_id.clone(), input_semantic_digest)
            .map_err(|_| NeuronRuntimeV2Error::ContextMismatch)
    }

    pub fn tick_id(&self) -> &StableId {
        &self.tick_id
    }

    pub const fn input_semantic_digest(&self) -> Digest32 {
        self.input_semantic_digest
    }
}

impl Serialize for AgentdNeuronOperationIdentityV2 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;

        let mut state = serializer.serialize_struct("AgentdNeuronOperationIdentityV2", 2)?;
        state.serialize_field("tickId", self.tick_id.as_str())?;
        state.serialize_field(
            "inputSemanticDigest",
            &self.input_semantic_digest.to_string(),
        )?;
        state.end()
    }
}

/// Identity of one observed provider receipt as committed by the V2 runtime.
/// The three digest domains are kept in a dedicated type instead of being
/// interchangeable `Digest32` arguments at product/control boundaries.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AgentdNeuronProviderReceiptIdentityV2 {
    operation_digest: Digest32,
    model_semantic_digest: Digest32,
    model_observation_digest: Digest32,
}

impl AgentdNeuronProviderReceiptIdentityV2 {
    pub fn from_commit(commit: &NeuronRuntimeCommitV2) -> Self {
        Self {
            operation_digest: commit.operation_digest,
            model_semantic_digest: commit.model_semantic_digest,
            model_observation_digest: commit.model_observation_digest,
        }
    }

    pub const fn operation_digest(self) -> Digest32 {
        self.operation_digest
    }

    pub const fn model_semantic_digest(self) -> Digest32 {
        self.model_semantic_digest
    }

    pub const fn model_observation_digest(self) -> Digest32 {
        self.model_observation_digest
    }
}

impl Serialize for AgentdNeuronProviderReceiptIdentityV2 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;

        let mut state = serializer.serialize_struct("AgentdNeuronProviderReceiptIdentityV2", 3)?;
        state.serialize_field("operationDigest", &self.operation_digest.to_string())?;
        state.serialize_field(
            "modelSemanticDigest",
            &self.model_semantic_digest.to_string(),
        )?;
        state.serialize_field(
            "modelObservationDigest",
            &self.model_observation_digest.to_string(),
        )?;
        state.end()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdNeuronIdentityErrorV2 {
    InvalidGeneration,
    InvalidExecutionEpoch,
    ZeroInputSemanticDigest,
}

impl fmt::Display for AgentdNeuronIdentityErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdNeuronIdentityErrorV2 {}

impl<W, P> AgentdNeuronOwnerV2<W, P>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    /// Explicit durable composition constructor. The legacy `new` spelling is
    /// retained only for source compatibility while product callers migrate.
    pub fn from_durable_control(runtime: NeuronRuntimeV2<W>, inference_control: P) -> Self {
        Self::new(runtime, inference_control)
    }
}

impl AgentdNeuronHandleV2 {
    pub fn generation_identity(
        &self,
    ) -> Result<AgentdNeuronGenerationIdV2, AgentdNeuronControlErrorV2> {
        AgentdNeuronGenerationIdV2::new(self.generation()?)
            .map_err(|_| AgentdNeuronControlErrorV2::GenerationConflict)
    }
}

impl AgentdNeuronGenerationControllerSnapshotV2 {
    pub fn active_generation_identity(
        &self,
    ) -> Result<AgentdNeuronGenerationIdV2, AgentdNeuronIdentityErrorV2> {
        AgentdNeuronGenerationIdV2::new(self.active_generation)
    }

    pub fn retained_generation_identities(
        &self,
    ) -> Result<Vec<AgentdNeuronGenerationIdV2>, AgentdNeuronIdentityErrorV2> {
        self.retained_generations
            .iter()
            .copied()
            .map(AgentdNeuronGenerationIdV2::new)
            .collect()
    }

    pub fn execution_epoch_identity(
        &self,
    ) -> Result<AgentdNeuronExecutionEpochV2, AgentdNeuronIdentityErrorV2> {
        AgentdNeuronExecutionEpochV2::new(self.execution_epoch)
    }
}

impl AgentdNeuronGenerationControllerV2 {
    /// Typed administrative query. New control-plane callers should use this
    /// boundary instead of passing unrelated raw counters and digests.
    pub fn query_operation_identity(
        &self,
        generation: AgentdNeuronGenerationIdV2,
        operation: &AgentdNeuronOperationIdentityV2,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        self.query_operation(
            generation.get(),
            operation.tick_id(),
            operation.input_semantic_digest(),
        )
    }

    pub fn active_generation_identity(
        &self,
    ) -> Result<AgentdNeuronGenerationIdV2, AgentdNeuronControlErrorV2> {
        AgentdNeuronGenerationIdV2::new(self.active_generation()?)
            .map_err(|_| AgentdNeuronControlErrorV2::GenerationConflict)
    }

    pub fn retained_generation_identities(
        &self,
    ) -> Result<Vec<AgentdNeuronGenerationIdV2>, AgentdNeuronControlErrorV2> {
        self.retained_generations()?
            .into_iter()
            .map(|generation| {
                AgentdNeuronGenerationIdV2::new(generation)
                    .map_err(|_| AgentdNeuronControlErrorV2::GenerationConflict)
            })
            .collect()
    }
}

#[cfg(test)]
mod identity_tests {
    use super::*;

    #[test]
    fn generation_epoch_operation_and_receipt_are_distinct() {
        let generation = AgentdNeuronGenerationIdV2::new(7).expect("generation");
        let epoch = AgentdNeuronExecutionEpochV2::new(7).expect("epoch");
        assert_eq!(generation.get(), epoch.get());
        assert_ne!(
            std::any::TypeId::of::<AgentdNeuronGenerationIdV2>(),
            std::any::TypeId::of::<AgentdNeuronExecutionEpochV2>()
        );

        let operation = AgentdNeuronOperationIdentityV2::new(
            StableId::new("identity.tick").expect("tick"),
            Digest32::of_bytes(b"input"),
        )
        .expect("operation");
        assert_eq!(operation.tick_id().as_str(), "identity.tick");
        assert!(!operation.input_semantic_digest().is_zero());
    }

    #[test]
    fn invalid_raw_identity_values_fail_closed() {
        assert_eq!(
            AgentdNeuronGenerationIdV2::new(0),
            Err(AgentdNeuronIdentityErrorV2::InvalidGeneration)
        );
        assert_eq!(
            AgentdNeuronExecutionEpochV2::new(0),
            Err(AgentdNeuronIdentityErrorV2::InvalidExecutionEpoch)
        );
        assert_eq!(
            AgentdNeuronOperationIdentityV2::new(
                StableId::new("identity.tick").expect("tick"),
                Digest32::ZERO,
            ),
            Err(AgentdNeuronIdentityErrorV2::ZeroInputSemanticDigest)
        );
    }
}
