use super::NduProjectionStoreError;
use super::NduProjectionStoreV1;

#[test]
fn unsupported_durability_profile_is_rejected_before_touching_paths()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().join("unsupported-ndu-profile");
    assert!(!root.exists());
    assert!(matches!(
        NduProjectionStoreV1::open(&root),
        Err(NduProjectionStoreError::UnsupportedPlatform)
    ));
    assert!(!root.exists());
    Ok(())
}
