//! Reconstructible commitments for one completely projected Joint v4 model.
//! These pure hashes do not authenticate a loader or attest any execution.

use codex_hepta_types::Digest32;

use crate::JointV4ComponentDigestsV1;
use crate::JointV4WeightProjectionV1;

pub const JOINT_V4_LOADING_PROCESS_PROFILE: &str = "joint-generator-proposal-linux-v3";

/// Bind the complete physical packet and all thirteen typed component positions.
/// The whole-file SHA binds the complete byte sequence, including its length.
/// Actual canonical decoding and the original packet bounds remain mandatory.
/// The two overlays are absent in this profile; a different composition requires
/// a new explicit loading contract, rather than an invented overlay proof.
pub fn joint_v4_loading_commitment_v1(
    physical_weights_digest: [u8; 32],
    components: &JointV4ComponentDigestsV1,
) -> Result<[u8; 32], String> {
    if physical_weights_digest == [0; 32]
        || components.organ_adapter.is_some()
        || components.cell_adapter.is_some()
    {
        return Err("invalid Joint v4 loading composition".into());
    }
    let positions = [
        Some(components.base),
        components.organ_adapter,
        components.cell_adapter,
        Some(components.heads),
        Some(components.composition),
        Some(components.encoder),
        Some(components.tokenizer),
        Some(components.normalizer),
        Some(components.calibration),
        Some(components.numeric_profile),
        Some(components.output_schema),
        Some(components.state_schema),
        Some(components.state_semantics),
    ];
    let mut bytes = physical_weights_digest.to_vec();
    for value in positions {
        match value {
            Some(value) if value.into_array() != [0; 32] => {
                bytes.push(1);
                bytes.extend(value.as_array());
            }
            Some(_) => return Err("empty Joint v4 loading component".into()),
            None => bytes.push(0),
        }
    }
    Ok(Digest32::of_parts(&[
        b"hepta.joint.v4.physical-model-loading-commitment.v1\0",
        &bytes,
    ])
    .into_array())
}

impl JointV4WeightProjectionV1 {
    /// Called on the immutable projection owned by the actual native Model.
    /// The caller must supply that Model's already validated canonical packet.
    /// A pure call alone remains a content binding, not an execution receipt.
    pub fn loading_commitment_v1(&self, physical_weights: &[u8]) -> Result<[u8; 32], String> {
        joint_v4_loading_commitment_v1(
            Digest32::of_bytes(physical_weights).into_array(),
            self.components(),
        )
    }
}
