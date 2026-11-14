from pathlib import Path
p=Path('/workspace/shared/supervisor-runfiles-backing-fix/robrix_control_projection.rs')
s=p.read_text(); a=s.index('fn read_tracked_artifacts()'); b=s.index('\nfn read_artifacts(',a)
new='''fn read_tracked_artifacts() -> Result<BTreeMap<String, Vec<u8>>> {
    if !codex_utils_cargo_bin::runfiles_available() {
        // Cargo keeps strict enumeration of the source fixture directory.
        return read_artifacts(&std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("fixtures/robrix-control-v2"));
    }
    let mut resources = Vec::new();
    for name in [MANIFEST_FILE, CORPUS_FILE, GENERATED_CONSTANTS_FILE,
        MATRIXD_SCHEMA_FILE, SUPERVISORD_SCHEMA_FILE] {
        // Resolve every declared resource before following delivery symlinks.
        let resource = format!("fixtures/robrix-control-v2/{name}");
        resources.push((name, codex_utils_cargo_bin::find_resource!(resource)?));
    }
    read_artifacts(&validated_fixture_backing_root(&resources)?)
}

// Bazel may deliver declared data through symlinks, including in manifest mode.
// Only the five successfully resolved resources may establish the backing root.
fn validated_fixture_backing_root(
    resources: &[(&str, std::path::PathBuf)],
) -> std::io::Result<std::path::PathBuf> {
    use std::io::{Error, ErrorKind};
    let invalid = |message| Error::new(ErrorKind::InvalidData, message);
    let expected: BTreeSet<_> = resources.iter().map(|(name, _)| *name).collect();
    if resources.len() != 5 || expected.len() != 5 {
        return Err(invalid("exactly five distinct fixture resources are required"));
    }
    let mut root = None;
    for (name, delivered) in resources {
        let backing = fs::canonicalize(delivered)?;
        if !fs::metadata(&backing)?.is_file()
            || backing.file_name() != Some(std::ffi::OsStr::new(name)) {
            return Err(invalid("fixture backing must be a regular file with its declared name"));
        }
        let parent = backing.parent().ok_or_else(|| invalid("fixture has no parent"))?;
        if let Some(expected_root) = &root {
            if expected_root != parent {
                return Err(invalid("fixture resources have different backing directories"));
            }
        } else {
            root = Some(parent.to_path_buf());
        }
    }
    let root = root.ok_or_else(|| invalid("fixture root is missing"))?;
    let mut actual = BTreeSet::new();
    for entry in fs::read_dir(&root)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            return Err(invalid("fixture backing directory contains a non-file"));
        }
        actual.insert(entry.file_name().into_string()
            .map_err(|_| invalid("fixture name is not UTF-8"))?);
    }
    if actual.iter().map(String::as_str).collect::<BTreeSet<_>>() != expected {
        return Err(invalid("fixture backing directory does not match the declared set"));
    }
    Ok(root)
}
'''
p.write_text(s[:a]+new+s[b:])
