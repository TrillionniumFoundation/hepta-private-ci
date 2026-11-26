//! CAS materialization and reload for a `MemoryRead` parameter bundle.
//!
//! The MemoryCell lab (#1452) owns an experimental bundle format and training
//! workflow.  This module does not decode that format.  It supplies the
//! production owner boundary around already encoded bytes: the bytes must
//! match the typed child manifest, be written through the existing create-only
//! CAS owner, and reload through the signed write receipt before they can be
//! bound to a `MemoryReadArtifactV1`.

use std::error::Error;
use std::fmt;
use std::fs::File;
use std::path::Path;

use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactCasOwnerV1;
use crate::ArtifactLoadReceiptV1;
use crate::ArtifactRegistry;
use crate::ArtifactWriteReceiptV1;
use crate::CellArtifactOwnerErrorV1;
use crate::CellParameterBundleManifestV1;
use crate::MemoryReadArtifactOwnerV1;
use crate::MemoryReadArtifactReceiptV1;
use crate::MemoryReadArtifactV1;
use crate::MemoryReadOwnerErrorV1;
use crate::ProductionOwnerError;

/// The complete witness returned after a MemoryRead bundle has been written to
/// the CAS and bound to its typed artifact definition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadBundleMaterializationV1 {
    pub artifact: MemoryReadArtifactV1,
    pub artifact_receipt: MemoryReadArtifactReceiptV1,
    pub write_receipt: ArtifactWriteReceiptV1,
    pub bundle_digest: Digest32,
    pub encoded_size_bytes: u64,
}

impl MemoryReadBundleMaterializationV1 {
    fn validate(&self) -> Result<(), MemoryReadBundleOwnerErrorV1> {
        self.artifact.validate()?;
        self.artifact_receipt.validate_against(&self.artifact)?;
        self.write_receipt
            .artifact_digest
            .eq(&self.bundle_digest)
            .then_some(())
            .ok_or(MemoryReadBundleOwnerErrorV1::Binding(
                "write receipt bundle digest",
            ))?;
        if self.bundle_digest != self.artifact.parameter_manifest.child_bundle_digest
            || self.encoded_size_bytes != self.write_receipt.encoded_size_bytes
            || self.encoded_size_bytes == 0
        {
            return Err(MemoryReadBundleOwnerErrorV1::Binding(
                "materialization manifest",
            ));
        }
        Ok(())
    }
}

/// A signed CAS load witness joined to the typed MemoryRead artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadBundleReloadV1 {
    pub artifact: MemoryReadArtifactV1,
    pub artifact_receipt: MemoryReadArtifactReceiptV1,
    pub payload: Vec<u8>,
    pub load_receipt: ArtifactLoadReceiptV1,
}

impl MemoryReadBundleReloadV1 {
    pub fn validate(&self) -> Result<(), MemoryReadBundleOwnerErrorV1> {
        self.artifact.validate()?;
        self.artifact_receipt.validate_against(&self.artifact)?;
        if self.payload.is_empty()
            || Digest32::of_bytes(&self.payload)
                != self.artifact.parameter_manifest.child_bundle_digest
            || self.load_receipt.artifact_digest
                != self.artifact.parameter_manifest.child_bundle_digest
            || self.load_receipt.payload_digest != Digest32::of_bytes(&self.payload)
            || self.load_receipt.encoded_size_bytes != self.payload.len() as u64
        {
            return Err(MemoryReadBundleOwnerErrorV1::Binding("reload payload"));
        }
        Ok(())
    }
}

