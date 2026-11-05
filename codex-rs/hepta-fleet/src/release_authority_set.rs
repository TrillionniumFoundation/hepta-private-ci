//! Fleet-specific membership binding for an actual M15-authorized release set.
//! Build records are publisher-covered declarations, not independently verified
//! old signatures or reproducibility attestations.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use trnm_release_bundle::ArtifactEntryV0;
use trnm_release_bundle::BuilderProvenanceV0;
use trnm_release_bundle::Digest32V0;
use trnm_release_bundle::ExactSourceV0;
use trnm_release_bundle::MAX_ARTIFACTS_V0;
use trnm_release_bundle::MAX_PACKAGES_V0;
use trnm_release_bundle::ReleaseBundleV0;
use trnm_release_bundle::SbomPackageV0;

use crate::FleetRegistryError;
use crate::ReleaseMetadata;
use crate::ReleaseProgramMetadata;
use crate::release_authority::invalid;
use crate::release_authority_bundle::ArtifactRecord;
use crate::release_authority_bundle::BundleRecord;
use crate::release_authority_bundle::PackageRecord;
use crate::release_authority_bundle::ProvenanceRecord;
use crate::release_authority_bundle::SourceRecord;
use crate::release_authority_wire::MetadataRecord;
use crate::release_authority_wire::SignatureRecord;

