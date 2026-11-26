use super::*;

fn directory() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().expect("private installed directory")
}
fn write_private(path: &Path, bytes: &[u8]) {
    std::fs::write(path, bytes).expect("fixture write");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .expect("private file");
    }
}
fn manifest() -> AgentdSelfIterationArtifactManifestV1 {
    AgentdSelfIterationArtifactManifestV1 {
        version: 1,
        objective_digest: Digest32::of_bytes(b"test objective"),
        candidate_generation: 8,
        artifacts: AgentdSelfIterationArtifactKindV1::REQUIRED
            .into_iter()
            .enumerate()
            .map(|(index, kind)| AgentdSelfIterationArtifactFileV1 {
                kind,
                filename: format!("input-{index}"),
                byte_length: 4,
                digest: Digest32::of_bytes(b"test"),
            })
            .collect(),
    }
}
fn install_manifest(
    directory: &Path,
    manifest: &AgentdSelfIterationArtifactManifestV1,
) -> Digest32 {
    let bytes = serde_json::to_vec(manifest).expect("manifest encode");
    write_private(&directory.join("inputs.json"), &bytes);
    Digest32::of_bytes(&bytes)
}
fn inspect(
    directory: &Path,
    digest: Digest32,
) -> Result<AgentdSelfIterationArtifactReadinessV1, AgentdError> {
    inspect_self_iteration_artifacts_v1(
        directory,
        "inputs.json",
        digest,
        Digest32::of_bytes(b"test objective"),
        8,
        Duration::from_secs(1),
    )
}

#[test]
fn missing_input_manifest_is_explicit_pending_without_authority() {
    let directory = directory();
    let state = inspect(
        directory.path(),
        Digest32::of_bytes(b"uninstalled manifest"),
    )
    .expect("pending");
    assert!(!state.authority().grants_any());
    assert_eq!(
        state,
        AgentdSelfIterationArtifactReadinessV1::PendingInputs {
            descriptor_digest: None,
            manifest_missing: true,
            missing: AgentdSelfIterationArtifactKindV1::REQUIRED.to_vec(),
        }
    );
}

#[test]
fn absent_inputs_remain_pending_and_verified_files_do_not_claim_qualification() {
    let directory = directory();
    let manifest = manifest();
    let digest = install_manifest(directory.path(), &manifest);
    let pending = inspect(directory.path(), digest).expect("pending actual absent files");
    assert!(matches!(
        pending,
        AgentdSelfIterationArtifactReadinessV1::PendingInputs {
            manifest_missing: false,
            ..
        }
    ));
    for input in &manifest.artifacts {
        write_private(&directory.path().join(&input.filename), b"test");
    }
    let state = inspect(directory.path(), digest).expect("identical files");
    assert!(!state.authority().grants_any());
    assert_eq!(
        state,
        AgentdSelfIterationArtifactReadinessV1::InputsVerifiedAwaitingOwnerQualification {
            descriptor_digest: digest,
            manifest,
        }
    );
}

#[test]
fn manifest_and_artifact_mutation_cannot_refresh_installed_identity() {
    let directory = directory();
    let manifest = manifest();
    let digest = install_manifest(directory.path(), &manifest);
    for input in &manifest.artifacts {
        write_private(&directory.path().join(&input.filename), b"test");
    }
    write_private(&directory.path().join("input-0"), b"evil");
    assert!(inspect(directory.path(), digest).is_err());
    write_private(&directory.path().join("input-0"), b"test");
    let mut foreign = manifest;
    foreign.candidate_generation = 9;
    let changed = install_manifest(directory.path(), &foreign);
    assert!(inspect(directory.path(), digest).is_err());
    assert!(inspect(directory.path(), changed).is_err());
}

#[test]
fn artifact_traversal_and_duplicate_roles_are_rejected() {
    let directory = directory();
    let mut manifest = manifest();
    manifest.artifacts[0].filename = "../foreign".into();
    let digest = install_manifest(directory.path(), &manifest);
    assert!(inspect(directory.path(), digest).is_err());
    manifest.artifacts[0].filename = "input-0".into();
    manifest.artifacts[1].kind = manifest.artifacts[0].kind;
    let digest = install_manifest(directory.path(), &manifest);
    assert!(inspect(directory.path(), digest).is_err());
}

#[cfg(unix)]
#[test]
fn symlink_and_public_file_cannot_be_installed_artifacts() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;
    let directory = directory();
    let manifest = manifest();
    let digest = install_manifest(directory.path(), &manifest);
    write_private(&directory.path().join("source"), b"test");
    symlink("source", directory.path().join("input-0")).expect("fixture link");
    assert!(inspect(directory.path(), digest).is_err());
    std::fs::remove_file(directory.path().join("input-0")).expect("remove link");
    write_private(&directory.path().join("input-0"), b"test");
    std::fs::set_permissions(
        directory.path().join("input-0"),
        std::fs::Permissions::from_mode(0o644),
    )
    .expect("public");
    assert!(inspect(directory.path(), digest).is_err());
}
