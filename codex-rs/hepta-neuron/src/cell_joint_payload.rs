//! Build the original owner-bound request; resident callers refresh the live
//! budget after waiting for their transport and omit only immutable assets.

use super::JointGenerationProcessWorkerV1;
use crate::CellBackendManifestV2;
use crate::CellGenerationErrorV2;
use crate::CellGenerationRequestV2;
use crate::JointGenerationInputV1;
use crate::JointGenerationInputV2;
use crate::cell_joint_observed;
use crate::cell_joint_protocol;

impl JointGenerationProcessWorkerV1 {
    pub(super) fn request_payload(
        &self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
        include_assets: bool,
        resident_clock: Option<u64>,
    ) -> Result<Vec<u8>, CellGenerationErrorV2> {
        let weights = if include_assets {
            self.weights.as_slice()
        } else {
            &[]
        };
        let public = if include_assets {
            self.public.as_slice()
        } else {
            &[]
        };
        if matches!(
            manifest.profile.as_str(),
            Self::OBSERVED_PROFILE | Self::RESIDENT_OBSERVED_PROFILE
        ) {
            let input = serde_json::from_slice::<JointGenerationInputV2>(&request.input)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
            if input.public_digest != self.public_digest {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            let now = resident_clock.unwrap_or_else(|| (self.clock)());
            if now == 0 {
                return Err(CellGenerationErrorV2::Unavailable);
            }
            cell_joint_observed::request_bytes(request, &input, weights, public, now)
        } else {
            let input = serde_json::from_slice::<JointGenerationInputV1>(&request.input)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
            if input.public_digest != self.public_digest {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            cell_joint_protocol::request_bytes(
                request.digest()?,
                weights,
                public,
                &request.predecessor.state,
                &request.predecessor.prefix,
                &input.command,
            )
        }
    }
}
