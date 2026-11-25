use std::collections::BTreeSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

#[path = "../tests/support/fixture_projection.rs"]
mod fixture_projection;

pub(crate) struct FixtureInputs {
    pub(crate) files: Vec<(PathBuf, PathBuf)>,
    pub(crate) carriers: BTreeSet<PathBuf>,
    _projection: Option<tempfile::TempDir>,
}

impl FixtureInputs {
    pub(crate) fn for_syntax_tests(requested: &Path) -> io::Result<Self> {
        let selected = resolve_existing_prefix(requested)?;
        let mut inputs = Self {
            files: Vec::new(),
            carriers: BTreeSet::new(),
            _projection: None,
        };
        let original = match fixture_projection::source_root().canonicalize() {
            Ok(path) => path,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(inputs),
            Err(error) => return Err(error),
        };
        for entry in fixture_projection::entries()? {
            let relative = entry.original()?;
            if !relative
                .file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with("syntax_test_"))
            {
                continue;
            }
            let original_path = original.join(relative);
            let Ok(suffix) = original_path.strip_prefix(&selected) else {
                continue;
            };
            match original_path.symlink_metadata() {
                Ok(_) => {
                    return Err(io::Error::new(
                        io::ErrorKind::AlreadyExists,
                        "archived test has a duplicate physical source",
                    ))
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => (),
                Err(error) => return Err(error),
            }
            let logical_path = if suffix.as_os_str().is_empty() {
                requested.to_path_buf()
            } else {
                requested.join(suffix)
            };
            if inputs._projection.is_none() {
                inputs._projection = Some(
                    tempfile::Builder::new()
                        .prefix("syntect-fixtures-")
                        .tempdir()?,
                );
            }
            let output_root = inputs._projection.as_ref().unwrap().path();
            entry.restore(output_root)?;
            let mut carrier = logical_path.as_os_str().to_owned();
            carrier.push(".evidence.gz");
            inputs.carriers.insert(PathBuf::from(carrier));
            inputs
                .files
                .push((logical_path, output_root.join(relative)));
        }
        Ok(inputs)
    }
}

fn resolve_existing_prefix(path: &Path) -> io::Result<PathBuf> {
    match fs::canonicalize(path) {
        Ok(resolved) => Ok(resolved),
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            let absolute = std::path::absolute(path)?;
            match (absolute.parent(), absolute.file_name()) {
                (Some(parent), Some(name)) => Ok(resolve_existing_prefix(parent)?.join(name)),
                _ => Err(error),
            }
        }
        Err(error) => Err(error),
    }
}
