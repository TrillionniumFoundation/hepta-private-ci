//! Frozen-encoder research Head handoff. The exporter verifies the training
//! manifest and tensor inventory; the owner authenticates the complete bundle.
//! Native readback checks independent identity pins and preserves original bytes.
//! It does not infer training quality, evaluator independence, or activation rights.

use std::fmt;
use std::ops::Range;

use codex_hepta_types::Digest32;

use crate::ArtifactKind;
use crate::ProvenanceModeV1;
use crate::VerifiedArtifactReadV1;

const MAGIC: &[u8] = b"HEPTA-CELL-HEAD-BUNDLE-V1\0";
const MAX_MANIFEST_BYTES: usize = 2 * 1024 * 1024;
const MAX_WEIGHTS_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellHeadFeatureIdentityV1 {
    pub encoder_digest: Digest32,
    /// SHA-256 of the exact UTF-8 checkpoint revision, not the revision itself.
    pub checkpoint_digest: Digest32,
    pub preprocessing_digest: Digest32,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation: u64,
    pub revocation_epoch: u64,
    pub width: u64,
}

impl CellHeadFeatureIdentityV1 {
    pub fn compatibility_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-head-feature.v1\0",
            self.encoder_digest.as_array(),
            self.checkpoint_digest.as_array(),
            self.preprocessing_digest.as_array(),
            self.scope_digest.as_array(),
            self.purpose_digest.as_array(),
            &self.generation.to_le_bytes(),
            &self.revocation_epoch.to_le_bytes(),
            &self.width.to_le_bytes(),
        ])
    }
}

/// Independently retained export identities. Do not derive these pins from the
/// same untrusted payload immediately before verification.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellHeadBundleIdentityV1 {
    pub feature: CellHeadFeatureIdentityV1,
    pub manifest_digest: Digest32,
    pub weights_digest: Digest32,
    pub source_frontier_digest: Digest32,
    pub training_dataset_digest: Digest32,
    pub calibration_dataset_digest: Digest32,
    pub training_code_digest: Digest32,
    pub runtime_tuple_digest: Digest32,
    pub trained_tensor_digest: Digest32,
}

/// Issued from persisted bytes authenticated by the existing artifact owner.
/// This is a point-in-time, deny-all research binding, not a model executor.
#[derive(Debug)]
pub struct VerifiedCellHeadBindingV1 {
    artifact: VerifiedArtifactReadV1,
    identity: CellHeadBundleIdentityV1,
    manifest_range: Range<usize>,
    weights_range: Range<usize>,
}

impl VerifiedCellHeadBindingV1 {
    pub fn artifact(&self) -> &VerifiedArtifactReadV1 {
        &self.artifact
    }

    pub fn identity(&self) -> &CellHeadBundleIdentityV1 {
        &self.identity
    }

    pub fn manifest_json(&self) -> &[u8] {
        &self.artifact.bytes()[self.manifest_range.clone()]
    }

    pub fn weights_npz(&self) -> &[u8] {
        &self.artifact.bytes()[self.weights_range.clone()]
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellHeadBundleErrorV1 {
    InvalidEncoding,
    PayloadMismatch,
    IdentityMismatch,
    OwnerManifestMismatch,
}

impl fmt::Display for CellHeadBundleErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellHeadBundleErrorV1 {}

pub fn verify_cell_head_bundle(
    artifact: VerifiedArtifactReadV1,
    expected: &CellHeadBundleIdentityV1,
) -> Result<VerifiedCellHeadBindingV1, CellHeadBundleErrorV1> {
    let (identity, manifest_range, weights_range) = decode(artifact.bytes())?;
    if &identity != expected {
        return Err(CellHeadBundleErrorV1::IdentityMismatch);
    }
    let manifest = artifact.manifest();
    let mut sources = vec![
        identity.training_dataset_digest,
        identity.calibration_dataset_digest,
    ];
    sources.sort();
    if manifest.kind != ArtifactKind::Parameters
        || manifest.provenance_mode != ProvenanceModeV1::DatasetDerived
        || manifest.source_dataset_digests != sources
        || manifest.training_code_digest != identity.training_code_digest
        || manifest.runtime_tuple_digest != identity.runtime_tuple_digest
        || manifest.normalization_digest != identity.feature.preprocessing_digest
        || manifest.compatibility_digest != identity.feature.compatibility_digest()
        || manifest.schema_profile_digest != Digest32::of_bytes(MAGIC)
        || !manifest.lineage_digests.contains(&identity.manifest_digest)
        || !manifest
            .lineage_digests
            .contains(&identity.trained_tensor_digest)
        || !manifest
            .lineage_digests
            .contains(&identity.source_frontier_digest)
    {
        return Err(CellHeadBundleErrorV1::OwnerManifestMismatch);
    }
    Ok(VerifiedCellHeadBindingV1 {
        artifact,
        identity,
        manifest_range,
        weights_range,
    })
}

struct Decoder<'a>(&'a [u8]);

impl Decoder<'_> {
    fn take<const N: usize>(&mut self) -> Result<[u8; N], CellHeadBundleErrorV1> {
        let (value, rest) = self
            .0
            .split_at_checked(N)
            .ok_or(CellHeadBundleErrorV1::InvalidEncoding)?;
        self.0 = rest;
        value
            .try_into()
            .map_err(|_| CellHeadBundleErrorV1::InvalidEncoding)
    }

