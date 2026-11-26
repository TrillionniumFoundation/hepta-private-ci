//! One original acknowledged operation, read under its existing runtime owner.
//! Integrity parsing grants no current-use, execution or witness authority;
//! recipients must independently authenticate the protected exporter/source.
use super::*;

const MAGIC: &[u8; 8] = b"HPTNOR02";
const DOMAIN: &[u8] = b"hepta.neuron.acknowledged-operation.v2";
pub const MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2: usize = 16 * 1024 * 1024 + 8192;

pub struct NeuronAcknowledgedOperationV2 {
    bytes: Vec<u8>,
    generation: u64,
    scope: JournalScope,
    current_witness: JournalAnchor,
    record: NeuronGenerationRecordV2,
    commit: NeuronRuntimeCommitV2,
}
impl NeuronAcknowledgedOperationV2 {
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn scope(&self) -> JournalScope {
        self.scope
    }
    pub fn current_witness(&self) -> JournalAnchor {
        self.current_witness
    }
    pub fn record(&self) -> &NeuronGenerationRecordV2 {
        &self.record
    }
    pub fn commit(&self) -> &NeuronRuntimeCommitV2 {
        &self.commit
    }

    /// `expected_source_digest` is selected by the protected original exporter,
    /// not by an Agent supplying observations. This is an integrity receipt.
    pub fn from_bytes(
        bytes: Vec<u8>,
        expected_source_digest: Digest32,
    ) -> Result<Self, NeuronRuntimeV2Error> {
        if bytes.len() > MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2
            || bytes.len() < 148
            || expected_source_digest.is_zero()
            || Digest32::of_bytes(&bytes) != expected_source_digest
        {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let end = bytes.len() - 32;
        if Digest32::of_parts(&[DOMAIN, &bytes[..end]]).as_array() != &bytes[end..] {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let mut reader = Reader {
            bytes: &bytes[..end],
            offset: 0,
        };
        if reader.take(8)? != MAGIC {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let generation = reader.u64()?;
        let scope = JournalScope {
            scope_digest: reader.digest()?,
            objective_digest: reader.digest()?,
        };
        let current_witness = JournalAnchor {
            sequence: reader.u64()?,
            checkpoint_digest: reader.digest()?,
        };
        let record = crate::generation_store_v2::decode_archived_record(
            reader.frame(16 * 1024 * 1024 + 4096)?,
        )?;
        if reader.offset != end
            || scope.scope_digest.is_zero()
            || scope.objective_digest.is_zero()
            || current_witness.sequence == 0
            || current_witness.checkpoint_digest.is_zero()
            || current_witness.sequence < record.next_anchor.sequence
            || current_witness.sequence == record.next_anchor.sequence
                && current_witness != record.next_anchor
            || generation == 0
        {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        let prepared = decode_prepared(&record.checkpoint_bytes)?;
        validate_prepared_against_record(&prepared, &record)?;
        if prepared.sparse_tick.body_digest != record.body_bundle_digest
            || prepared.output.tick.checkpoint_after != record.next_anchor.checkpoint_digest
            || prepared.output.tick.checkpoint_before
                != record
                    .expected_anchor
                    .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
            || prepared.output.signal.authority.grants_any()
        {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        let receipt_extension =
            decode_full_receipt_v2(&record.checkpoint_bytes, &record.full_receipt_bytes)?;
        let commit = NeuronRuntimeCommitV2 {
            key: record.key.clone(),
            expected_anchor: record.expected_anchor,
            next_anchor: record.next_anchor,
            operation_digest: record.operation_digest,
            model_semantic_digest: record.model_semantic_digest,
            model_observation_digest: record.model_observation_digest,
            disposition: record.disposition.clone(),
            receipt_extension,
            output: prepared.output,
        };
        Ok(Self {
            bytes,
            generation,
            scope,
            current_witness,
            record,
            commit,
        })
    }
}

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    /// Observe one exact existing commit. No provider, witness CAS, new intent,
    /// full generation archive or result-use capability is created here.
    pub fn export_acknowledged_operation_v2(
        &mut self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronAcknowledgedOperationV2, NeuronRuntimeV2Error> {
        let status = self.query_operation(tick_id, input_digest)?;
        let NeuronOperationStatusV2::Committed {
            commit,
            witness_acknowledged: true,
        } = status
        else {
            return Err(NeuronRuntimeV2Error::PendingOperation);
        };
        let record = self
            .store
            .find_operation(&commit.key)?
            .ok_or(NeuronRuntimeV2Error::RecoveryMismatch)?;
        let current_witness = self
            .witness
            .current()?
            .ok_or(NeuronRuntimeV2Error::RecoveryMismatch)?;
        if !record.witness_acknowledged || Some(current_witness) != self.store.witnessed_anchor()? {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        let encoded = crate::generation_store_v2::encode_archived_record(&record)?;
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(&self.config.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.store_context.scope.scope_digest.as_array());
        bytes.extend_from_slice(self.store_context.scope.objective_digest.as_array());
        bytes.extend_from_slice(&current_witness.sequence.to_be_bytes());
        bytes.extend_from_slice(current_witness.checkpoint_digest.as_array());
        frame(&mut bytes, &encoded)?;
        let checksum = Digest32::of_parts(&[DOMAIN, &bytes]);
        bytes.extend_from_slice(checksum.as_array());
        let source_digest = Digest32::of_bytes(&bytes);
        let exported = NeuronAcknowledgedOperationV2::from_bytes(bytes, source_digest)?;
        if exported.commit() != commit.as_ref() || self.witness.current()? != Some(current_witness)
        {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        Ok(exported)
    }
}

fn frame(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), NeuronRuntimeV2Error> {
    if value.is_empty()
        || bytes
            .len()
            .checked_add(value.len() + 4)
            .is_none_or(|size| size > MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2 - 32)
    {
        return Err(GenerationStoreError::Capacity.into());
    }
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}
struct Reader<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], NeuronRuntimeV2Error> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or(GenerationStoreError::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(GenerationStoreError::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn frame(&mut self, maximum: usize) -> Result<&'a [u8], NeuronRuntimeV2Error> {
        let length = u32::from_be_bytes(
            self.take(4)?
                .try_into()
                .map_err(|_| GenerationStoreError::Corrupt)?,
        ) as usize;
        if length == 0 || length > maximum {
            return Err(GenerationStoreError::Corrupt.into());
        }
        self.take(length)
    }
    fn u64(&mut self) -> Result<u64, NeuronRuntimeV2Error> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| GenerationStoreError::Corrupt)?,
        ))
    }
    fn digest(&mut self) -> Result<Digest32, NeuronRuntimeV2Error> {
        Ok(Digest32::from_array(
            self.take(32)?
                .try_into()
                .map_err(|_| GenerationStoreError::Corrupt)?,
        ))
    }
}
