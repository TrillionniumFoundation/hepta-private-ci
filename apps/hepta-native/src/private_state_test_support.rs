use tempfile::TempDir;

pub fn private_tempdir() -> TempDir {
    let root = tempfile::tempdir().unwrap();
    // Let the production owner create Unix mode 0700 or the Windows protected
    // DACL instead of depending on tempfile's inherited permissions.
    let child = root.path().join("private");
    crate::private_state::PrivateStateRoot::open(&child).unwrap();
    let holding = root.path().with_extension("private-child");
    std::fs::rename(&child, &holding).unwrap();
    std::fs::remove_dir(root.path()).unwrap();
    std::fs::rename(&holding, root.path()).unwrap();
    root
}
