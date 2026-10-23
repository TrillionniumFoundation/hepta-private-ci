use super::*;
use tempfile::tempdir;
use tempfile::tempdir_in;

#[test]
fn portable_root_manifest_can_be_packed_and_unpacked() {
    let source = tempdir().expect("source tempdir");
    fs::write(
        source.path().join("plugin.json"),
        r#"{"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json","name":"portable"}"#,
    )
    .expect("write portable manifest");
    fs::create_dir_all(source.path().join("skills/demo")).expect("create skill directory");
    fs::write(source.path().join("skills/demo/SKILL.md"), "# Demo\n").expect("write skill");

    let archive =
        pack_plugin_bundle_tar_gz(source.path(), 1024 * 1024).expect("pack portable plugin");
    let destination = tempdir().expect("destination tempdir");
    unpack_plugin_bundle_tar_gz(&archive, destination.path(), 1024 * 1024)
        .expect("unpack portable plugin");

    assert!(destination.path().join("plugin.json").is_file());
    assert!(destination.path().join("skills/demo/SKILL.md").is_file());
}

#[test]
fn invalid_portable_manifest_is_rejected_before_packing() {
    let source = tempdir().expect("source tempdir");
    fs::write(
        source.path().join("plugin.json"),
        r#"{"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json","name":"UPPER"}"#,
    )
    .expect("write invalid portable manifest");

    let error = pack_plugin_bundle_tar_gz(source.path(), 1024 * 1024)
        .expect_err("invalid Agent Plugin manifest should fail");

    assert!(matches!(
        error,
        PluginBundlePackError::InvalidPluginPath { .. }
    ));
}

fn fixture_header(entry_type: tar::EntryType, path: &str, size: u64) -> tar::Header {
    let mut header = tar::Header::new_gnu();
    header.set_entry_type(entry_type);
    header.set_path(path).expect("fixture path");
    header.set_size(size);
    header.set_mode(0o644);
    header.set_uid(0);
    header.set_gid(0);
    header.set_mtime(0);
    header.set_cksum();
    header
}

fn append_fixture_entry(archive: &mut Vec<u8>, header: &tar::Header, payload: &[u8]) {
    archive.extend_from_slice(header.as_bytes());
    archive.extend_from_slice(payload);
    archive.resize(archive.len().div_ceil(512) * 512, 0);
}

fn gzip_fixture(archive: &[u8]) -> Vec<u8> {
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(archive).expect("compress fixture");
    encoder.finish().expect("finish fixture")
}

fn pax_longname_fixture(path: &str) -> Vec<u8> {
    // GHSA-3pv8-6f4r-ffg2: PAX size belongs to the next file, across the
    // intermediary GNU longname. Raw records keep this fixture independent of
    // either version's Builder interpretation of extension headers.
    let mut archive = Vec::new();
    let pax = b"13 size=2048\n";
    append_fixture_entry(
        &mut archive,
        &fixture_header(tar::EntryType::XHeader, "pax", pax.len() as u64),
        pax,
    );
    let mut longname = path.as_bytes().to_vec();
    longname.push(0);
    append_fixture_entry(
        &mut archive,
        &fixture_header(
            tar::EntryType::GNULongName,
            "longname",
            longname.len() as u64,
        ),
        &longname,
    );
    append_fixture_entry(
        &mut archive,
        &fixture_header(tar::EntryType::Regular, "file_a", /*size*/ 0),
        &[b'A'; 2048],
    );
    append_fixture_entry(
        &mut archive,
        &fixture_header(tar::EntryType::Regular, "file_b", /*size*/ 0),
        &[],
    );
    archive.resize(archive.len() + 1024, 0);
    gzip_fixture(&archive)
}

#[test]
fn pax_size_crosses_longname_header_without_hiding_files() {
    let destination = tempdir().expect("destination");
    unpack_plugin_bundle_tar_gz(
        &pax_longname_fixture("longname.txt"),
        destination.path(),
        /*max_total_bytes*/ 2048,
    )
    .expect("PAX size must apply to file, not GNU extension");
    assert_eq!(
        fs::read(destination.path().join("longname.txt")).expect("complete PAX file"),
        [b'A'; 2048],
    );
    assert_eq!(
        fs::read(destination.path().join("file_b")).expect("following file is not hidden"),
        Vec::<u8>::new(),
    );
    let mut names = fs::read_dir(destination.path())
        .expect("extracted entries")
        .map(|entry| entry.expect("entry").file_name())
        .collect::<Vec<_>>();
    names.sort();
    assert_eq!(names, ["file_b", "longname.txt"]);
}

#[test]
fn pax_size_still_enforces_actual_extracted_byte_limit() {
    let destination = tempdir().expect("destination");
    let error = unpack_plugin_bundle_tar_gz(
        &pax_longname_fixture("longname.txt"),
        destination.path(),
        /*max_total_bytes*/ 2047,
    )
    .expect_err("PAX size must not bypass the original byte limit");
    assert!(matches!(
        error,
        PluginBundleUnpackError::ExtractedBundleTooLarge {
            bytes: 2048,
            max_bytes: 2047
        }
    ));
    assert_eq!(
        fs::read_dir(destination.path())
            .expect("destination")
            .count(),
        0
    );
}

#[test]
fn pax_longname_still_rejects_parent_and_absolute_paths() {
    let root = tempdir().expect("root");
    let absolute = root.path().join("outside.txt");
    for path in [
        "../outside.txt".to_string(),
        absolute.to_string_lossy().into_owned(),
    ] {
        let destination = tempdir_in(root.path()).expect("destination");
        let error = unpack_plugin_bundle_tar_gz(
            &pax_longname_fixture(&path),
            destination.path(),
            /*max_total_bytes*/ 2048,
        )
        .expect_err("PAX/GNU path must stay inside extraction root");
        assert!(
            matches!(error, PluginBundleUnpackError::InvalidBundle(ref message) if message.contains("escapes extraction root"))
        );
        assert!(!absolute.exists());
        assert_eq!(
            fs::read_dir(destination.path())
                .expect("destination")
                .count(),
            0
        );
    }
}

#[test]
fn archive_symlinks_and_hardlinks_remain_rejected() {
    for entry_type in [tar::EntryType::Symlink, tar::EntryType::Link] {
        let destination = tempdir().expect("destination");
        let mut header = fixture_header(entry_type, "link", /*size*/ 0);
        header.set_link_name("outside").expect("link target");
        header.set_cksum();
        let mut archive = Vec::new();
        append_fixture_entry(&mut archive, &header, &[]);
        archive.resize(archive.len() + 1024, 0);
        let error = unpack_plugin_bundle_tar_gz(
            &gzip_fixture(&archive),
            destination.path(),
            /*max_total_bytes*/ 2048,
        )
        .expect_err("links must remain unsupported");
        assert!(
            matches!(error, PluginBundleUnpackError::InvalidBundle(ref message) if message.contains("is a link"))
        );
        assert_eq!(
            fs::read_dir(destination.path())
                .expect("destination")
                .count(),
            0
        );
    }
}
