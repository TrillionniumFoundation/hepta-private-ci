use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::VerifiedManifest;
use super::parse_manifest;
use crate::durable::sha256;
use crate::test_support::private_tempdir;

#[test]
fn manifest_parser_requires_sorted_safe_unique_paths() {
    let first = "0".repeat(64);
    let second = "1".repeat(64);
    let valid = format!("{first}  a/file\n{second}  b\n");
    let parsed = parse_manifest(valid.as_bytes()).expect("valid manifest");
    assert_eq!(parsed.keys().cloned().collect::<Vec<_>>(), ["a/file", "b"]);

    for invalid in [
        format!("{first}  ../escape\n"),
        format!("{first}  /absolute\n"),
        format!("{first}  b\n{second}  a\n"),
        format!("{first}  duplicate\n{second}  duplicate\n"),
        format!("{first}  no-final-newline"),
    ] {
        assert!(parse_manifest(invalid.as_bytes()).is_err(), "{invalid:?}");
    }
}

#[test]
fn verified_manifest_rejects_extra_files_and_hardlinks() {
    let fixture = Fixture::new();
    fixture.write("artifact", b"sealed");
    let sums = fixture.seal(&[("artifact", b"sealed")]);
    VerifiedManifest::load(&fixture.root, &sha256(&sums), 1).expect("sealed fixture");

    fixture.write("extra", b"unsealed");
    assert!(VerifiedManifest::load(&fixture.root, &sha256(&sums), 1).is_err());
    std::fs::remove_file(fixture.root.join("extra")).expect("remove test extra");

    std::fs::hard_link(fixture.root.join("artifact"), fixture.root.join("alias"))
        .expect("create test hardlink");
    let linked_sums = fixture.seal(&[("alias", b"sealed"), ("artifact", b"sealed")]);
    assert!(VerifiedManifest::load(&fixture.root, &sha256(&linked_sums), 2).is_err());
}

#[cfg(unix)]
#[test]
fn verified_manifest_rejects_symlinks() {
    use std::os::unix::fs::symlink;

    let fixture = Fixture::new();
    fixture.write("target", b"sealed");
    symlink(fixture.root.join("target"), fixture.root.join("alias")).expect("create test symlink");
    let sums = fixture.seal(&[("alias", b"sealed"), ("target", b"sealed")]);
    assert!(VerifiedManifest::load(&fixture.root, &sha256(&sums), 2).is_err());
}

struct Fixture {
    _temporary: TempDir,
    root: std::path::PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let temporary = private_tempdir("temporary manifest fixture directory");
        let root = temporary
            .path()
            .canonicalize()
            .expect("canonical fixture root");
        Self {
            _temporary: temporary,
            root,
        }
    }

    fn write(&self, relative: &str, bytes: &[u8]) {
        write_private(&self.root.join(relative), bytes);
    }

    fn seal(&self, entries: &[(&str, &[u8])]) -> Vec<u8> {
        let mut sorted = entries.to_vec();
        sorted.sort_by_key(|(relative, _)| *relative);
        let mut sums = Vec::new();
        for (relative, bytes) in sorted {
            writeln!(sums, "{}  {relative}", sha256(bytes)).expect("write sums line");
        }
        let sums_path = self.root.join("SHA256SUMS");
        if sums_path.exists() {
            std::fs::remove_file(&sums_path).expect("replace test sums");
        }
        write_private(&sums_path, &sums);
        sums
    }
}

fn write_private(path: &Path, bytes: &[u8]) {
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).expect("create private test file");
    file.write_all(bytes).expect("write private test file");
}
