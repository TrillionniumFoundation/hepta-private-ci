//! Synthetic build declarations for the actual PQ qualification publisher.
//! Artifact bytes are real; the labelled fixture source/build identities are
//! not evidence of an independently reproduced production build.

use std::path::Path;
use std::path::PathBuf;

use sha2::Digest;
use sha2::Sha256;
use trnm_release_bundle::BuilderProvenanceV0;
use trnm_release_bundle::ReleaseBundleV0;

use crate::RELEASE_METADATA_SCHEMA_VERSION;
use crate::ReleaseId;
use crate::ReleaseMetadata;
use crate::ReleaseProgramMetadata;
use crate::release_authority_bundle::*;
use crate::release_authority_set::BuildRecord;
use crate::release_authority_set::MemberRecord;
use crate::release_authority_set::ReleaseSetRecord;
use crate::release_authority_set::SET_PROFILE;
use crate::release_authority_set::manifest_bytes;
use crate::release_authority_set::record_bytes;
use crate::release_qualification::QualificationResult;

pub(crate) const PLATFORM: [u8; 32] = [101; 32];

pub(crate) fn member(
    id: ReleaseId,
    agentd: &Path,
    args: Vec<String>,
    matrixd: Option<&Path>,
    matrix_args: Vec<String>,
) -> QualificationResult<MemberRecord> {
    let release = ReleaseMetadata {
        schema_version: RELEASE_METADATA_SCHEMA_VERSION,
        release_id: id,
        agentd: program(agentd, "bin/hepta-agentd", args)?,
        matrixd: matrixd
            .map(|path| program(path, "bin/hepta-matrixd", matrix_args))
            .transpose()?,
    };
    let mut artifacts = vec![artifact(
        b"release.json",
        &manifest_bytes(&release)?,
        /*executable*/ false,
    )];
    let mut packages = Vec::new();
    for (name, path, executable) in [
        ("codex-hepta-agentd", Some(agentd), Some(&release.agentd)),
        ("codex-hepta-matrixd", matrixd, release.matrixd.as_ref()),
    ] {
        if let (Some(path), Some(program)) = (path, executable) {
            let bytes = std::fs::read(path)?;
            artifacts.push(artifact(
                program
                    .program_relative_path
                    .to_str()
                    .ok_or("invalid fixture program path")?
                    .as_bytes(),
                &bytes,
                /*executable*/ true,
            ));
            packages.push(PackageRecord {
                package_name: name.as_bytes().to_vec(),
                package_version: b"0.0.0".to_vec(),
                source_digest: Sha256::digest(b"qualification-only-package-source").into(),
                package_checksum: Sha256::digest(&bytes).into(),
                license_expression: b"Apache-2.0".to_vec(),
                direct_production_dependency: true,
            });
        }
    }
    let source = source(release.release_id.as_str().as_bytes());
    let declared = bundle(
        b"qualification-member",
        b"0.0.0",
        source,
        artifacts,
        packages,
        [1; 32],
        /*previous*/ None,
    );
    Ok(MemberRecord {
        release,
        build_record: BuildRecord {
            exact_source: declared.exact_source,
            artifacts: declared.artifacts,
            sbom_packages: declared.sbom_packages,
            provenance: declared.provenance,
        },
    })
}

fn program(
    path: &Path,
    name: &str,
    args: Vec<String>,
) -> QualificationResult<ReleaseProgramMetadata> {
    let bytes = std::fs::read(path)?;
    Ok(ReleaseProgramMetadata {
        program_relative_path: PathBuf::from(name),
        program_sha256: format!("{:x}", Sha256::digest(&bytes)),
        program_size_bytes: bytes.len() as u64,
        args,
    })
}

pub(crate) fn release_set(
    members: Vec<MemberRecord>,
    version: u64,
    signer: [u8; 32],
    previous: Option<[u8; 32]>,
) -> QualificationResult<ReleaseSetRecord> {
    let mut artifacts = Vec::new();
    let mut packages = Vec::new();
    for member in &members {
        let prefix = format!("releases/{}/", member.release.release_id);
        for item in &member.build_record.artifacts {
            let mut qualified = item.clone();
            qualified.logical_name = [prefix.as_bytes(), &item.logical_name].concat();
            artifacts.push(qualified);
        }
        artifacts.push(artifact(
            format!("{prefix}build-record.json").as_bytes(),
            &record_bytes(&member.build_record)?,
            /*executable*/ false,
        ));
        for item in &member.build_record.sbom_packages {
            let mut qualified = item.clone();
            qualified.package_name = [prefix.as_bytes(), &item.package_name].concat();
            packages.push(qualified);
        }
    }
    let bundle = bundle(
        SET_PROFILE.as_bytes(),
        version.to_string().as_bytes(),
        source(b"qualification-set-assembly"),
        artifacts,
        packages,
        signer,
        previous,
    );
    Ok(ReleaseSetRecord {
        schema_version: 1,
        profile: SET_PROFILE.into(),
        bundle,
        members,
    })
}

fn source(label: &[u8]) -> SourceRecord {
    SourceRecord {
        repository_digest: Sha256::digest(b"qualification-only-repository").into(),
        commit_digest: Sha256::digest(label).into(),
        tree_digest: [3; 32],
        cargo_lock_digest: [4; 32],
        toolchain_digest: [5; 32],
        production_closure_digest: [6; 32],
        dirty: false,
    }
}

fn artifact(name: &[u8], bytes: &[u8], executable: bool) -> ArtifactRecord {
    ArtifactRecord {
        logical_name: name.to_vec(),
        media_type: b"application/octet-stream".to_vec(),
        size_bytes: bytes.len() as u64,
        content_digest: Sha256::digest(bytes).into(),
        executable,
        platform_digest: PLATFORM,
        source_path_digest: Sha256::digest(name).into(),
    }
}

fn bundle(
    name: &[u8],
    version: &[u8],
    exact_source: SourceRecord,
    artifacts: Vec<ArtifactRecord>,
    sbom_packages: Vec<PackageRecord>,
    signer: [u8; 32],
    previous: Option<[u8; 32]>,
) -> BundleRecord {
    let mut bundle = BundleRecord {
        bundle_name: name.to_vec(),
        release_version: version.to_vec(),
        protocol_digest: Sha256::digest(SET_PROFILE).into(),
        exact_source,
        artifacts,
        sbom_packages,
        provenance: ProvenanceRecord {
            builder_identity_digest: [21; 32],
            workflow_digest: [22; 32],
            run_identity_digest: [23; 32],
            isolated_environment_digest: [24; 32],
            exact_source_digest: [0; 32],
            build_inputs: vec![BuildInputRecord {
                logical_name: b"fixture-input".to_vec(),
                source_digest: [25; 32],
                content_digest: [26; 32],
            }],
            artifact_set_digest: [0; 32],
            sbom_digest: [0; 32],
            provenance_digest: [0; 32],
        },
        previous_bundle_digest: previous,
        signer_identity_digest: signer,
        signature_digest: [0; 32],
        bundle_digest: [0; 32],
    };
    let native = ReleaseBundleV0::from(&bundle);
    bundle.provenance.exact_source_digest = native.exact_source.canonical_digest().0;
    bundle.provenance.artifact_set_digest = native.artifact_set_digest().0;
    bundle.provenance.sbom_digest = native.sbom_digest().0;
    bundle.provenance.provenance_digest = BuilderProvenanceV0::from(&bundle.provenance)
        .canonical_digest()
        .0;
    bundle.bundle_digest = ReleaseBundleV0::from(&bundle).canonical_digest().0;
    bundle
}
