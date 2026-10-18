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
