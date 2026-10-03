//! Bounded executable verification through the original protected file owner.
use crate::initial_neuron_operational_source::HostResult;
use codex_hepta_learning_ledger::open_root_review_input;
use codex_hepta_types::Digest32;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

fn identity(meta: &std::fs::Metadata) -> (u64, u64, u64, i64, i64, i64, i64) {
    (
        meta.dev(),
        meta.ino(),
        meta.len(),
        meta.mtime(),
        meta.mtime_nsec(),
        meta.ctime(),
        meta.ctime_nsec(),
    )
}

/// Verify the whole pinned ELF with a bounded streaming buffer. This proves a
/// public file fact, never a role, invocation, selection or process admission.
pub fn verify_registered_operational_program_v3(
    path: &Path,
    expected: Digest32,
) -> HostResult<Digest32> {
    if expected.is_zero() {
        return Err("empty registered executable pin".into());
    }
    let mut file = open_root_review_input(path)?;
    let before = identity(&file.metadata()?);
    let mut magic = [0_u8; 4];
    file.read_exact(&mut magic)?;
    if magic != *b"\x7fELF" {
        return Err("registered executable is not ELF".into());
    }
    file.seek(SeekFrom::Start(0))?;
    let actual = Digest32::of_reader(&mut file, 512 * 1024 * 1024)?;
    if actual != expected
        || identity(&file.metadata()?) != before
        || identity(&open_root_review_input(path)?.metadata()?) != before
    {
        return Err("registered executable bytes or protected identity changed".into());
    }
    Ok(actual)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::PermissionsExt;

    struct Directory(std::path::PathBuf);
    impl Directory {
        fn new(parent: &Path) -> Self {
            use std::sync::atomic::AtomicU64;
            use std::sync::atomic::Ordering;
            static NEXT: AtomicU64 = AtomicU64::new(0);
            let path = parent.join(format!(
                "hepta-registered-program-test-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::DirBuilder::new()
                .mode(0o700)
                .create(&path)
                .expect("exclusive fixture directory");
            Self(path)
        }
        fn path(&self) -> &Path {
            &self.0
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn unprotected_public_program_cannot_be_verified_by_matching_bytes_or_zero_pin() {
        let directory = Directory::new(&std::env::temp_dir());
        let path = directory.path().join("program.elf");
        let bytes = b"\x7fELFpublic fixture";
        std::fs::write(&path, bytes).expect("write public fixture");
        assert!(
            verify_registered_operational_program_v3(&path, Digest32::of_bytes(bytes)).is_err()
        );
        assert!(verify_registered_operational_program_v3(&path, Digest32::ZERO).is_err());
        assert_eq!(std::fs::read(&path).expect("unchanged fixture"), bytes);
    }

    #[test]
    #[ignore = "requires actual kernel UID0 and protected Root ancestors"]
    fn actual_root_verifies_large_whole_program_and_rejects_wrong_pin_magic_and_link() {
        assert_eq!(rustix::process::geteuid().as_raw(), 0);
        let directory = Directory::new(Path::new("/root"));
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .expect("Root directory");
        let path = directory.path().join("program.elf");
        let mut file = std::fs::File::create(&path).expect("create public input");
        file.write_all(b"\x7fELF").expect("ELF prefix");
        for _ in 0..4096 {
            file.write_all(&[0x19; 8192])
                .expect("bounded fixture writer");
        }
        file.sync_all().expect("persist public input");
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
            .expect("exclusive public input");
        let mut reader = std::fs::File::open(&path).expect("read fixture");
        let expected =
            Digest32::of_reader(&mut reader, 512 * 1024 * 1024).expect("whole public SHA");
        assert_eq!(
            verify_registered_operational_program_v3(&path, expected).expect("streamed whole file"),
            expected
        );
        assert!(
            verify_registered_operational_program_v3(&path, Digest32::of_bytes(b"wrong")).is_err()
        );
        let link = directory.path().join("link.elf");
        std::os::unix::fs::symlink(&path, &link).expect("fixture symlink");
        assert!(verify_registered_operational_program_v3(&link, expected).is_err());
        let non_elf = directory.path().join("not-elf");
        std::fs::write(&non_elf, b"JSON").expect("public non-ELF fixture");
        std::fs::set_permissions(&non_elf, std::fs::Permissions::from_mode(0o600))
            .expect("Root protected fixture");
        assert!(
            verify_registered_operational_program_v3(&non_elf, Digest32::of_bytes(b"JSON"))
                .is_err()
        );
    }
}
