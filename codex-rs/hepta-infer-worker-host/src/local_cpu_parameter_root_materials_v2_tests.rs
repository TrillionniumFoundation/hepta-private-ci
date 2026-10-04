use super::*;

#[test]
fn unprotected_descriptor_cannot_supply_materials_or_create_a_worker()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("materials.json");
    let original = br#"{"schema":"hepta.cpu-neuron.parameter-root-materials.v2"}"#;
    std::fs::write(&path, original)?;
    let source = InstalledCpuSourceV1 {
        path: path.clone(),
        digest: Digest32::of_bytes(original).to_string(),
    };
    assert!(
        CpuNeuronParameterRootMaterialsV2::from_protected_source(
            &source,
            Digest32::of_bytes(b"independently expected Worker ELF"),
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&path)?, original);
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 1);
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
#[ignore = "requires actual UID0 and protected whole descriptor Sources"]
fn actual_root_reads_the_complete_maximum_frontier_and_refuses_an_oversized_source()
-> Result<(), Box<dyn std::error::Error>> {
    use std::os::unix::fs::PermissionsExt;

    assert_eq!(unsafe { libc::geteuid() }, 0, "actual protected Source owner");
    let directory = tempfile::tempdir()?;
    let long_directory = format!("/original/{}", "retained-round/".repeat(64));
    let source = |ordinal: usize, purpose: &str| serde_json::json!({
        "path": format!("{long_directory}/{ordinal}/{purpose}.json"),
        "digest": Digest32::of_bytes(format!("{ordinal}:{purpose}").as_bytes()).to_string(),
    });
    let candidates: Vec<_> = (0..32).map(|ordinal| serde_json::json!({
        "candidate_id": format!("candidate-{ordinal}"),
        "generation": source(ordinal, "generation"),
        "canary_tick": source(ordinal, "canary-tick"),
        "canary_port": source(ordinal, "canary-port"),
    })).collect();
    let rollbacks: Vec<_> = (0..32).map(|ordinal| serde_json::json!({
        "candidate_id": format!("candidate-{ordinal}"),
        "generation": source(ordinal, "rollback"),
    })).collect();
    let bytes = serde_json::to_vec(&serde_json::json!({
        "schema": "hepta.cpu-neuron.parameter-root-materials.v2",
        "canonical_envelope": source(0, "canonical"),
        "parameter_request": source(0, "request"),
        "baseline": source(0, "baseline"),
        "baseline_candidate_id": "baseline",
        "test_plan_digest": Digest32::of_bytes(b"original test plan").to_string(),
        "candidates": candidates,
        "rollback": source(0, "rollback"),
        "rollbacks": rollbacks,
        "worker_program": source(0, "worker"),
    }))?;
    assert!(bytes.len() > 64 * 1024);
    let path = directory.path().join("materials.json");
    std::fs::write(&path, &bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let installed = InstalledCpuSourceV1 {
        path: path.clone(), digest: Digest32::of_bytes(&bytes).to_string(),
    };
    let complete = read(&installed, MAX_PARAMETER_ROUND_DESCRIPTOR_BYTES_V2)?;
    assert_eq!(complete, bytes);
    let descriptor: Descriptor = serde_json::from_slice(&complete)?;
    assert_eq!(descriptor.candidates.len(), 32);
    assert_eq!(descriptor.rollbacks.len(), 32);
    for (ordinal, (candidate, rollback)) in descriptor.candidates.iter().zip(&descriptor.rollbacks).enumerate() {
        assert_eq!(candidate.candidate_id, rollback.candidate_id);
        assert_eq!(candidate.generation.path, std::path::PathBuf::from(format!("{long_directory}/{ordinal}/generation.json")));
        assert_eq!(rollback.generation.path, std::path::PathBuf::from(format!("{long_directory}/{ordinal}/rollback.json")));
    }
    let oversized = vec![b' '; MAX_PARAMETER_ROUND_DESCRIPTOR_BYTES_V2 as usize + 1];
    let oversized_path = directory.path().join("oversized.json");
    std::fs::write(&oversized_path, &oversized)?;
    std::fs::set_permissions(&oversized_path, std::fs::Permissions::from_mode(0o600))?;
    let too_large = InstalledCpuSourceV1 {
        path: oversized_path.clone(), digest: Digest32::of_bytes(&oversized).to_string(),
    };
    assert!(read(&too_large, MAX_PARAMETER_ROUND_DESCRIPTOR_BYTES_V2).is_err());
    assert_eq!(std::fs::read(&path)?, bytes);
    assert_eq!(std::fs::read(&oversized_path)?, oversized);
    Ok(())
}