/// Errors from the MemoryRead-specific CAS owner boundary.
#[derive(Debug)]
pub enum MemoryReadBundleOwnerErrorV1 {
    Artifact(MemoryReadOwnerErrorV1),
    Production(ProductionOwnerError),
    Manifest(CellArtifactOwnerErrorV1),
    Binding(&'static str),
}

impl fmt::Display for MemoryReadBundleOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for MemoryReadBundleOwnerErrorV1 {}

impl From<MemoryReadOwnerErrorV1> for MemoryReadBundleOwnerErrorV1 {
    fn from(value: MemoryReadOwnerErrorV1) -> Self {
        Self::Artifact(value)
    }
}

impl From<ProductionOwnerError> for MemoryReadBundleOwnerErrorV1 {
    fn from(value: ProductionOwnerError) -> Self {
        Self::Production(value)
    }
}

impl From<CellArtifactOwnerErrorV1> for MemoryReadBundleOwnerErrorV1 {
    fn from(value: CellArtifactOwnerErrorV1) -> Self {
        Self::Manifest(value)
    }
}

impl MemoryReadArtifactOwnerV1 {
    /// Materialize one already encoded MemoryRead bundle through the signed
    /// CAS owner.  The owner does not train or decode the payload.  It checks
    /// that the exact bytes hash to the child manifest before accepting the
    /// write receipt and binding the artifact to that payload digest.
    #[allow(clippy::too_many_arguments)]
    pub fn materialize_bundle(
        &self,
        cas_owner: &ArtifactCasOwnerV1,
        operation_id: StableId,
        root: impl AsRef<Path>,
        relative: impl AsRef<Path>,
        registry: &ArtifactRegistry,
        definition: CellDefinitionV2,
        parameter_manifest: CellParameterBundleManifestV1,
        bundle_bytes: &[u8],
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<MemoryReadBundleMaterializationV1, MemoryReadBundleOwnerErrorV1> {
        validate_bundle_inputs(&definition, &parameter_manifest, bundle_bytes)?;
        let write_receipt = cas_owner.write_candidate(
            operation_id,
            root,
            relative,
            registry,
            &parameter_manifest.artifact_id,
            bundle_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )?;
        if write_receipt.artifact_digest != parameter_manifest.child_bundle_digest
            || write_receipt.encoded_size_bytes != bundle_bytes.len() as u64
        {
            return Err(MemoryReadBundleOwnerErrorV1::Binding("CAS write receipt"));
        }
        let bundle_digest = Digest32::of_bytes(bundle_bytes);
        let (artifact, artifact_receipt) =
            self.bind_registered(registry, definition, parameter_manifest, bundle_digest)?;
        let materialization = MemoryReadBundleMaterializationV1 {
            artifact,
            artifact_receipt,
            write_receipt,
            bundle_digest,
            encoded_size_bytes: bundle_bytes.len() as u64,
        };
        materialization.validate()?;
        Ok(materialization)
    }

    /// Reload one materialized bundle from a file opened beneath the host's
    /// trusted root.  The generic CAS owner verifies the signed write receipt
    /// and exact payload digest; this method then rebinds the typed artifact,
    /// so a valid byte file cannot be substituted under another definition or
    /// generation.
    #[allow(clippy::too_many_arguments)]
    pub fn reload_bundle(
        &self,
        cas_owner: &ArtifactCasOwnerV1,
        operation_id: StableId,
        file: File,
        registry: &ArtifactRegistry,
        definition: CellDefinitionV2,
        parameter_manifest: CellParameterBundleManifestV1,
        expected_write: &ArtifactWriteReceiptV1,
        relative: impl AsRef<Path>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<MemoryReadBundleReloadV1, MemoryReadBundleOwnerErrorV1> {
        validate_bundle_inputs(&definition, &parameter_manifest, &[])?;
        let (payload, load_receipt) = cas_owner.load_candidate(
            operation_id,
            file,
            registry,
            &parameter_manifest.artifact_id,
            expected_write,
            relative,
            host_evidence_digest,
            observer_evidence_digest,
        )?;
        validate_bundle_inputs(&definition, &parameter_manifest, &payload)?;
        if load_receipt.artifact_digest != parameter_manifest.child_bundle_digest {
            return Err(MemoryReadBundleOwnerErrorV1::Binding("CAS load receipt"));
        }
        let (artifact, artifact_receipt) = self.bind_registered(
            registry,
            definition,
            parameter_manifest,
            load_receipt.payload_digest,
        )?;
        let reload = MemoryReadBundleReloadV1 {
            artifact,
            artifact_receipt,
            payload,
            load_receipt,
        };
        reload.validate()?;
        Ok(reload)
    }
}

fn validate_bundle_inputs(
    definition: &CellDefinitionV2,
    parameter_manifest: &CellParameterBundleManifestV1,
    bundle_bytes: &[u8],
) -> Result<(), MemoryReadBundleOwnerErrorV1> {
    definition
        .validate()
        .map_err(|_| MemoryReadBundleOwnerErrorV1::Binding("definition"))?;
    parameter_manifest.validate()?;
    if definition.role != codex_hepta_types::CellRoleV1::MemoryRead
        || parameter_manifest.cell_id != definition.cell_id
        || parameter_manifest.generation != definition.generation
        || parameter_manifest.scope_digest != definition.scope_digest
        || parameter_manifest.definition_digest
            != definition
                .content_digest()
                .map_err(|_| MemoryReadBundleOwnerErrorV1::Binding("definition digest"))?
        || parameter_manifest.child_bundle_digest != definition.parameter_bundle_digest
    {
        return Err(MemoryReadBundleOwnerErrorV1::Binding("definition manifest"));
    }
    if !bundle_bytes.is_empty()
        && (Digest32::of_bytes(bundle_bytes) != parameter_manifest.child_bundle_digest
            || bundle_bytes.len() as u64 != parameter_manifest.encoded_size_bytes)
    {
        return Err(MemoryReadBundleOwnerErrorV1::Binding("bundle bytes"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "memory_read_cas_tests.rs"]
mod tests;
