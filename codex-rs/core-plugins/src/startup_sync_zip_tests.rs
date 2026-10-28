use super::extract_zipball_to_dir;
use pretty_assertions::assert_eq;
use std::io::Cursor;
use std::io::Write;
use tempfile::tempdir;
use zip::CompressionMethod;
#[cfg(unix)]
use zip::ZipArchive;
use zip::ZipWriter;
use zip::write::SimpleFileOptions;

const CONTENTS: &[u8] = b"#!/bin/sh\nprintf 'curated plugin'\n";

fn zipball_with_file(name: &str, method: CompressionMethod) -> Vec<u8> {
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    let options = SimpleFileOptions::default()
        .compression_method(method)
        .unix_permissions(0o755);
    writer.start_file(name, options).expect("start ZIP entry");
    writer.write_all(CONTENTS).expect("write ZIP entry");
    writer.finish().expect("finish ZIP archive").into_inner()
}

#[test]
fn zipball_extraction_preserves_contents_across_compression_methods() {
    for method in [
        CompressionMethod::Stored,
        CompressionMethod::Deflated,
        CompressionMethod::Bzip2,
        CompressionMethod::Zstd,
        CompressionMethod::Xz,
    ] {
        let destination = tempdir().expect("create extraction directory");
        let archive = zipball_with_file("archive/plugin/run.sh", method);

        extract_zipball_to_dir(&archive, destination.path()).expect("extract ZIP archive");

        assert_eq!(
            std::fs::read(destination.path().join("plugin/run.sh")).expect("read plugin"),
            CONTENTS
        );
    }
}

#[test]
fn zipball_extraction_reads_lzma_entries() {
    let destination = tempdir().expect("create extraction directory");
    let archive = include_bytes!("../tests/fixtures/zipball_lzma.zip");

    extract_zipball_to_dir(archive, destination.path()).expect("extract LZMA ZIP archive");

    assert_eq!(
        std::fs::read(destination.path().join("plugin/run.sh")).expect("read plugin"),
        CONTENTS
    );
}

#[cfg(unix)]
#[test]
fn zipball_extraction_strips_privileged_bits_and_keeps_executable_access() {
    use std::os::unix::fs::PermissionsExt;

    let destination = tempdir().expect("create extraction directory");
    let mut archive = zipball_with_file("archive/plugin/run.sh", CompressionMethod::Stored);
    // ZipWriter intentionally strips privileged bits. Set the external Unix
    // attributes in the central-directory record to model an untrusted ZIP.
    let central = archive
        .windows(4)
        .position(|bytes| bytes == b"PK\x01\x02")
        .expect("find central-directory record");
    let mode = 0o107755_u32;
    archive[central + 38..central + 42].copy_from_slice(&(mode << 16).to_le_bytes());
    let mut reader = ZipArchive::new(Cursor::new(&archive)).expect("reopen hostile ZIP");
    // unix_mode() already clears privileged bits in zip 9. Verify the actual
    // untrusted header metadata instead, then check the resulting filesystem.
    assert_eq!(
        reader
            .by_index(0)
            .expect("read hostile ZIP entry")
            .external_attributes()
            >> 16,
        mode
    );

    extract_zipball_to_dir(&archive, destination.path()).expect("extract hostile ZIP");

    let output = destination.path().join("plugin/run.sh");
    assert_eq!(
        std::fs::read(&output).expect("read extracted plugin"),
        CONTENTS
    );
    assert_eq!(
        std::fs::metadata(&output)
            .expect("read extracted permissions")
            .permissions()
            .mode()
            & 0o7777,
        0o755
    );
}

#[test]
fn zipball_extraction_rejects_paths_outside_the_destination() {
    let parent = tempdir().expect("create parent directory");
    let destination = parent.path().join("destination");
    let archive = zipball_with_file("archive/../../escaped", CompressionMethod::Stored);

    let error = extract_zipball_to_dir(&archive, &destination).expect_err("reject escaping path");

    assert!(error.contains("escapes extraction root"));
    assert!(!parent.path().join("escaped").exists());
}

