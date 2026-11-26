use super::*;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;

fn source(path: &std::path::Path) -> InstalledCpuSourceV1 {
    let mut file = File::open(path).expect("open public test input");
    InstalledCpuSourceV1 {
        path: path.to_owned(),
        digest: Digest32::of_reader(&mut file, 512 * 1024 * 1024)
            .expect("bounded input SHA")
            .to_string(),
    }
}

fn write_input(path: &std::path::Path, magic: &[u8; 4]) {
    let mut file = File::create(path).expect("create public test input");
    file.write_all(magic).expect("test ELF marker");
    // Exercise a stream substantially larger than the descriptor/plan limits;
    // the fixture and production verifier both retain bounded read buffers.
    let chunk = [0x5a_u8; 8192];
    for _ in 0..4096 {
        file.write_all(&chunk).expect("stream public input");
    }
    file.sync_all().expect("persist public test input");
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .expect("exclusive Root test input");
}

#[test]
#[ignore = "requires actual kernel UID0 and protected Root ancestors"]
fn actual_root_streams_whole_worker_and_rejects_non_elf_mutation_and_replacement() {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    let directory = tempfile::tempdir_in("/root").expect("Root-owned isolated public fixture");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("Root-only directory");
    let path = directory.path().join("worker-public-test.elf");
    write_input(&path, b"\x7fELF");
    let pinned = source(&path);
    let expected = digest(&pinned.digest).expect("original SHA");
    let verified = VerifiedWorker::open(&pinned, expected).expect("whole streamed Worker fact");
    verified.revalidate().expect("unchanged held FD and path");
    assert!(VerifiedWorker::open(&pinned, Digest32::of_bytes(b"other Worker")).is_err());

    let replacement = directory.path().join("replacement.elf");
    write_input(&replacement, b"\x7fELF");
    assert_eq!(source(&replacement).digest, pinned.digest);
    std::fs::rename(&replacement, &path).expect("replace path by same public bytes");
    assert!(
        verified.revalidate().is_err(),
        "different inode is not the retained Worker"
    );

    let replaced = VerifiedWorker::open(&pinned, expected).expect("new exact immutable file");
    let mut changed = std::fs::OpenOptions::new()
        .write(true)
        .open(&path)
        .expect("test mutation");
    changed.seek(SeekFrom::End(-1)).expect("last original byte");
    changed.write_all(&[0x33]).expect("change original input");
    changed.sync_all().expect("persist original mutation");
    assert!(replaced.revalidate().is_err());
    assert!(VerifiedWorker::open(&pinned, expected).is_err());

    let non_elf = directory.path().join("not-elf-public-input");
    write_input(&non_elf, b"JSON");
    let wrong_magic = source(&non_elf);
    assert!(VerifiedWorker::open(&wrong_magic, digest(&wrong_magic.digest).expect("SHA")).is_err());

    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o660))
        .expect("make fixture input mutable by group");
    assert!(
        VerifiedWorker::open(&source(&path), digest(&source(&path).digest).expect("SHA")).is_err()
    );
    let symlink = directory.path().join("symlink.elf");
    std::os::unix::fs::symlink(&non_elf, &symlink).expect("public fixture symlink");
    assert!(
        VerifiedWorker::open(
            &source(&symlink),
            digest(&source(&symlink).digest).expect("SHA")
        )
        .is_err()
    );
}
