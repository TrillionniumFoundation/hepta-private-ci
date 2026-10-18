//! A failed or crashed stage cannot admit an unbounded set of package files.
//! Unknown entries remain operator recovery evidence and are never deleted here.
use crate::error::ShellError;
use crate::private_state::PrivateStateRoot;
use crate::update_storage::digest_private_file;
use std::ffi::OsString;

const MAX_SCAN_ENTRIES: usize = 16 * 1024;

pub(super) fn admit_staged_package(
    root: &PrivateStateRoot,
    digest: &str,
) -> Result<(), ShellError> {
    crate::model::validate_digest(digest, "staged package admission")?;
    root.verify()?;
    let expected = format!("{digest}.package");
    let entries = staged_entries(root)?;
    root.verify()?;
    match entries.as_slice() {
        [] => Ok(()),
        [name] if name.as_os_str() == std::ffi::OsStr::new(&expected) => {
            if digest_private_file(root, &root.path().join(&expected))? != digest {
                return Err(ShellError::Security("existing staged package does not match its retry digest".into()));
            }
            root.verify()
        }
        _ => Err(ShellError::Update("staging admits only one exact package; preserve and explicitly recover unknown, abandoned or crash-remnant files before retrying".into())),
    }
}

fn staged_entries(root: &PrivateStateRoot) -> Result<Vec<OsString>, ShellError> {
    let mut names = Vec::new();
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStringExt as _;
        let directory =
            rustix::fs::Dir::read_from(root.directory_handle()).map_err(std::io::Error::from)?;
        for (index, entry) in directory.enumerate() {
            if index >= MAX_SCAN_ENTRIES {
                return Err(ShellError::Update(
                    "staging inspection exceeded its entry budget".into(),
                ));
            }
            let entry = entry.map_err(std::io::Error::from)?;
            let bytes = entry.file_name().to_bytes();
            if bytes == b"." || bytes == b".." {
                continue;
            }
            names.push(OsString::from_vec(bytes.to_vec()));
            if names.len() > 1 {
                break;
            }
        }
    }
    #[cfg(not(unix))]
    {
        for (index, entry) in std::fs::read_dir(root.path())?.enumerate() {
            if index >= MAX_SCAN_ENTRIES {
                return Err(ShellError::Update(
                    "staging inspection exceeded its entry budget".into(),
                ));
            }
            names.push(entry?.file_name());
            if names.len() > 1 {
                break;
            }
        }
    }
    root.verify()?;
    Ok(names)
}