#[test]
fn zipball_extraction_rejects_invalid_utf8_names() {
    let destination = tempdir().expect("create extraction directory");
    let mut archive = zipball_with_file("archive/plugin/run.sh", CompressionMethod::Stored);
    let central = archive
        .windows(4)
        .position(|bytes| bytes == b"PK\x01\x02")
        .expect("find central-directory record");
    let local_flags = u16::from_le_bytes(archive[6..8].try_into().expect("local ZIP flags"));
    let central_flags = u16::from_le_bytes(
        archive[central + 8..central + 10]
            .try_into()
            .expect("central ZIP flags"),
    );
    archive[6..8].copy_from_slice(&(local_flags | 0x800).to_le_bytes());
    archive[central + 8..central + 10].copy_from_slice(&(central_flags | 0x800).to_le_bytes());
    archive[30] = 0xff;
    archive[central + 46] = 0xff;

    let error = extract_zipball_to_dir(&archive, destination.path())
        .expect_err("reject invalid UTF-8 name");
    assert!(error.contains("declares UTF-8"));

    assert_eq!(
        std::fs::read_dir(destination.path())
            .expect("read extraction directory")
            .count(),
        0
    );
}

#[test]
fn zipball_extraction_preserves_valid_utf8_names() {
    let destination = tempdir().expect("create extraction directory");
    let archive = zipball_with_file("archive/plugin/café-中文.sh", CompressionMethod::Stored);
    let flags = u16::from_le_bytes(archive[6..8].try_into().expect("local ZIP flags"));
    assert_ne!(flags & 0x800, 0, "fixture must declare UTF-8");

    extract_zipball_to_dir(&archive, destination.path()).expect("extract valid UTF-8 name");

    assert_eq!(
        std::fs::read(destination.path().join("plugin/café-中文.sh")).expect("read UTF-8 plugin"),
        CONTENTS
    );
}

#[test]
fn zipball_extraction_preserves_legacy_cp437_names() {
    let destination = tempdir().expect("create extraction directory");
    let mut archive = zipball_with_file("archive/plugin/cafX.sh", CompressionMethod::Stored);
    let central = archive
        .windows(4)
        .position(|bytes| bytes == b"PK\x01\x02")
        .expect("find central-directory record");
    let flags = u16::from_le_bytes(archive[6..8].try_into().expect("local ZIP flags"));
    assert_eq!(flags & 0x800, 0, "legacy fixture must not declare UTF-8");
    let name_offset = b"archive/plugin/caf".len();
    archive[30 + name_offset] = 0x82;
    archive[central + 46 + name_offset] = 0x82;

    extract_zipball_to_dir(&archive, destination.path()).expect("extract CP437 name");

    assert_eq!(
        std::fs::read(destination.path().join("plugin/café.sh")).expect("read CP437 plugin"),
        CONTENTS
    );
}

#[test]
fn zipball_extraction_does_not_follow_archive_symlink_targets() {
    let parent = tempdir().expect("create parent directory");
    let outside = parent.path().join("outside");
    std::fs::write(&outside, b"unchanged").expect("write outside file");
    let destination = parent.path().join("destination");
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    writer
        .add_symlink(
            "archive/link",
            outside.to_string_lossy(),
            SimpleFileOptions::default(),
        )
        .expect("add hostile symlink");
    let archive = writer.finish().expect("finish ZIP archive").into_inner();

    extract_zipball_to_dir(&archive, &destination).expect("extract symlink as regular content");

    assert_eq!(
        std::fs::read(&outside).expect("read outside file"),
        b"unchanged"
    );
    assert!(
        !std::fs::symlink_metadata(destination.join("link"))
            .expect("read extracted file metadata")
            .file_type()
            .is_symlink()
    );
    assert_eq!(
        std::fs::read_to_string(destination.join("link")).expect("read regular link content"),
        outside.to_string_lossy()
    );
}
