use super::*;

// Produced independently by Python's zipfile + bz2, with all three special
// permission bits in the original central-directory Unix mode (0107755).
// Fixture SHA256: 5cc717bf12c0e45e3d2da44316e6fb2dae1382cd8f59cbdfbad1d423798385d7
const BZIP2_ZIPBALL: &[u8] = &[
    80, 75, 3, 4, 46, 0, 0, 0, 12, 0, 0, 0, 33, 40, 242, 145, 174, 3, 73, 0, 0, 0, 33, 0, 0, 0, 21,
    0, 0, 0, 114, 101, 112, 111, 115, 105, 116, 111, 114, 121, 47, 112, 108, 117, 103, 105, 110,
    46, 116, 120, 116, 66, 90, 104, 57, 49, 65, 89, 38, 83, 89, 144, 129, 175, 163, 0, 0, 2, 221,
    128, 0, 16, 64, 0, 16, 0, 0, 32, 62, 229, 87, 16, 32, 0, 49, 76, 38, 154, 3, 76, 66, 38, 134,
    64, 105, 130, 101, 24, 148, 140, 24, 194, 9, 2, 60, 178, 231, 10, 195, 81, 71, 73, 41, 248,
    187, 146, 41, 194, 132, 132, 132, 13, 125, 24, 80, 75, 1, 2, 46, 3, 46, 0, 0, 0, 12, 0, 0, 0,
    33, 40, 242, 145, 174, 3, 73, 0, 0, 0, 33, 0, 0, 0, 21, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 237,
    143, 0, 0, 0, 0, 114, 101, 112, 111, 115, 105, 116, 111, 114, 121, 47, 112, 108, 117, 103, 105,
    110, 46, 116, 120, 116, 80, 75, 5, 6, 0, 0, 0, 0, 1, 0, 1, 0, 67, 0, 0, 0, 124, 0, 0, 0, 0, 0,
];

#[test]
fn bzip2_zipball_extracts_independent_archive() {
    let destination = tempdir().unwrap();
    let mut archive = zip::ZipArchive::new(std::io::Cursor::new(BZIP2_ZIPBALL)).unwrap();
    std::assert_eq!(
        archive.by_index(0).unwrap().compression(),
        zip::CompressionMethod::Bzip2
    );
    extract_zipball_to_dir(BZIP2_ZIPBALL, destination.path()).unwrap();
    std::assert_eq!(
        std::fs::read(destination.path().join("plugin.txt")).unwrap(),
        b"Independent bzip2 plugin archive\n"
    );
}

#[cfg(unix)]
#[test]
fn zipball_special_mode_bits_never_reach_filesystem() {
    use std::os::unix::fs::PermissionsExt;
    let destination = tempdir().unwrap();
    extract_zipball_to_dir(BZIP2_ZIPBALL, destination.path()).unwrap();
    let mode = std::fs::metadata(destination.path().join("plugin.txt"))
        .unwrap()
        .permissions()
        .mode();
    std::assert_eq!(mode & 0o7777, 0o755);
}
