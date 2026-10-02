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
        #[cfg(unix)]
        {
            let mut programs = Vec::new();
            resolve_catalog_release_with_programs(
                self,
                release_id,
                |program, metadata, manifest| {
                    programs.push(self.release_digests.read_catalog_program(
                        program,
                        manifest,
                        &metadata.program_sha256,
                    )?);
                    Ok(())
                },
            )?;
            Ok(ReleaseReadPin::from_catalog_programs(programs))
        }
        #[cfg(not(unix))]
        {
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
    }

    /// Recheck a same-request descriptor using its actual complete-read FDs.
    /// This still reads the current allowance/revocation and closed catalog.
    /// It carries no launch authority: physical use must independently resolve
    /// the release again, including all program bytes.
    #[cfg(unix)]
    pub fn resolve_release_descriptor_from_read_pin(
        &self,
        agent_id: &AgentId,
        release_id: &ReleaseId,
        pin: &ReleaseReadPin,
    ) -> Result<RegisteredRelease, FleetRegistryError> {
        self.resolve_release_with_catalog(agent_id, release_id, |registry, release_id| {
            resolve_catalog_release_with_programs(
                registry,
                release_id,
                |program, metadata, manifest| {
                    pin.verify_catalog_program(program, manifest, &metadata.program_sha256)
                },
            )
            .map(|(release, _)| release)
        })
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
        let mut verified = None;
        let (release, _) = resolve_catalog_release_with_programs(
            self,
            &release_id,
            |candidate, metadata, manifest| {
                let role_matches = match domain {
                    LaunchDigestDomain::Agent => {
                        metadata.program_relative_path == Path::new(AGENTD_RELEASE_PROGRAM)
                    }
                    LaunchDigestDomain::Matrix => {
                        metadata.program_relative_path == Path::new(MATRIXD_RELEASE_PROGRAM)
                    }
                };
                if candidate == program && role_matches {
                    // The catalog check and launch prefix own the same actual FD
                    // within this call. This is not a mutable cross-request cache.
                    verified = Some(self.release_digests.launch_prefix(
                        candidate,
                        manifest.clone(),
                        &metadata.program_sha256,
                        domain,
                    )?);
                } else if self.release_digests.sha256(candidate, manifest)?
                    != metadata.program_sha256
                {
                    return Err(FleetRegistryError::Corrupt(format!(
                        "release {release_id} program differs from immutable metadata"
                    )));
                }
                Ok(())
            },
        )?;
        let resolved_program = match domain {
            LaunchDigestDomain::Agent => Some(release.program.as_path()),
            LaunchDigestDomain::Matrix => release
                .matrixd
                .as_ref()
                .map(|matrix| matrix.program.as_path()),
        };
        if resolved_program != Some(program) {
            return Err(invalid_program());
        }
        verified.ok_or_else(invalid_program)
    }
}

#[cfg(unix)]
fn invalid_program() -> FleetRegistryError {
    FleetRegistryError::Invalid("launch program does not match its catalog role".into())
}

#[cfg(all(test, unix))]
#[path = "release_launch_read_tests.rs"]
mod tests;
