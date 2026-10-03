use tempfile::TempDir;

pub fn private_tempdir() -> TempDir {
    let root = TempDir::new().unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    #[cfg(windows)]
    {
        // tempfile creates an ordinary inherited DACL. Ask the real private
        // directory owner to create a fresh child, rather than weakening trust
        // validation for every existing directory in the product.
        let child = root.path().join("private");
        hepta_native::private_state::PrivateStateRoot::open(child.clone()).unwrap();
        // Moving the private child to the reserved path preserves its DACL and
        // keeps TempDir's existing cleanup/fixture API on all test call sites.
        let holding = root.path().with_extension("private-child");
        std::fs::rename(&child, &holding).unwrap();
        std::fs::remove_dir(root.path()).unwrap();
        std::fs::rename(&holding, root.path()).unwrap();
    }
    root
}
