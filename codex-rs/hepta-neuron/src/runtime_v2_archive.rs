//! Immutable full history for a retired generation. No model/witness owner is
//! rebuilt by this reader; it exposes administrative truth only.
use std::collections::BTreeMap;

use super::*;
use crate::NeuronOperationFailureV2;

const MAGIC: &[u8; 8] = b"HPTNAR01";
const DOMAIN: &[u8] = b"hepta.neuron.generation-archive.v1";
pub const MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1: usize = 64 * 1024 * 1024;
const MAX_OPERATIONS: usize = 65_536;
const MAX_FRAME: usize = 16 * 1024 * 1024 + 32;

pub struct NeuronGenerationArchiveV1 {
    generation: u64,
    configuration_digest: Digest32,
    body_bundle_digest: Digest32,
    digest: Digest32,
    bytes: Vec<u8>,
    operations: BTreeMap<StableId, (Digest32, NeuronOperationStatusV2)>,
}
impl NeuronGenerationArchiveV1 {
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn configuration_digest(&self) -> Digest32 {
        self.configuration_digest
    }
    pub fn body_bundle_digest(&self) -> Digest32 {
        self.body_bundle_digest
    }
    pub fn digest(&self) -> Digest32 {
        self.digest
    }
    pub fn operation_count(&self) -> usize {
        self.operations.len()
    }
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn query_operation(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        if input_digest.is_zero() {
            return Err(NeuronRuntimeV2Error::OperationConflict);
        }
        match self.operations.get(tick_id) {
            Some((original, status)) if *original == input_digest => Ok(status.clone()),
            Some(_) => Err(NeuronRuntimeV2Error::OperationConflict),
            None => Ok(NeuronOperationStatusV2::NotRecorded),
        }
    }

