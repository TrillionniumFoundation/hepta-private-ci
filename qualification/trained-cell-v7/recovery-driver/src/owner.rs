//! Reuse the unchanged fenced owner; select only the actual payload schema.
#[path = "../../../trained-cell-v5/actual-review-driver/src/owner.rs"]
mod legacy;
pub(crate) use legacy::digest;
pub(crate) use legacy::hex;
pub(crate) use legacy::id;
pub(crate) use legacy::inventory;
pub(crate) use legacy::request;
pub(crate) use legacy::trust;

use crate::handoff_version::Handoff;
use crate::*;

pub(crate) fn manifest(
    name: &str,
    payload: &[u8],
    previous: Option<codex_hepta_types::StableId>,
    inputs: &report::Inputs,
    now: u64,
) -> Result<LearningArtifactManifestV2> {
    let mut result = legacy::manifest(name, payload, previous, inputs, now)?;
    if Handoff::recognizes(payload) {
        let bundle = Handoff::decode(payload, Digest32::of_bytes(payload))?;
        ensure(
            bundle.artifact_id().as_str() == name
                && bundle.generation() == result.generation
                && bundle.protocol_digest() == inputs.policy.protocol_digest,
            "handoff manifest identity differs",
        )?;
        result.compatibility_digest = bundle.compatibility_digest();
        result.schema_profile_digest = result.compatibility_digest;
    }
    Ok(result)
}
