use std::io::Cursor;
use std::io::Write;

use pretty_assertions::assert_eq;
use zip::ZipWriter;
use zip::write::SimpleFileOptions;

use super::extract_zipball_to_dir;

fn archive_with_file(name: &str, body: &[u8]) -> Vec<u8> {
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    writer
        .start_file(
            name,
            SimpleFileOptions::default().unix_permissions(/*mode*/ 0o755),
        )
        .expect("start archive file");
    writer.write_all(body).expect("write archive file");
    writer.finish().expect("finish archive").into_inner()
}

#[test]
#[cfg(unix)]
fn archive_modes_keep_executable_bits_without_special_privileges() {
    use std::os::unix::fs::PermissionsExt;

    let mut archive = archive_with_file("repository/tool", b"tool contents");
    let central = archive
        .windows(/*size*/ 4)
        .position(|bytes| bytes == b"PK\x01\x02")
        .expect("central directory");
    // Set the actual ZIP external attributes. The safe writer API itself masks
    // special bits, so passing a mode to FileOptions would not test this input.
    archive[central + 5] = 3; // Unix creator system.
    archive[central + 38..central + 42]
        .copy_from_slice(&((0o100000_u32 | 0o7755) << 16).to_le_bytes());
    let root = tempfile::tempdir().expect("temporary directory");
    let destination = root.path().join("extracted");

    extract_zipball_to_dir(&archive, &destination).expect("extract archive");

    let output = destination.join("tool");
    assert_eq!(std::fs::read(&output).expect("read tool"), b"tool contents");
    assert_eq!(
        std::fs::metadata(output)
            .expect("tool metadata")
            .permissions()
            .mode()
            & 0o7777,
        0o755
    );
}

#[test]
fn archive_traversal_cannot_overwrite_a_file_outside_the_destination() {
    let root = tempfile::tempdir().expect("temporary directory");
    let outside = root.path().join("outside");
    std::fs::write(&outside, b"unchanged").expect("write sentinel");
    let archive = archive_with_file("repository/../../outside", b"changed");

    let error = extract_zipball_to_dir(&archive, &root.path().join("extracted"))
        .expect_err("reject traversal");

    assert!(error.contains("escapes extraction root"));
    assert_eq!(std::fs::read(outside).expect("read sentinel"), b"unchanged");
}

#[test]
fn archive_symlink_cannot_redirect_a_later_entry_outside_the_destination() {
    let root = tempfile::tempdir().expect("temporary directory");
    let outside = root.path().join("outside");
    std::fs::create_dir(&outside).expect("create outside directory");
    std::fs::write(outside.join("sentinel"), b"unchanged").expect("write sentinel");
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    writer
        .add_symlink(
            "repository/link",
            "../outside",
            SimpleFileOptions::default(),
        )
        .expect("add symlink entry");
    writer
        .start_file("repository/link/sentinel", SimpleFileOptions::default())
        .expect("start later entry");
    writer.write_all(b"changed").expect("write later entry");
    let archive = writer.finish().expect("finish archive").into_inner();
    let destination = root.path().join("extracted");

    extract_zipball_to_dir(&archive, &destination).expect_err("link is never a directory");

    assert!(
        std::fs::symlink_metadata(destination.join("link"))
            .expect("link entry metadata")
            .is_file()
    );
    assert_eq!(
        std::fs::read(outside.join("sentinel")).expect("read sentinel"),
        b"unchanged"
    );
}
