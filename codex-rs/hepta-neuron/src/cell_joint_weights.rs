//! Pure inspection of the exact weights format admitted by the Joint process.
//! This never starts a worker or produces an observed-loading receipt.

use codex_hepta_infer_core::JointTensorPacketV1;
use codex_hepta_infer_core::JointV4ComponentDigestsV1;
use codex_hepta_infer_core::JointV4TensorViewV1;
use codex_hepta_infer_core::JointV4WeightProjectionV1;
use codex_hepta_infer_core::project_joint_v4_weights_v1;
use codex_hepta_types::Digest32;

use crate::CellGenerationErrorV2;

pub(crate) const MAX_JOINT_WEIGHTS_BYTES: usize = 8 * 1024 * 1024;

/// Content-derived identity only. The complete projection and physical packet
/// digest cannot be supplied independently or modified through this value.
#[derive(Clone, Debug, PartialEq)]
pub struct JointGenerationWeightInspectionV1 {
    physical_weights_digest: Digest32,
    weights_bytes: u64,
    projection: JointV4WeightProjectionV1,
}

impl JointGenerationWeightInspectionV1 {
    pub fn physical_weights_digest(&self) -> Digest32 {
        self.physical_weights_digest
    }

    pub fn weights_bytes(&self) -> u64 {
        self.weights_bytes
    }

    pub fn decoded_weights_digest(&self) -> Digest32 {
        self.projection.decoded_weights_digest()
    }

    pub fn components(&self) -> &JointV4ComponentDigestsV1 {
        self.projection.components()
    }
}

/// Inspect canonical HEPTAPK3 bytes under the existing process's 8 MiB limit
/// and width32/depth1/dual/direct profile. All thirteen component positions are
/// derived by the same projector called by the native Model loader. Parsing
/// these bytes does not prove that any model process has loaded or used them.
pub fn inspect_joint_v4_generation_weights_v1(
    bytes: &[u8],
) -> Result<JointGenerationWeightInspectionV1, CellGenerationErrorV2> {
    if bytes.is_empty() || bytes.len() > MAX_JOINT_WEIGHTS_BYTES {
        return Err(CellGenerationErrorV2::Capacity);
    }
    let packet =
        JointTensorPacketV1::decode(bytes).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    if packet
        .encode()
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?
        != bytes
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let text = |key| {
        packet
            .text(key)
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)
    };
    if text("width")?.parse::<usize>().ok() != Some(32)
        || text("depth")?.parse::<usize>().ok() != Some(1)
        || text("mode")? != "dual"
        || text("boundary")? != "direct"
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let projection = project_joint_v4_weights_v1(
        &packet.meta,
        packet
            .tensors
            .iter()
            .map(|(name, tensor)| JointV4TensorViewV1 {
                name,
                shape: &tensor.shape,
                values: &tensor.data,
            }),
    )
    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    Ok(JointGenerationWeightInspectionV1 {
        physical_weights_digest: Digest32::of_bytes(bytes),
        weights_bytes: bytes.len() as u64,
        projection,
    })
}
