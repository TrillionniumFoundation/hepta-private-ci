//! Additional validation for one fixed, non-installing initial material profile.
//! Expected upstream identities are commitments, not observations of main model
//! bytes. Only the original independent selector reaches this private consumer.

use codex_hepta_types::Digest32;

use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactSelectionError;
use crate::LoadedPinnedCandidate;

pub(super) const PROFILE: &[u8] =
    include_bytes!("../profiles/smollm2-initial-positive-zero-v1.profile");
const HEADER: &[u8] =
    include_bytes!("../profiles/smollm2-initial-positive-zero-v1.safetensors.header");
const FACTOR_BYTES: usize = 230_400 * 4;

pub(super) fn validate_manifest(manifest: &ArtifactManifest) -> Result<(), ArtifactSelectionError> {
    if manifest.compatibility_digest != Digest32::of_bytes(PROFILE) {
        return Ok(());
    }
    if manifest.kind != ArtifactKind::Parameters
        || manifest.generation.get() != 1
        || manifest.predecessor_id.is_some()
        || manifest.encoded_size_bytes != (8 + HEADER.len() + FACTOR_BYTES) as u64
    {
        return Err(ArtifactSelectionError::InitialGenesisMaterial);
    }
    Ok(())
}

pub(super) fn validate_payload(
    loaded: &LoadedPinnedCandidate,
) -> Result<(), ArtifactSelectionError> {
    let manifest = &loaded.spec().manifest;
    if manifest.compatibility_digest != Digest32::of_bytes(PROFILE) {
        return Ok(());
    }
    validate_manifest(manifest)?;
    let bytes = loaded.bytes();
    let factors_start = 8 + HEADER.len();
    // This additive profile has ONE canonical safetensors wire representation.
    // Comparing the complete code-owned header rejects duplicate/unknown keys,
    // altered dtype/shape/ranges, metadata aliases and every alternative JSON
    // encoding without interpreting untrusted lengths or allocating a parser.
    if bytes.len() != factors_start + FACTOR_BYTES
        || bytes.get(..8) != Some((HEADER.len() as u64).to_le_bytes().as_slice())
        || bytes.get(8..factors_start) != Some(HEADER)
        || bytes[factors_start..].iter().any(|byte| *byte != 0)
    {
        return Err(ArtifactSelectionError::InitialGenesisMaterial);
    }
    Ok(())
}

#[cfg(test)]
#[path = "initial_smollm_genesis_tests.rs"]
mod tests;