    fn digest(&mut self) -> Result<Digest32, CellHeadBundleErrorV1> {
        let value = Digest32::from_array(self.take()?);
        if value.is_zero() {
            return Err(CellHeadBundleErrorV1::InvalidEncoding);
        }
        Ok(value)
    }

    fn number(&mut self) -> Result<u64, CellHeadBundleErrorV1> {
        Ok(u64::from_le_bytes(self.take()?))
    }
}

fn decode(
    bytes: &[u8],
) -> Result<(CellHeadBundleIdentityV1, Range<usize>, Range<usize>), CellHeadBundleErrorV1> {
    let mut decoder = Decoder(
        bytes
            .strip_prefix(MAGIC)
            .ok_or(CellHeadBundleErrorV1::InvalidEncoding)?,
    );
    let identity = CellHeadBundleIdentityV1 {
        feature: CellHeadFeatureIdentityV1 {
            encoder_digest: decoder.digest()?,
            checkpoint_digest: decoder.digest()?,
            preprocessing_digest: decoder.digest()?,
            scope_digest: decoder.digest()?,
            purpose_digest: decoder.digest()?,
            generation: decoder.number()?,
            revocation_epoch: decoder.number()?,
            width: decoder.number()?,
        },
        manifest_digest: decoder.digest()?,
        weights_digest: decoder.digest()?,
        source_frontier_digest: decoder.digest()?,
        training_dataset_digest: decoder.digest()?,
        calibration_dataset_digest: decoder.digest()?,
        training_code_digest: decoder.digest()?,
        runtime_tuple_digest: decoder.digest()?,
        trained_tensor_digest: decoder.digest()?,
    };
    let manifest_len =
        usize::try_from(decoder.number()?).map_err(|_| CellHeadBundleErrorV1::InvalidEncoding)?;
    let weights_len =
        usize::try_from(decoder.number()?).map_err(|_| CellHeadBundleErrorV1::InvalidEncoding)?;
    if identity.feature.generation == 0
        || !(1..=65_536).contains(&identity.feature.width)
        || !(1..=MAX_MANIFEST_BYTES).contains(&manifest_len)
        || !(1..=MAX_WEIGHTS_BYTES).contains(&weights_len)
        || decoder.0.len() != manifest_len + weights_len
    {
        return Err(CellHeadBundleErrorV1::InvalidEncoding);
    }
    let start = bytes.len() - decoder.0.len();
    let manifest_range = start..start + manifest_len;
    let weights_range = manifest_range.end..bytes.len();
    if Digest32::of_bytes(&bytes[manifest_range.clone()]) != identity.manifest_digest
        || Digest32::of_bytes(&bytes[weights_range.clone()]) != identity.weights_digest
    {
        return Err(CellHeadBundleErrorV1::PayloadMismatch);
    }
    Ok((identity, manifest_range, weights_range))
}

#[cfg(test)]
#[path = "cell_head_bundle_tests.rs"]
mod tests;
