//! Exact internal layouts, independent of the native V1 decision protocol.
//! A profile names semantics; its digest is not evidence that a model implements
//! those semantics or that the caller may read, train or publish its contents.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub(crate) const MAX_REPRESENTATION_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum CellTensorDtypeV1 {
    U8 = 0,
    I32Le = 1,
    I64Le = 2,
    F16Le = 3,
    F32Le = 4,
    F64Le = 5,
    SignedQ24Le = 6,
}

impl CellTensorDtypeV1 {
    pub fn element_bytes(self) -> u64 {
        match self {
            Self::U8 => 1,
            Self::F16Le => 2,
            Self::I32Le | Self::F32Le => 4,
            Self::I64Le | Self::F64Le | Self::SignedQ24Le => 8,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
#[repr(u8)]
pub enum CellTensorRoleV1 {
    Features = 0,
    Tokens = 1,
    Mask = 2,
    Coordinates = 3,
    Output = 4,
    Weights = 5,
    Optimizer = 6,
    Rng = 7,
    Sampler = 8,
    TrainingCursor = 9,
}

/// Contiguous, row-major, exact extents. Padding requires an explicit mask;
/// neither an omitted modality nor a token sequence is inferred from a vector.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellTensorLayoutV1 {
    pub name: StableId,
    pub role: CellTensorRoleV1,
    pub dtype: CellTensorDtypeV1,
    pub shape: Vec<u64>,
    pub axes: Vec<StableId>,
    pub modality: Option<StableId>,
    pub optional: bool,
}

impl CellTensorLayoutV1 {
    pub fn byte_len(&self) -> Result<u64, CellRepresentationErrorV1> {
        if self.shape.is_empty()
            || self.shape.len() > 8
            || self.axes.len() != self.shape.len()
            || self.shape.contains(&0)
            || self.axes.iter().collect::<BTreeSet<_>>().len() != self.axes.len()
            || (self.optional && self.modality.is_none())
            || (self.role == CellTensorRoleV1::Mask && self.dtype != CellTensorDtypeV1::U8)
        {
            return Err(CellRepresentationErrorV1::InvalidLayout);
        }
        self.shape
            .iter()
            .try_fold(self.dtype.element_bytes(), |bytes, extent| {
                bytes.checked_mul(*extent)
            })
            .filter(|bytes| *bytes <= MAX_REPRESENTATION_BYTES)
            .ok_or(CellRepresentationErrorV1::Capacity)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellRepresentationKindV1 {
    GlobalVector,
    TokenSequence {
        tokenizer_digest: Digest32,
    },
    MultimodalSpatiotemporal {
        coordinate_system_digest: Digest32,
        timebase_digest: Digest32,
    },
    GenerationOutput {
        codec_digest: Digest32,
    },
    TrainableState {
        training_protocol_digest: Digest32,
    },
}

/// Versioned internal schema. A changed dtype, extent, axis, missing-modality
/// rule, codec, optimizer roster or budget is a different exact profile.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationProfileV1 {
    pub profile_id: StableId,
    pub generation: Generation,
    pub semantic_schema_digest: Digest32,
    pub kind: CellRepresentationKindV1,
    pub tensors: Vec<CellTensorLayoutV1>,
    pub max_payload_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellRepresentationErrorV1 {
    InvalidProfile,
    InvalidLayout,
    InvalidPayload,
    Capacity,
    Incompatible,
    UnqualifiedProjection,
    ProjectionRequired,
    ScopeMismatch,
    StaleSource,
    StaleProducer,
    StaleConsumer,
}

impl std::fmt::Display for CellRepresentationErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellRepresentationErrorV1 {}

impl CellRepresentationProfileV1 {
    /// Normalize owned metadata after validating its logical bounds. Callers
    /// cannot retain arbitrarily large spare buffers behind a small layout.
    pub(crate) fn into_compact(mut self) -> Result<Self, CellRepresentationErrorV1> {
        self.digest()?;
        self.profile_id = compact_id(&self.profile_id)?;
        for tensor in &mut self.tensors {
            tensor.name = compact_id(&tensor.name)?;
            tensor.modality = tensor.modality.as_ref().map(compact_id).transpose()?;
            for axis in &mut tensor.axes {
                *axis = compact_id(axis)?;
            }
            tensor.axes = std::mem::take(&mut tensor.axes)
                .into_boxed_slice()
                .into_vec();
            tensor.shape = std::mem::take(&mut tensor.shape)
                .into_boxed_slice()
                .into_vec();
        }
        self.tensors = self.tensors.into_boxed_slice().into_vec();
        Ok(self)
    }

    pub fn digest(&self) -> Result<Digest32, CellRepresentationErrorV1> {
        use CellRepresentationErrorV1 as E;
        use CellTensorRoleV1 as R;

        if self.semantic_schema_digest.is_zero()
            || self.tensors.is_empty()
            || self.tensors.len() > 32
        {
            return Err(E::InvalidProfile);
        }
        if !(1..=MAX_REPRESENTATION_BYTES).contains(&self.max_payload_bytes) {
            return Err(E::Capacity);
        }
        let mut names = BTreeSet::new();
        let mut modalities = BTreeMap::new();
        let mut total = 0_u64;
        for tensor in &self.tensors {
            if !names.insert(&tensor.name) {
                return Err(E::InvalidLayout);
            }
            total = total.checked_add(tensor.byte_len()?).ok_or(E::Capacity)?;
            if let Some(modality) = &tensor.modality
                && let Some(previous) = modalities.insert(modality, tensor.optional)
                && previous != tensor.optional
            {
                return Err(E::InvalidLayout);
            }
        }
        if total > self.max_payload_bytes {
            return Err(E::Capacity);
        }
        let roles: BTreeSet<_> = self.tensors.iter().map(|tensor| tensor.role).collect();
        let mut bytes = b"hepta.cell.representation-profile.v1\0".to_vec();
        push_id(&mut bytes, &self.profile_id);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.semantic_schema_digest.as_array());
        match &self.kind {
            CellRepresentationKindV1::GlobalVector => {
                if self.tensors.len() != 1
                    || self.tensors[0].role != R::Features
                    || self.tensors[0].axes.len() != 1
                    || self.tensors[0].axes[0].as_str() != "feature"
                    || !modalities.is_empty()
                {
                    return Err(E::InvalidProfile);
                }
                bytes.push(0);
            }
            CellRepresentationKindV1::TokenSequence { tokenizer_digest } => {
                let token_counts: BTreeSet<_> =
                    self.tensors.iter().map(|tensor| tensor.shape[0]).collect();
                if tokenizer_digest.is_zero()
                    || self
                        .tensors
                        .iter()
                        .filter(|tensor| tensor.role == R::Tokens)
                        .count()
                        != 1
                    || !roles.is_subset(&BTreeSet::from([R::Tokens, R::Mask, R::Coordinates]))
                    || token_counts.len() != 1
                    || self
                        .tensors
                        .iter()
                        .any(|tensor| tensor.axes[0].as_str() != "token")
                    || !modalities.is_empty()
                {
                    return Err(E::InvalidProfile);
                }
                bytes.push(1);
                bytes.extend_from_slice(tokenizer_digest.as_array());
            }
            CellRepresentationKindV1::MultimodalSpatiotemporal {
                coordinate_system_digest,
                timebase_digest,
            } => {
                if coordinate_system_digest.is_zero()
                    || timebase_digest.is_zero()
                    || modalities.len() < 2
                    || self.tensors.iter().any(|tensor| tensor.modality.is_none())
                    || !roles.is_subset(&BTreeSet::from([R::Features, R::Mask, R::Coordinates]))
                    || !self
                        .tensors
                        .iter()
                        .flat_map(|tensor| &tensor.axes)
                        .any(|axis| matches!(axis.as_str(), "time" | "height" | "width" | "space"))
                {
                    return Err(E::InvalidProfile);
                }
                bytes.push(2);
                bytes.extend_from_slice(coordinate_system_digest.as_array());
                bytes.extend_from_slice(timebase_digest.as_array());
            }
            CellRepresentationKindV1::GenerationOutput { codec_digest } => {
                if codec_digest.is_zero()
                    || !roles.is_subset(&BTreeSet::from([R::Output, R::Tokens, R::Mask]))
                    || !(roles.contains(&R::Output) || roles.contains(&R::Tokens))
                    || !modalities.is_empty()
                {
                    return Err(E::InvalidProfile);
                }
                bytes.push(3);
                bytes.extend_from_slice(codec_digest.as_array());
            }
            CellRepresentationKindV1::TrainableState {
                training_protocol_digest,
            } => {
                if training_protocol_digest.is_zero()
                    || roles
                        != BTreeSet::from([
                            R::Weights,
                            R::Optimizer,
                            R::Rng,
                            R::Sampler,
                            R::TrainingCursor,
                        ])
                    || !modalities.is_empty()
                {
                    return Err(E::InvalidProfile);
                }
                bytes.push(4);
                bytes.extend_from_slice(training_protocol_digest.as_array());
            }
        }
        bytes.extend_from_slice(&self.max_payload_bytes.to_be_bytes());
        bytes.extend_from_slice(&(self.tensors.len() as u64).to_be_bytes());
        for tensor in &self.tensors {
            push_id(&mut bytes, &tensor.name);
            bytes.extend_from_slice(&[
                tensor.role as u8,
                tensor.dtype as u8,
                u8::from(tensor.optional),
            ]);
            bytes.extend_from_slice(&(tensor.shape.len() as u64).to_be_bytes());
            for (extent, axis) in tensor.shape.iter().zip(&tensor.axes) {
                bytes.extend_from_slice(&extent.to_be_bytes());
                push_id(&mut bytes, axis);
            }
            match &tensor.modality {
                Some(modality) => {
                    bytes.push(1);
                    push_id(&mut bytes, modality);
                }
                None => bytes.push(0),
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

pub(crate) fn compact_id(id: &StableId) -> Result<StableId, CellRepresentationErrorV1> {
    StableId::new(id.as_str()).map_err(|_| CellRepresentationErrorV1::InvalidProfile)
}
