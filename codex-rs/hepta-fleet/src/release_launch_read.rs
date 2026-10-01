use super::*;
#[cfg(unix)]
use crate::LaunchDigestDomain;
use crate::ReleaseReadPin;
#[cfg(unix)]
use crate::VerifiedLaunchDigest;

impl FleetRegistry {
    /// Read installed bytes outside the writer lane and pin only their facts.
    pub fn prevalidate_release_for_launch(
        &self,
        release_id: &ReleaseId,
    ) -> Result<ReleaseReadPin, FleetRegistryError> {
        let (release, validated_manifest_sha256) = resolve_catalog_release_with_manifest(
            self, release_id, /*defer_cold_read*/ false,
        )?;
        let manifest_path = release_manifest_path(self.layout().releases_root(), release_id);
        let manifest = self
            .release_digests
            .manifest(&manifest_path, MAX_RELEASE_MANIFEST_BYTES)?;
        if manifest.sha256 != validated_manifest_sha256 {
            return Err(FleetRegistryError::ReleasePrevalidationRequired);
        }
        let mut paths = vec![release.program];
        if let Some(matrix) = release.matrixd {
            paths.push(matrix.program);
        }
        self.release_digests.pin_programs(&paths, &manifest)
    }

    /// Return the exact original raw-byte prefix, with native final-use guards.
    #[cfg(unix)]
    pub fn launch_digest_prefix(
        &self,
        program: &Path,
        domain: LaunchDigestDomain,
    ) -> Result<VerifiedLaunchDigest, FleetRegistryError> {
        let relative = program
            .strip_prefix(self.layout().releases_root())
            .map_err(|_| {
                FleetRegistryError::Invalid("launch program is outside the catalog".into())
            })?;
        let name = relative
            .components()
            .next()
            .and_then(|part| part.as_os_str().to_str())
            .ok_or_else(|| FleetRegistryError::Invalid("launch catalog path is invalid".into()))?;
        let release_id = ReleaseId::parse(name)?;
        let (release, validated_manifest_sha256) = resolve_catalog_release_with_manifest(
            self,
            &release_id,
            /*defer_cold_read*/ false,
        )?;
        let manifest_path = release_manifest_path(self.layout().releases_root(), &release_id);
        let manifest = self
            .release_digests
            .manifest(&manifest_path, MAX_RELEASE_MANIFEST_BYTES)?;
        if manifest.sha256 != validated_manifest_sha256 {
            return Err(FleetRegistryError::ReleasePrevalidationRequired);
        }
        let metadata: CatalogReleaseMetadata =
            serde_json::from_slice(&manifest.bytes).map_err(|error| {
                FleetRegistryError::Corrupt(format!("invalid release JSON: {error}"))
            })?;
        let expected = match (metadata, domain) {
            (CatalogReleaseMetadata::V2(metadata), LaunchDigestDomain::Agent) => {
                validate_metadata(&metadata, &release_id)?;
                if release.program != program {
                    return Err(invalid_program());
                }
                metadata.agentd.program_sha256
            }
            (CatalogReleaseMetadata::V2(metadata), LaunchDigestDomain::Matrix) => {
                validate_metadata(&metadata, &release_id)?;
                if release
                    .matrixd
                    .as_ref()
                    .map(|matrix| matrix.program.as_path())
                    != Some(program)
                {
                    return Err(invalid_program());
                }
                metadata.matrixd.ok_or_else(invalid_program)?.program_sha256
            }
            (CatalogReleaseMetadata::V1(metadata), LaunchDigestDomain::Agent) => {
                validate_legacy_metadata(&metadata, &release_id)?;
                if release.program != program {
                    return Err(invalid_program());
                }
                metadata.program_sha256
            }
            (CatalogReleaseMetadata::V1(_), LaunchDigestDomain::Matrix) => {
                return Err(invalid_program());
            }
        };
        self.release_digests
            .launch_prefix(program, manifest, &expected, domain)
    }
}

#[cfg(unix)]
fn invalid_program() -> FleetRegistryError {
    FleetRegistryError::Invalid("launch program does not match its catalog role".into())
}
