//! Test-only private roots for platform-independent authority behavior tests.

use std::io;

pub(crate) fn private_tempdir() -> io::Result<tempfile::TempDir> {
    let directory = tempfile::tempdir()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    }
    #[cfg(windows)]
    {
        // Only this new, empty fixture directory is removed. Recreate it through
        // the production primitive so it starts with the private inheritable DACL.
        std::fs::remove_dir(directory.path())?;
        drop(codex_utils_path::open_private_state_directory(
            directory.path(),
        )?);
    }
    Ok(directory)
}
