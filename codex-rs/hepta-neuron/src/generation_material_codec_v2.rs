//! Bounded complete immutable plan bytes. Decoding grants no owner or worker.
use crate::NeuronGenerationMaterialErrorV2;
use crate::NeuronGenerationMaterialV2;
use crate::validate_neuron_generation_material_v2;
use serde::Deserialize;
use serde::Serialize;
#[path = "generation_material_dto_v2.rs"]
mod dto;

pub const MAX_NEURON_GENERATION_MATERIAL_BYTES_V2: usize = 262_144;
const SCHEMA: &str = "hepta.cpu-neuron.full-generation-material.v2";
#[derive(Serialize)]
struct Borrowed<'a> {
    schema: &'static str,
    #[serde(with = "dto::Plan")]
    plan: &'a NeuronGenerationMaterialV2,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Owned {
    schema: String,
    #[serde(with = "dto::Plan")]
    plan: NeuronGenerationMaterialV2,
}

pub fn encode_neuron_generation_material_v2(
    plan: &NeuronGenerationMaterialV2,
) -> Result<Vec<u8>, NeuronGenerationMaterialErrorV2> {
    validate_neuron_generation_material_v2(plan)?;
    let mut writer = Bounded(Vec::new());
    serde_json::to_writer(
        &mut writer,
        &Borrowed {
            schema: SCHEMA,
            plan,
        },
    )?;
    Ok(writer.0)
}

pub fn decode_neuron_generation_material_v2(
    bytes: &[u8],
) -> Result<NeuronGenerationMaterialV2, NeuronGenerationMaterialErrorV2> {
    if bytes.is_empty() || bytes.len() > MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 {
        return Err(NeuronGenerationMaterialErrorV2::Invalid(
            "full generation material byte bound".into(),
        ));
    }
    let owned: Owned = serde_json::from_slice(bytes)?;
    if owned.schema != SCHEMA {
        return Err(NeuronGenerationMaterialErrorV2::Invalid(
            "full generation material schema".into(),
        ));
    }
    validate_neuron_generation_material_v2(&owned.plan)?;
    // Freeze one canonical representation; reordered, duplicated or omitted
    // fields cannot provide another Source identity for this original plan.
    if encode_neuron_generation_material_v2(&owned.plan)? != bytes {
        return Err(NeuronGenerationMaterialErrorV2::Invalid(
            "noncanonical full generation material".into(),
        ));
    }
    Ok(owned.plan)
}

struct Bounded(Vec<u8>);
impl std::io::Write for Bounded {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if self.0.len().saturating_add(bytes.len()) > MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 {
            return Err(std::io::Error::other("full generation material byte bound"));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
#[path = "generation_material_codec_v2_tests.rs"]
mod tests;
