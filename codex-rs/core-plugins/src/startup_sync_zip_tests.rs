use super::extract_zipball_to_dir;
use pretty_assertions::assert_eq;
use std::fs;
use std::io::Cursor;
use std::io::Write;
use tempfile::tempdir;
use zip::CompressionMethod;
use zip::ZipWriter;
use zip::write::SimpleFileOptions;

#[test]
fn ordinary_archives_keep_contents_under_the_extraction_directory() {
    for compression in [
        CompressionMethod::Stored,
        CompressionMethod::Deflated,
        CompressionMethod::Bzip2,
        CompressionMethod::Zstd,
    ] {
        let destination = tempdir().expect("extraction directory");
        let contents = "name = \"example\"\nmessage = \"你好\"\n".as_bytes();
        let bytes = zip_with_file(
            "repo/plugins/example/config.toml",
            contents,
            SimpleFileOptions::default().compression_method(compression),
        );

        extract_zipball_to_dir(&bytes, destination.path()).expect("extract ordinary archive");

        assert_eq!(
            fs::read(destination.path().join("plugins/example/config.toml")).expect("read file"),
            contents
        );
        assert!(!destination.path().join("repo").exists());
        assert_eq!(
            fs::read_dir(destination.path()).expect("read root").count(),
            1
        );
    }
}

#[test]
fn ordinary_large_regular_entry_extracts_completely() {
    let destination = tempdir().expect("extraction directory");
    let contents = vec![b'x'; 2 * 1024 * 1024];
    let bytes = zip_with_file(
        "repo/assets/large.txt",
        &contents,
        SimpleFileOptions::default().compression_method(CompressionMethod::Stored),
    );

    extract_zipball_to_dir(&bytes, destination.path()).expect("extract regular large file");

    assert_eq!(
        fs::read(destination.path().join("assets/large.txt")).expect("read complete large file"),
        contents
    );
}

#[test]
fn truncated_ordinary_archive_returns_an_error_without_extracting_files() {
    let destination = tempdir().expect("extraction directory");
    let mut bytes = zip_with_file(
        "repo/README.md",
        b"ordinary file",
        SimpleFileOptions::default(),
    );
    bytes.truncate(bytes.len() / 2);

    let error = extract_zipball_to_dir(&bytes, destination.path()).expect_err("incomplete archive");

    assert!(error.contains("failed to open curated plugins zip archive"));
    assert_eq!(
        fs::read_dir(destination.path()).expect("read root").count(),
        0
    );
}

#[test]
fn internal_archive_link_retains_the_existing_regular_file_behavior() {
    let destination = tempdir().expect("extraction directory");
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    let options = SimpleFileOptions::default();
    writer
        .start_file("repo/README.md", options)
        .expect("start file");
    writer.write_all(b"ordinary file").expect("write file");
    writer
        .add_symlink("repo/shortcut", "README.md", options)
        .expect("internal archive link");
    let bytes = writer.finish().expect("finish archive").into_inner();

    extract_zipball_to_dir(&bytes, destination.path()).expect("extract internal link contents");

    let shortcut = destination.path().join("shortcut");
    assert!(fs::symlink_metadata(&shortcut).expect("metadata").is_file());
    assert_eq!(
        fs::read(shortcut).expect("read link contents"),
        b"README.md"
    );
    assert_eq!(
        fs::read(destination.path().join("README.md")).expect("read file"),
        b"ordinary file"
    );
}

#[cfg(unix)]
#[test]
fn archive_file_permissions_preserve_executable_bits() {
    use std::os::unix::fs::PermissionsExt;

    let destination = tempdir().expect("extraction directory");
    let bytes = zip_with_file(
        "repo/bin/helper.sh",
        b"#!/bin/sh\nprintf example\n",
        SimpleFileOptions::default().unix_permissions(/*mode*/ 0o751),
    );

    extract_zipball_to_dir(&bytes, destination.path()).expect("extract executable file");

    let path = destination.path().join("bin/helper.sh");
    assert_eq!(
        fs::metadata(&path).expect("metadata").permissions().mode() & 0o7777,
        0o751
    );
}

#[cfg(unix)]
#[test]
fn permission_policy_applies_only_ordinary_access_bits() {
    use std::os::unix::fs::PermissionsExt;

    let destination = tempdir().expect("extraction directory");
    let path = destination.path().join("ordinary-file");
    fs::write(&path, b"ordinary file").expect("create file");
    super::apply_zip_permissions(Some(0o7777), &path).expect("apply permission policy");
    assert_eq!(
        fs::metadata(&path).expect("metadata").permissions().mode() & 0o7777,
        0o777
    );
    super::apply_zip_permissions(/*mode*/ None, &path)
        .expect("missing permissions preserve the mode");
    assert_eq!(
        fs::metadata(&path).expect("metadata").permissions().mode() & 0o7777,
        0o777
    );
}

fn zip_with_file(name: &str, contents: &[u8], options: SimpleFileOptions) -> Vec<u8> {
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    writer
        .add_directory("repo/", SimpleFileOptions::default())
        .expect("root directory");
    writer.start_file(name, options).expect("start file");
    writer.write_all(contents).expect("write file");
    writer.finish().expect("finish archive").into_inner()
}