    /// The owning durable archive receipt provides the expected sealed digest.
    /// Missing/changed blobs cannot be reconstructed from a model invocation.
    pub fn from_bytes(
        bytes: Vec<u8>,
        expected_digest: Digest32,
    ) -> Result<Self, NeuronRuntimeV2Error> {
        if bytes.len() > MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1 || bytes.len() < 116 {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let end = bytes.len() - 32;
        let digest = Digest32::of_parts(&[DOMAIN, &bytes[..end]]);
        if expected_digest.is_zero()
            || digest != expected_digest
            || digest.as_array() != &bytes[end..]
        {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let mut input = ArchiveDecoder {
            bytes: &bytes[..end],
            position: 0,
        };
        if input.take(8)? != MAGIC {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let generation = input.u64()?;
        let configuration_digest = input.digest()?;
        let body_bundle_digest = input.digest()?;
        let count = input.u32()? as usize;
        if generation == 0
            || configuration_digest.is_zero()
            || body_bundle_digest.is_zero()
            || count > MAX_OPERATIONS
        {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let mut operations = BTreeMap::new();
        for _ in 0..count {
            let tag = input.u8()?;
            let payload = input.frame(MAX_FRAME)?;
            let (key, status) = match tag {
                1 => {
                    let record = crate::generation_store_v2::decode_archived_record(payload)?;
                    if record.config_semantic_digest != configuration_digest
                        || record.body_bundle_digest != body_bundle_digest
                    {
                        return Err(GenerationStoreError::ContextMismatch.into());
                    }
                    let prepared = decode_prepared(&record.checkpoint_bytes)?;
                    validate_prepared_against_record(&prepared, &record)?;
                    let receipt_extension = decode_full_receipt_v2(
                        &record.checkpoint_bytes,
                        &record.full_receipt_bytes,
                    )?;
                    let commit = NeuronRuntimeCommitV2 {
                        key: record.key.clone(),
                        expected_anchor: record.expected_anchor,
                        next_anchor: record.next_anchor,
                        operation_digest: record.operation_digest,
                        model_semantic_digest: record.model_semantic_digest,
                        model_observation_digest: record.model_observation_digest,
                        disposition: record.disposition,
                        receipt_extension,
                        output: prepared.output,
                    };
                    (
                        record.key,
                        NeuronOperationStatusV2::Committed {
                            commit: Box::new(commit),
                            witness_acknowledged: true,
                        },
                    )
                }
                2 => decode_failure(payload)?,
                _ => return Err(GenerationStoreError::Corrupt.into()),
            };
            if operations
                .insert(key.tick_id, (key.input_semantic_digest, status))
                .is_some()
            {
                return Err(GenerationStoreError::Corrupt.into());
            }
        }
        if input.position != end {
            return Err(GenerationStoreError::Corrupt.into());
        }
        Ok(Self {
            generation,
            configuration_digest,
            body_bundle_digest,
            digest,
            bytes,
            operations,
        })
    }
}

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    /// Called only after the host has closed/drained the generation. Unknown,
    /// reserved work or witness outbox prevents retirement; no provider is run.
    pub fn export_generation_archive(
        &mut self,
        maximum_bytes: usize,
    ) -> Result<NeuronGenerationArchiveV1, NeuronRuntimeV2Error> {
        if maximum_bytes == 0 || maximum_bytes > MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1 {
            return Err(GenerationStoreError::InvalidLimit.into());
        }
        self.reconcile()?;
        if self.index.pending()?.is_some() || self.pending_witness_count()? != 0 {
            return Err(NeuronRuntimeV2Error::PendingOperation);
        }
        let records = self.store.archive_records()?;
        let failures = self.index.archive_failures()?;
        let count = records
            .len()
            .checked_add(failures.len())
            .ok_or(GenerationStoreError::Capacity)?;
        if count > MAX_OPERATIONS {
            return Err(GenerationStoreError::Capacity.into());
        }
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(&self.config.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.configuration_digest()?.as_array());
        bytes.extend_from_slice(self.body_bundle_digest.as_array());
        bytes.extend_from_slice(&(count as u32).to_be_bytes());
        for record in records {
            self.commit_from_record(record)?;
            append_frame(
                &mut bytes,
                1,
                &crate::generation_store_v2::encode_archived_record(record)?,
                maximum_bytes,
            )?;
        }
        for (key, reason) in failures.values() {
            if self.store.find_operation(key)?.is_some() {
                return Err(NeuronRuntimeV2Error::RecoveryMismatch);
            }
            append_frame(&mut bytes, 2, &encode_failure(key, *reason)?, maximum_bytes)?;
        }
        let digest = Digest32::of_parts(&[DOMAIN, &bytes]);
        bytes.extend_from_slice(digest.as_array());
        if bytes.len() > maximum_bytes {
            return Err(GenerationStoreError::Capacity.into());
        }
        NeuronGenerationArchiveV1::from_bytes(bytes, digest)
    }
}

fn append_frame(
    bytes: &mut Vec<u8>,
    tag: u8,
    payload: &[u8],
    limit: usize,
) -> Result<(), GenerationStoreError> {
    let projected = bytes
        .len()
        .checked_add(payload.len())
        .and_then(|value| value.checked_add(37))
        .ok_or(GenerationStoreError::Capacity)?;
    if payload.is_empty() || payload.len() > MAX_FRAME || projected > limit {
        return Err(GenerationStoreError::Capacity);
    }
    bytes.push(tag);
    bytes.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    bytes.extend_from_slice(payload);
    Ok(())
}
fn encode_failure(
    key: &NeuronOperationKeyV2,
    failure: NeuronOperationFailureV2,
) -> Result<Vec<u8>, GenerationStoreError> {
    key.semantic_digest()
        .map_err(|_| GenerationStoreError::Corrupt)?;
    let id = key.tick_id.as_str().as_bytes();
    let mut bytes = (id.len() as u32).to_be_bytes().to_vec();
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(key.input_semantic_digest.as_array());
    bytes.push(match failure {
        NeuronOperationFailureV2::ModelRejected => 1,
        NeuronOperationFailureV2::InvalidModelOutput => 2,
        NeuronOperationFailureV2::InvalidTransition => 3,
        NeuronOperationFailureV2::AdmissionDenied => 4,
        NeuronOperationFailureV2::ResultOverBudget => 5,
    });
    Ok(bytes)
}
fn decode_failure(
    bytes: &[u8],
) -> Result<(NeuronOperationKeyV2, NeuronOperationStatusV2), GenerationStoreError> {
    let mut input = ArchiveDecoder { bytes, position: 0 };
    let id = std::str::from_utf8(input.frame(255)?).map_err(|_| GenerationStoreError::Corrupt)?;
    let key = NeuronOperationKeyV2 {
        tick_id: StableId::new(id).map_err(|_| GenerationStoreError::Corrupt)?,
        input_semantic_digest: input.digest()?,
    };
    key.semantic_digest()
        .map_err(|_| GenerationStoreError::Corrupt)?;
    let failure = match input.u8()? {
        1 => NeuronOperationFailureV2::ModelRejected,
        2 => NeuronOperationFailureV2::InvalidModelOutput,
        3 => NeuronOperationFailureV2::InvalidTransition,
        4 => NeuronOperationFailureV2::AdmissionDenied,
        5 => NeuronOperationFailureV2::ResultOverBudget,
        _ => return Err(GenerationStoreError::Corrupt),
    };
    if input.position != bytes.len() {
        return Err(GenerationStoreError::Corrupt);
    }
    Ok((key, NeuronOperationStatusV2::Failed(failure)))
}
struct ArchiveDecoder<'a> {
    bytes: &'a [u8],
    position: usize,
}
impl<'a> ArchiveDecoder<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], GenerationStoreError> {
        let end = self
            .position
            .checked_add(count)
            .ok_or(GenerationStoreError::Corrupt)?;
        let value = self
            .bytes
            .get(self.position..end)
            .ok_or(GenerationStoreError::Corrupt)?;
        self.position = end;
        Ok(value)
    }
    fn u8(&mut self) -> Result<u8, GenerationStoreError> {
        Ok(self.take(1)?[0])
    }
    fn u32(&mut self) -> Result<u32, GenerationStoreError> {
        Ok(u32::from_be_bytes(
            self.take(4)?
                .try_into()
                .map_err(|_| GenerationStoreError::Corrupt)?,
        ))
    }
    fn u64(&mut self) -> Result<u64, GenerationStoreError> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| GenerationStoreError::Corrupt)?,
        ))
    }
    fn digest(&mut self) -> Result<Digest32, GenerationStoreError> {
        Ok(Digest32::from_array(
            self.take(32)?
                .try_into()
                .map_err(|_| GenerationStoreError::Corrupt)?,
        ))
    }
    fn frame(&mut self, limit: usize) -> Result<&'a [u8], GenerationStoreError> {
        let count = self.u32()? as usize;
        if count == 0 || count > limit {
            return Err(GenerationStoreError::Corrupt);
        }
        self.take(count)
    }
}
