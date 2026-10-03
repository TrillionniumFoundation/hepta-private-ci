//! Actual fresh physical preparation. Integrity decoding grants no authority.
use super::*;
use crate::NeuronGenerationMaterialV2;
use crate::NeuronPreparedFileObservationV2;

const MAGIC: &[u8; 8] = b"HPTNPG02";
const DOMAIN: &[u8] = b"hepta.neuron.prepared-generation.v2";
pub const MAX_NEURON_PREPARED_GENERATION_BYTES_V2: usize =
    crate::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 + 32768;

pub struct NeuronPreparedGenerationV2 {
    bytes: Vec<u8>,
    material: NeuronGenerationMaterialV2,
    files: [NeuronPreparedFileObservationV2; 3],
}
impl NeuronPreparedGenerationV2 {
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn material(&self) -> &NeuronGenerationMaterialV2 {
        &self.material
    }
    pub fn files(&self) -> &[NeuronPreparedFileObservationV2; 3] {
        &self.files
    }

    /// The caller must authenticate the original exporter separately.
    pub fn from_bytes(
        bytes: Vec<u8>,
        expected_digest: Digest32,
    ) -> Result<Self, NeuronRuntimeV2Error> {
        if bytes.len() < 60
            || bytes.len() > MAX_NEURON_PREPARED_GENERATION_BYTES_V2
            || expected_digest.is_zero()
            || Digest32::of_bytes(&bytes) != expected_digest
        {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let end = bytes.len() - 32;
        if &bytes[..8] != MAGIC
            || Digest32::of_parts(&[DOMAIN, &bytes[..end]]).as_array() != &bytes[end..]
        {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let mut at = 8;
        let material = crate::decode_neuron_generation_material_v2(frame(
            &bytes[..end],
            &mut at,
            crate::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
        )?)
        .map_err(|_| NeuronRuntimeV2Error::RecoveryMismatch)?;
        let mut files = Vec::new();
        for _ in 0..3 {
            files.push(
                serde_json::from_slice::<NeuronPreparedFileObservationV2>(frame(
                    &bytes[..end],
                    &mut at,
                    8192,
                )?)
                .map_err(|_| NeuronRuntimeV2Error::RecoveryMismatch)?,
            );
        }
        if at != end {
            return Err(GenerationStoreError::Corrupt.into());
        }
        let files: [_; 3] = files
            .try_into()
            .map_err(|_| NeuronRuntimeV2Error::RecoveryMismatch)?;
        validate_prepared_files(&material, &files)?;
        let encoded = encode(&material, &files)?;
        if encoded != bytes {
            return Err(GenerationStoreError::Corrupt.into());
        }
        Ok(Self {
            bytes,
            material,
            files,
        })
    }
    pub fn validate_against(
        &self,
        expected: &NeuronGenerationMaterialV2,
    ) -> Result<(), NeuronRuntimeV2Error> {
        if crate::encode_neuron_generation_material_v2(expected)
            .map_err(|_| NeuronRuntimeV2Error::ContextMismatch)?
            != crate::encode_neuron_generation_material_v2(&self.material)
                .map_err(|_| NeuronRuntimeV2Error::ContextMismatch)?
        {
            return Err(NeuronRuntimeV2Error::ContextMismatch);
        }
        validate_prepared_files(expected, &self.files)
    }
}
impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    /// Uses only the three already-held descriptors and their original loaded
    /// contexts. It never reconciles, opens, recovers, ticks or acknowledges.
    pub fn export_prepared_generation_v2(
        &self,
        expected: &NeuronGenerationMaterialV2,
    ) -> Result<NeuronPreparedGenerationV2, NeuronRuntimeV2Error> {
        if self.checkpoint.is_some() || self.last_measurement.is_some() {
            return Err(NeuronRuntimeV2Error::PendingOperation);
        }
        self.validate_frontiers()?;
        let (store_context, store) = self.store.observe_fresh_prepared_v2()?;
        let (index_context, index) = self.index.observe_fresh_prepared_v2()?;
        let (witness_context, witness) = self.witness.observe_fresh_prepared_v2()?;
        let actual = NeuronGenerationMaterialV2 {
            // The original physical composition independently pins this
            // manifest; the loaded runtime owns its exact manifest digest.
            model_manifest: expected.model_manifest.clone(),
            model_manifest_digest: self.config.model_manifest_digest,
            generation_store: store.path.clone(),
            runtime_index: index.path.clone(),
            witness: witness.path.clone(),
            native: self.native.clone(),
            scope: self.store_context.scope,
            runtime: self.config.clone(),
            body: self.body_bundle.clone(),
            store_context,
            index_context,
            witness_context,
        };
        let files = [store, index, witness];
        let bytes = encode(&actual, &files)?;
        let result =
            NeuronPreparedGenerationV2::from_bytes(bytes.clone(), Digest32::of_bytes(&bytes))?;
        result.validate_against(expected)?;
        Ok(result)
    }
}
fn validate_prepared_files(
    plan: &NeuronGenerationMaterialV2,
    files: &[NeuronPreparedFileObservationV2; 3],
) -> Result<(), NeuronRuntimeV2Error> {
    crate::validate_neuron_generation_material_v2(plan)
        .map_err(|_| NeuronRuntimeV2Error::ContextMismatch)?;
    for (file, path) in
        files
            .iter()
            .zip([&plan.generation_store, &plan.runtime_index, &plan.witness])
    {
        file.validate().map_err(GenerationStoreError::from)?;
        if &file.path != path {
            return Err(NeuronRuntimeV2Error::ContextMismatch);
        }
    }
    for i in 0..3 {
        for j in i + 1..3 {
            if files[i].device == files[j].device && files[i].inode == files[j].inode {
                return Err(NeuronRuntimeV2Error::ContextMismatch);
            }
        }
    }
    crate::generation_store_v2::validate_fresh_prepared_header_v2(
        &files[0].header,
        &plan.store_context,
    )?;
    crate::runtime_index_v2::validate_fresh_prepared_header_v2(
        &files[1].header,
        &plan.index_context,
    )?;
    crate::witness_v2::validate_fresh_prepared_header_v2(&files[2].header, &plan.witness_context)?;
    Ok(())
}
fn encode(
    plan: &NeuronGenerationMaterialV2,
    files: &[NeuronPreparedFileObservationV2; 3],
) -> Result<Vec<u8>, NeuronRuntimeV2Error> {
    validate_prepared_files(plan, files)?;
    let mut bytes = MAGIC.to_vec();
    put(
        &mut bytes,
        &crate::encode_neuron_generation_material_v2(plan)
            .map_err(|_| NeuronRuntimeV2Error::ContextMismatch)?,
    )?;
    for file in files {
        put(
            &mut bytes,
            &serde_json::to_vec(file).map_err(|_| NeuronRuntimeV2Error::ContextMismatch)?,
        )?;
    }
    let digest = Digest32::of_parts(&[DOMAIN, &bytes]);
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}
fn put(out: &mut Vec<u8>, bytes: &[u8]) -> Result<(), NeuronRuntimeV2Error> {
    if bytes.is_empty()
        || out
            .len()
            .checked_add(bytes.len() + 36)
            .is_none_or(|n| n > MAX_NEURON_PREPARED_GENERATION_BYTES_V2)
    {
        return Err(GenerationStoreError::Capacity.into());
    }
    out.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
    out.extend_from_slice(bytes);
    Ok(())
}
fn frame<'a>(
    bytes: &'a [u8],
    at: &mut usize,
    max: usize,
) -> Result<&'a [u8], NeuronRuntimeV2Error> {
    let n = bytes
        .get(*at..*at + 4)
        .ok_or(GenerationStoreError::Corrupt)?;
    let len = u32::from_be_bytes(n.try_into().map_err(|_| GenerationStoreError::Corrupt)?) as usize;
    *at += 4;
    if len == 0 || len > max {
        return Err(GenerationStoreError::Corrupt.into());
    }
    let end = at.checked_add(len).ok_or(GenerationStoreError::Corrupt)?;
    let result = bytes.get(*at..end).ok_or(GenerationStoreError::Corrupt)?;
    *at = end;
    Ok(result)
}
