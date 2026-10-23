use super::*;
use std::os::unix::fs::PermissionsExt;

#[test]
fn host_material_requires_original_digest_and_protected_unaliased_file()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let path = root.join("host.json");
    let bytes = b"independently pinned host material";
    let digest = Digest32::of_bytes(bytes);
    std::fs::write(&path, bytes)?;
    assert_eq!(read_pinned_file(&path, digest, MAX_HOST_FILE_BYTES)?, bytes);
    std::fs::write(&path, b"changed host configuration")?;
    assert!(read_pinned_file(&path, digest, MAX_HOST_FILE_BYTES).is_err());
    std::fs::write(&path, bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))?;
    assert!(read_pinned_file(&path, digest, MAX_HOST_FILE_BYTES).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    std::os::unix::fs::symlink(&path, root.join("alias"))?;
    assert!(read_pinned_file(&root.join("alias"), digest, MAX_HOST_FILE_BYTES).is_err());
    std::fs::hard_link(&path, root.join("hard-link"))?;
    assert!(read_pinned_file(&path, digest, MAX_HOST_FILE_BYTES).is_err());
    Ok(())
}