pub(crate) const SET_PROFILE: &str = "hepta.fleet.release-set.v1";
const MAX_MEMBERS: usize = 256;
const MAX_MANIFEST_BYTES: usize = 32 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct BuildRecord {
    pub exact_source: SourceRecord,
    pub artifacts: Vec<ArtifactRecord>,
    pub sbom_packages: Vec<PackageRecord>,
    pub provenance: ProvenanceRecord,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MemberRecord {
    pub release: ReleaseMetadata,
    pub build_record: BuildRecord,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ReleaseSetRecord {
    pub schema_version: u32,
    pub profile: String,
    pub bundle: BundleRecord,
    pub members: Vec<MemberRecord>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SignedReleaseSet {
    pub release_set: ReleaseSetRecord,
    pub metadata: MetadataRecord,
    pub signatures: Vec<SignatureRecord>,
}

pub(crate) struct SetBinding {
    pub bundle: ReleaseBundleV0,
    pub required_packages: Vec<(Vec<u8>, Vec<u8>)>,
}

impl ReleaseSetRecord {
    pub fn bind(&self, platform: [u8; 32]) -> Result<SetBinding, FleetRegistryError> {
        if self.schema_version != 1
            || self.profile != SET_PROFILE
            || self.members.is_empty()
            || self.members.len() > MAX_MEMBERS
            || self.bundle.bundle_name != SET_PROFILE.as_bytes()
            || self.bundle.protocol_digest != <[u8; 32]>::from(Sha256::digest(SET_PROFILE))
            || self.bundle.artifacts.len() > MAX_ARTIFACTS_V0
            || self.bundle.sbom_packages.len() > MAX_PACKAGES_V0
            || platform == [0; 32]
        {
            return Err(invalid("unsupported or oversized Fleet release set"));
        }
        let bundle = ReleaseBundleV0::from(&self.bundle);
        let mut expected_artifacts = BTreeMap::new();
        let mut expected_packages = Vec::new();
        let mut required_packages = Vec::new();
        let mut members = BTreeSet::new();
        for member in &self.members {
            crate::release::validate_metadata(&member.release, &member.release.release_id)?;
            if !members.insert(member.release.release_id.clone()) {
                return Err(invalid("duplicate release-set member"));
            }
            let manifest = manifest_bytes(&member.release)?;
            let mut expected_member = BTreeMap::from([(
                b"release.json".to_vec(),
                (
                    <[u8; 32]>::from(Sha256::digest(&manifest)),
                    manifest.len() as u64,
                    false,
                ),
            )]);
            insert_program(&mut expected_member, &member.release.agentd)?;
            if let Some(matrixd) = &member.release.matrixd {
                insert_program(&mut expected_member, matrixd)?;
            }
            let artifacts = member
                .build_record
                .artifacts
                .iter()
                .map(ArtifactEntryV0::from)
                .collect::<Vec<_>>();
            check_artifacts(&artifacts, &expected_member, platform)?;
            let packages = member
                .build_record
                .sbom_packages
                .iter()
                .map(SbomPackageV0::from)
                .collect::<Vec<_>>();
            check_build_record(&member.build_record, &artifacts, &packages)?;
            let prefix = format!("releases/{}/", member.release.release_id);
            for artifact in artifacts {
                let name = [prefix.as_bytes(), &artifact.logical_name].concat();
                expected_artifacts.insert(
                    name,
                    (
                        artifact.content_digest.0,
                        artifact.size_bytes,
                        artifact.executable,
                    ),
                );
            }
            let record = record_bytes(&member.build_record)?;
            expected_artifacts.insert(
                format!("{prefix}build-record.json").into_bytes(),
                (
                    <[u8; 32]>::from(Sha256::digest(&record)),
                    record.len() as u64,
                    false,
                ),
            );
            let mut required = BTreeSet::from([b"codex-hepta-agentd".to_vec()]);
            if member.release.matrixd.is_some() {
                required.insert(b"codex-hepta-matrixd".to_vec());
            }
            let mut seen_required = BTreeSet::new();
            for package in packages {
                let original_name = package.package_name.clone();
                let mut qualified = package;
                qualified.package_name = [prefix.as_bytes(), &original_name].concat();
                qualified
                    .validate()
                    .map_err(|_| invalid("member SBOM namespace exceeds M15 bounds"))?;
                if required.contains(&original_name) {
                    if !seen_required.insert(original_name) {
                        return Err(invalid(
                            "member executable package has ambiguous versions or sources",
                        ));
                    }
                    required_packages.push((
                        qualified.package_name.clone(),
                        qualified.package_version.clone(),
                    ));
                }
                expected_packages.push(qualified);
            }
            if seen_required != required {
                return Err(invalid(
                    "member SBOM omits its actual Hepta executable package",
                ));
            }
            if expected_packages.len() > MAX_PACKAGES_V0 {
                return Err(invalid("release-set SBOM exceeds the M15 package bound"));
            }
        }
        check_artifacts(&bundle.artifacts, &expected_artifacts, platform)?;
        expected_packages.sort_unstable();
        let mut actual_packages = bundle.sbom_packages.clone();
        actual_packages.sort_unstable();
        if actual_packages != expected_packages || required_packages.is_empty() {
            return Err(invalid(
                "release-set SBOM is not the exact namespaced member SBOM",
            ));
        }
        Ok(SetBinding {
            bundle,
            required_packages,
        })
    }
}

pub(crate) fn manifest_bytes(metadata: &ReleaseMetadata) -> Result<Vec<u8>, FleetRegistryError> {
    let bytes = record_bytes(metadata)?;
    if bytes.len() > MAX_MANIFEST_BYTES {
        return Err(invalid("release manifest exceeds the original Fleet limit"));
    }
    Ok(bytes)
}

pub(crate) fn record_bytes(value: &impl Serialize) -> Result<Vec<u8>, FleetRegistryError> {
    let mut bytes =
        serde_json::to_vec(value).map_err(|_| invalid("cannot encode release record"))?;
    bytes.push(b'\n');
    Ok(bytes)
}

type ArtifactBindings = BTreeMap<Vec<u8>, ([u8; 32], u64, bool)>;

fn insert_program(
    expected: &mut ArtifactBindings,
    program: &ReleaseProgramMetadata,
) -> Result<(), FleetRegistryError> {
    let name = program
        .program_relative_path
        .to_str()
        .ok_or_else(|| invalid("non-UTF-8 release program"))?;
    let digest = parse_digest(&program.program_sha256)?;
    if expected
        .insert(
            name.as_bytes().to_vec(),
            (digest, program.program_size_bytes, true),
        )
        .is_some()
    {
        return Err(invalid("duplicate release program"));
    }
    Ok(())
}

fn check_artifacts(
    actual: &[ArtifactEntryV0],
    expected: &ArtifactBindings,
    platform: [u8; 32],
) -> Result<(), FleetRegistryError> {
    if actual.len() != expected.len() || actual.len() > MAX_ARTIFACTS_V0 {
        return Err(invalid("release artifact set is not closed"));
    }
    let mut seen = BTreeSet::new();
    for artifact in actual {
        artifact
            .validate()
            .map_err(|_| invalid("invalid M15 artifact declaration"))?;
        if !seen.insert(&artifact.logical_name)
            || artifact.platform_digest.0 != platform
            || expected.get(&artifact.logical_name)
                != Some(&(
                    artifact.content_digest.0,
                    artifact.size_bytes,
                    artifact.executable,
                ))
        {
            return Err(invalid(
                "release artifact is duplicate, substituted, or for another platform",
            ));
        }
    }
    Ok(())
}

fn check_build_record(
    record: &BuildRecord,
    artifacts: &[ArtifactEntryV0],
    packages: &[SbomPackageV0],
) -> Result<(), FleetRegistryError> {
    let source = ExactSourceV0::from(&record.exact_source)
        .validate()
        .map_err(|_| invalid("invalid member exact-source record"))?;
    let provenance = BuilderProvenanceV0::from(&record.provenance);
    provenance
        .validate()
        .map_err(|_| invalid("invalid member builder provenance"))?;
    if packages.is_empty() || packages.len() > MAX_PACKAGES_V0 {
        return Err(invalid("missing or oversized member SBOM"));
    }
    let mut seen = BTreeSet::new();
    for package in packages {
        package
            .validate()
            .map_err(|_| invalid("invalid member SBOM package"))?;
        if !seen.insert((&package.package_name, &package.package_version)) {
            return Err(invalid("duplicate member SBOM package"));
        }
    }
    // These are the V0 declaration-set digests, not authorization messages.
    // The regression compares both against M15's actual bundle methods.
    let mut sorted_artifacts = artifacts.to_vec();
    sorted_artifacts.sort_unstable();
    let mut artifact_hash = Sha256::new();
    artifact_hash.update(b"trnm.release.artifact-set.v0");
    for artifact in sorted_artifacts {
        artifact_hash.update(artifact.canonical_digest().0);
    }
    let mut sorted_packages = packages.to_vec();
    sorted_packages.sort_unstable();
    let mut package_hash = Sha256::new();
    package_hash.update(b"trnm.release.sbom.v0");
    for package in sorted_packages {
        package_hash.update(package.canonical_digest().0);
    }
    if provenance.exact_source_digest != source.canonical_digest()
        || provenance.artifact_set_digest != Digest32V0(artifact_hash.finalize().into())
        || provenance.sbom_digest != Digest32V0(package_hash.finalize().into())
    {
        return Err(invalid(
            "member provenance is not bound to its actual declarations",
        ));
    }
    Ok(())
}

pub(crate) fn parse_digest(value: &str) -> Result<[u8; 32], FleetRegistryError> {
    if value.len() != 64 || !value.as_bytes().iter().all(u8::is_ascii_hexdigit) {
        return Err(invalid("invalid release SHA-256"));
    }
    let mut digest = [0; 32];
    for (index, byte) in digest.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| invalid("invalid release SHA-256"))?;
    }
    Ok(digest)
}
