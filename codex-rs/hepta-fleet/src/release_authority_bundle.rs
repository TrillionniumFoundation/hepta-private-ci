//! Storage DTOs for the existing M15 declarations. These conversions neither
//! sign nor verify anything and do not introduce a second signing format.

use serde::Deserialize;
use serde::Serialize;
use trnm_release_bundle::ArtifactEntryV0;
use trnm_release_bundle::BuildInputV0;
use trnm_release_bundle::BuilderProvenanceV0;
use trnm_release_bundle::Digest32V0;
use trnm_release_bundle::ExactSourceV0;
use trnm_release_bundle::ReleaseBundleV0;
use trnm_release_bundle::SbomPackageV0;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SourceRecord {
    pub repository_digest: [u8; 32],
    pub commit_digest: [u8; 32],
    pub tree_digest: [u8; 32],
    pub cargo_lock_digest: [u8; 32],
    pub toolchain_digest: [u8; 32],
    pub production_closure_digest: [u8; 32],
    pub dirty: bool,
}

impl From<&SourceRecord> for ExactSourceV0 {
    fn from(value: &SourceRecord) -> Self {
        Self {
            repository_digest: Digest32V0(value.repository_digest),
            commit_digest: Digest32V0(value.commit_digest),
            tree_digest: Digest32V0(value.tree_digest),
            cargo_lock_digest: Digest32V0(value.cargo_lock_digest),
            toolchain_digest: Digest32V0(value.toolchain_digest),
            production_closure_digest: Digest32V0(value.production_closure_digest),
            dirty: value.dirty,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ArtifactRecord {
    pub logical_name: Vec<u8>,
    pub media_type: Vec<u8>,
    pub size_bytes: u64,
    pub content_digest: [u8; 32],
    pub executable: bool,
    pub platform_digest: [u8; 32],
    pub source_path_digest: [u8; 32],
}

impl From<&ArtifactRecord> for ArtifactEntryV0 {
    fn from(value: &ArtifactRecord) -> Self {
        Self {
            logical_name: value.logical_name.clone(),
            media_type: value.media_type.clone(),
            size_bytes: value.size_bytes,
            content_digest: Digest32V0(value.content_digest),
            executable: value.executable,
            platform_digest: Digest32V0(value.platform_digest),
            source_path_digest: Digest32V0(value.source_path_digest),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PackageRecord {
    pub package_name: Vec<u8>,
    pub package_version: Vec<u8>,
    pub source_digest: [u8; 32],
    pub package_checksum: [u8; 32],
    pub license_expression: Vec<u8>,
    pub direct_production_dependency: bool,
}

impl From<&PackageRecord> for SbomPackageV0 {
    fn from(value: &PackageRecord) -> Self {
        Self {
            package_name: value.package_name.clone(),
            package_version: value.package_version.clone(),
            source_digest: Digest32V0(value.source_digest),
            package_checksum: Digest32V0(value.package_checksum),
            license_expression: value.license_expression.clone(),
            direct_production_dependency: value.direct_production_dependency,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct BuildInputRecord {
    pub logical_name: Vec<u8>,
    pub source_digest: [u8; 32],
    pub content_digest: [u8; 32],
}

impl From<&BuildInputRecord> for BuildInputV0 {
    fn from(value: &BuildInputRecord) -> Self {
        Self {
            logical_name: value.logical_name.clone(),
            source_digest: Digest32V0(value.source_digest),
            content_digest: Digest32V0(value.content_digest),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProvenanceRecord {
    pub builder_identity_digest: [u8; 32],
    pub workflow_digest: [u8; 32],
    pub run_identity_digest: [u8; 32],
    pub isolated_environment_digest: [u8; 32],
    pub exact_source_digest: [u8; 32],
    pub build_inputs: Vec<BuildInputRecord>,
    pub artifact_set_digest: [u8; 32],
    pub sbom_digest: [u8; 32],
    pub provenance_digest: [u8; 32],
}

impl From<&ProvenanceRecord> for BuilderProvenanceV0 {
    fn from(value: &ProvenanceRecord) -> Self {
        Self {
            builder_identity_digest: Digest32V0(value.builder_identity_digest),
            workflow_digest: Digest32V0(value.workflow_digest),
            run_identity_digest: Digest32V0(value.run_identity_digest),
            isolated_environment_digest: Digest32V0(value.isolated_environment_digest),
            exact_source_digest: Digest32V0(value.exact_source_digest),
            build_inputs: value.build_inputs.iter().map(BuildInputV0::from).collect(),
            artifact_set_digest: Digest32V0(value.artifact_set_digest),
            sbom_digest: Digest32V0(value.sbom_digest),
            provenance_digest: Digest32V0(value.provenance_digest),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct BundleRecord {
    pub bundle_name: Vec<u8>,
    pub release_version: Vec<u8>,
    pub protocol_digest: [u8; 32],
    pub exact_source: SourceRecord,
    pub artifacts: Vec<ArtifactRecord>,
    pub sbom_packages: Vec<PackageRecord>,
    pub provenance: ProvenanceRecord,
    pub previous_bundle_digest: Option<[u8; 32]>,
    pub signer_identity_digest: [u8; 32],
    pub signature_digest: [u8; 32],
    pub bundle_digest: [u8; 32],
}

impl From<&BundleRecord> for ReleaseBundleV0 {
    fn from(value: &BundleRecord) -> Self {
        Self {
            bundle_name: value.bundle_name.clone(),
            release_version: value.release_version.clone(),
            protocol_digest: Digest32V0(value.protocol_digest),
            exact_source: ExactSourceV0::from(&value.exact_source),
            artifacts: value.artifacts.iter().map(ArtifactEntryV0::from).collect(),
            sbom_packages: value
                .sbom_packages
                .iter()
                .map(SbomPackageV0::from)
                .collect(),
            provenance: BuilderProvenanceV0::from(&value.provenance),
            previous_bundle_digest: value.previous_bundle_digest.map(Digest32V0),
            signer_identity_digest: Digest32V0(value.signer_identity_digest),
            signature_digest: Digest32V0(value.signature_digest),
            bundle_digest: Digest32V0(value.bundle_digest),
        }
    }
}
