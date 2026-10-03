//! Full original port input bytes; decoding grants no execution or admission.
use crate::CanonicalIntelligenceError;
use crate::CanonicalPortInputV1;
use crate::CanonicalStageV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1: usize = 16 * 1024;
const MAGIC: &[u8; 8] = b"HPTCPI01";
fn invalid() -> CanonicalIntelligenceError {
    CanonicalIntelligenceError::InvalidSnapshot("canonical port material")
}
pub fn encode_canonical_port_input_material_v1(
    input: &CanonicalPortInputV1,
) -> Result<Vec<u8>, CanonicalIntelligenceError> {
    let id = input.run_id.as_str().as_bytes();
    let length = u16::try_from(id.len()).map_err(|_| invalid())?;
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(id);
    for digest in [
        input.snapshot_digest,
        input.objective_digest,
        input.candidate_set_digest,
        input.predecessor_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&input.budget_micros.to_be_bytes());
    bytes.push(match input.stage {
        CanonicalStageV1::ObjectiveValidated => 0,
        CanonicalStageV1::UtilityEvaluated => 1,
        CanonicalStageV1::NeuralSignalCollected => 2,
        CanonicalStageV1::PromptPortfolioBuilt => 3,
        CanonicalStageV1::IntuitionDecided => 4,
        CanonicalStageV1::ContextCompiled => 5,
        CanonicalStageV1::EvaluationAdmitted => 6,
    });
    if bytes.len() > MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1 {
        return Err(invalid());
    }
    Ok(bytes)
}
pub fn decode_canonical_port_input_material_v1(
    bytes: &[u8],
) -> Result<CanonicalPortInputV1, CanonicalIntelligenceError> {
    if bytes.len() > MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1 || bytes.get(..8) != Some(MAGIC) {
        return Err(invalid());
    }
    let length = u16::from_be_bytes(
        bytes
            .get(8..10)
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
    ) as usize;
    let end = 10usize.checked_add(length).ok_or_else(invalid)?;
    if bytes.len() != end + 128 + 8 + 1 {
        return Err(invalid());
    }
    let run_id = StableId::new(
        std::str::from_utf8(bytes.get(10..end).ok_or_else(invalid)?)
            .map_err(|_| invalid())?
            .to_owned(),
    )
    .map_err(|_| invalid())?;
    let digest = |offset: usize| -> Result<Digest32, CanonicalIntelligenceError> {
        Ok(Digest32::from_array(
            bytes
                .get(offset..offset + 32)
                .ok_or_else(invalid)?
                .try_into()
                .map_err(|_| invalid())?,
        ))
    };
    let stage = match bytes[end + 136] {
        0 => CanonicalStageV1::ObjectiveValidated,
        1 => CanonicalStageV1::UtilityEvaluated,
        2 => CanonicalStageV1::NeuralSignalCollected,
        3 => CanonicalStageV1::PromptPortfolioBuilt,
        4 => CanonicalStageV1::IntuitionDecided,
        5 => CanonicalStageV1::ContextCompiled,
        6 => CanonicalStageV1::EvaluationAdmitted,
        _ => return Err(invalid()),
    };
    let port = CanonicalPortInputV1 {
        run_id,
        snapshot_digest: digest(end)?,
        objective_digest: digest(end + 32)?,
        candidate_set_digest: digest(end + 64)?,
        predecessor_digest: digest(end + 96)?,
        budget_micros: u64::from_be_bytes(
            bytes[end + 128..end + 136]
                .try_into()
                .map_err(|_| invalid())?,
        ),
        stage,
    };
    if encode_canonical_port_input_material_v1(&port)? != bytes {
        return Err(invalid());
    }
    Ok(port)
}
#[cfg(test)]
#[path = "canonical_port_material_v1_tests.rs"]
mod tests;
