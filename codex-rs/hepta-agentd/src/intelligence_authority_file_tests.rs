use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use ed25519_dalek::Verifier;
use std::cell::Cell;
use std::fs::FileTimes;
use std::fs::OpenOptions;
use std::io::Write;
use std::rc::Rc;

#[cfg(unix)]
fn make_fifo(path: &Path) {
    assert!(
        std::process::Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(path)
            .status()
            .expect("POSIX mkfifo")
            .success()
    );
}

#[cfg(unix)]
fn expect_bounded_fifo_rejection(fifo: &Path, operation: impl FnOnce() -> bool + Send + 'static) {
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::mpsc;
    use std::time::Duration;

    let (sender, receiver) = mpsc::channel();
    let worker =
        std::thread::spawn(move || sender.send(operation()).expect("open result receiver"));
    let observed = receiver.recv_timeout(Duration::from_secs(/*secs*/ 2));
    // Release a regressed blocking read-open before joining and failing the
    // test, so even the failure path leaves no blocked test worker behind.
    if observed.is_err() {
        let rescue = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(fifo)
            .expect("release blocking FIFO open");
        receiver
            .recv_timeout(Duration::from_secs(/*secs*/ 2))
            .expect("FIFO opener finishes after cleanup");
        drop(rescue);
    }
    worker.join().expect("open worker");
    assert!(observed.expect("authority open must not wait for a FIFO writer"));
}

#[cfg(unix)]
#[test]
fn inspected_authority_fifo_replacement_is_rejected_without_waiting_for_a_writer() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    let retained = temp.path().join("retained.json");
    write_file(&path, b"trusted");
    let inspected = InspectedAuthorityFile::inspect(&path).expect("regular authority preflight");
    std::fs::rename(&path, &retained).expect("retain preflight inode");
    make_fifo(&path);
    expect_bounded_fifo_rejection(&path, move || inspected.open().is_err());
    assert_eq!(
        std::fs::read(retained).expect("unchanged original bytes"),
        b"trusted"
    );
}

#[cfg(unix)]
#[test]
fn inspected_authority_symlink_to_fifo_is_rejected_at_open_without_following_it() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    let retained = temp.path().join("retained.json");
    let fifo = temp.path().join("replacement.fifo");
    write_file(&path, b"trusted");
    let inspected = InspectedAuthorityFile::inspect(&path).expect("regular authority preflight");
    std::fs::rename(&path, &retained).expect("retain preflight inode");
    make_fifo(&fifo);
    std::os::unix::fs::symlink(&fifo, &path).expect("replacement final-component symlink");
    expect_bounded_fifo_rejection(&fifo, move || {
        inspected
            .open()
            .err()
            .and_then(|error| error.raw_os_error())
            == Some(libc::ELOOP)
    });
    assert_eq!(
        std::fs::read(retained).expect("unchanged original bytes"),
        b"trusted"
    );
}

fn write_file(path: &Path, bytes: &[u8]) {
    std::fs::write(path, bytes).expect("write authority fixture");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .expect("private authority fixture");
    }
}

fn signed_authority() -> (
    Vec<u8>,
    IntelligenceAuthorityVerifierV1,
    CurrentOwnerStateV1,
) {
    let signing = SigningKey::from_bytes(&[17; 32]);
    let verifier = IntelligenceAuthorityVerifierV1 {
        signer_id: "owner.authority".to_string(),
        verifying_key: signing.verifying_key().to_bytes(),
    };
    let current = CurrentOwnerStateV1 {
        owner_id: StableId::new("objective.compiler").expect("owner id"),
        generation: Generation::new(3).expect("generation"),
        implementation_digest: Digest32::of_bytes(b"implementation"),
        key_digest: Digest32::of_bytes(b"key"),
        key_epoch: 4,
        authority_epoch: 5,
        revocation_frontier_digest: Digest32::of_bytes(b"frontier"),
    };
    let mut authority = IntelligenceAuthorityFileV1 {
        schema_version: 1,
        authority_epoch: current.authority_epoch,
        revocation_frontier_digest: current.revocation_frontier_digest.to_string(),
        owners: vec![super::super::IntelligenceAuthorityOwnerFileV1 {
            owner_id: current.owner_id.to_string(),
            generation: current.generation.get(),
            implementation_digest: current.implementation_digest.to_string(),
            key_digest: current.key_digest.to_string(),
            key_epoch: current.key_epoch,
        }],
        signer_id: verifier.signer_id.clone(),
        signature: Vec::new(),
    };
    authority.signature = signing
        .sign(&super::super::authority_signing_payload(&authority).expect("signed payload"))
        .to_bytes()
        .to_vec();
    (
        serde_json::to_vec(&authority).expect("authority json"),
        verifier,
        current,
    )
}

#[test]
fn signed_authority_at_exact_byte_cap_retains_current_owner() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    let (mut bytes, verifier, current) = signed_authority();
    bytes.resize(MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES as usize, b' ');
    write_file(&path, &bytes);
    let mut oracle = FileBackedFreshnessOracleV1::new(path, verifier);
    assert_eq!(
        oracle.current(&current.owner_id).expect("current owner"),
        current
    );
}

#[test]
fn identity_and_other_small_order_verifier_keys_are_rejected_at_runner_admission() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    let mut identity = [0; 32];
    identity[0] = 1;
    // The zero encoding decompresses to a different small-order Edwards point.
    for verifying_key in [identity, [0; 32]] {
        assert!(matches!(
            super::super::AgentdIntelligenceProductRunnerV1::new(
                path.clone(),
                IntelligenceAuthorityVerifierV1 {
                    signer_id: "owner.authority".to_string(),
                    verifying_key,
                },
            ),
            Err(super::super::AgentdIntelligenceProductError::InvalidAuthorityVerifier)
        ));
    }
    let (_, verifier, _) = signed_authority();
    assert!(super::super::AgentdIntelligenceProductRunnerV1::new(path, verifier).is_ok());
}

#[test]
fn identity_key_signature_forgery_fails_before_current_owner_is_returned() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    let (bytes, mut verifier, current) = signed_authority();
    let mut authority: IntelligenceAuthorityFileV1 =
        serde_json::from_slice(&bytes).expect("authority json");
    let mut identity = [0; 32];
    identity[0] = 1;
    verifier.verifying_key = identity;
    // R is the identity and s is zero; this requires no signing secret.
    authority.signature = vec![0; 64];
    authority.signature[0] = 1;
    let key = ed25519_dalek::VerifyingKey::from_bytes(&identity).expect("weak point decodes");
    let signature = ed25519_dalek::Signature::from_bytes(
        &authority.signature.as_slice().try_into().expect("64 bytes"),
    );
    let payload = super::super::authority_signing_payload(&authority).expect("forged payload");
    // Demonstrate that ordinary verification accepts the adversarial signature.
    assert!(key.verify(&payload, &signature).is_ok());
    write_file(
        &path,
        &serde_json::to_vec(&authority).expect("forged authority json"),
    );
    let mut oracle = FileBackedFreshnessOracleV1::new(path, verifier);
    assert!(matches!(
        oracle.current(&current.owner_id),
        Err(CanonicalIntelligenceError::FreshnessUnavailable(owner)) if owner == current.owner_id
    ));
}

#[test]
fn bounded_reader_stops_an_endlessly_growing_source_at_the_overflow_sentinel() {
    struct GrowingSource(Rc<Cell<u64>>);

    impl Read for GrowingSource {
        fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
            bytes.fill(b' ');
            self.0.set(self.0.get() + bytes.len() as u64);
            Ok(bytes.len())
        }
    }

    let consumed = Rc::new(Cell::new(0));
    assert!(read_bounded_authority_file(GrowingSource(Rc::clone(&consumed))).is_err());
    assert_eq!(consumed.get(), MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES + 1);
}

#[test]
fn empty_and_already_oversized_files_fail_as_freshness_unavailable() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    let (_, verifier, current) = signed_authority();
    for bytes in [
        Vec::new(),
        vec![b' '; MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES as usize + 1],
    ] {
        write_file(&path, &bytes);
        let mut oracle = FileBackedFreshnessOracleV1::new(path.clone(), verifier.clone());
        assert!(matches!(
            oracle.current(&current.owner_id),
            Err(CanonicalIntelligenceError::FreshnessUnavailable(owner))
                if owner == current.owner_id
        ));
    }
}

#[test]
fn file_growth_after_open_is_rejected() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    write_file(&path, b"trusted");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    OpenOptions::new()
        .append(true)
        .open(&path)
        .expect("append authority")
        .write_all(&vec![b' '; MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES as usize])
        .expect("grow authority");
    assert!(reader.read().is_err());
}

#[test]
fn file_truncation_after_open_is_rejected() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    write_file(&path, b"trusted");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    OpenOptions::new()
        .write(true)
        .open(&path)
        .expect("truncate authority")
        .set_len(3)
        .expect("truncate authority");
    assert!(reader.read().is_err());
}

#[test]
fn same_length_in_place_update_after_open_is_rejected() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    write_file(&path, b"trusted");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    let mut writer = OpenOptions::new()
        .write(true)
        .open(&path)
        .expect("update authority");
    writer.write_all(b"revoked").expect("update authority");
    // Make the metadata change deterministic on filesystems with coarse clocks.
    writer
        .set_times(FileTimes::new().set_modified(std::time::UNIX_EPOCH))
        .expect("change authority version");
    assert!(reader.read().is_err());
}

#[cfg(unix)]
#[test]
fn replacement_with_matching_size_and_mtime_after_open_is_rejected() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    let replacement = temp.path().join("replacement.json");
    write_file(&path, b"trusted");
    write_file(&replacement, b"revoked");
    File::open(&replacement)
        .expect("open replacement")
        .set_times(
            FileTimes::new().set_modified(
                std::fs::metadata(&path)
                    .expect("authority metadata")
                    .modified()
                    .expect("authority mtime"),
            ),
        )
        .expect("match replacement mtime");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    std::fs::rename(&replacement, &path).expect("replace authority path");
    assert!(reader.read().is_err());
}

#[cfg(unix)]
#[test]
fn unix_write_policy_is_preserved_and_rechecked_after_open() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    write_file(&path, b"trusted");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644))
        .expect("allow existing read-only sharing");
    assert_eq!(
        ValidatedAuthorityFile::open(&path)
            .expect("non-writable authority")
            .read()
            .expect("read authority"),
        b"trusted"
    );
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o620))
        .expect("introduce group write permission");
    assert!(reader.read().is_err());
    assert!(ValidatedAuthorityFile::open(&path).is_err());
}

#[cfg(unix)]
#[test]
fn group_and_world_writable_immediate_parents_are_rejected_before_open() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    write_file(&path, b"trusted");
    for mode in [0o720, 0o702, 0o777, 0o1777] {
        std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(mode))
            .expect("writable parent");
        assert!(ValidatedAuthorityFile::open(&path).is_err());
    }
    for mode in [0o700, 0o755] {
        std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(mode))
            .expect("owner-controlled parent");
        assert_eq!(
            ValidatedAuthorityFile::open(&path)
                .expect("owner-controlled parent")
                .read()
                .expect("read authority"),
            b"trusted"
        );
    }
}

#[cfg(unix)]
#[test]
fn parent_permission_drift_after_open_is_rejected_even_when_still_nonwritable() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    write_file(&path, b"trusted");
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private parent");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o755))
        .expect("change parent permission");
    assert!(reader.read().is_err());
}

#[cfg(unix)]
#[test]
fn newly_writable_parent_after_open_is_rejected() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    write_file(&path, b"trusted");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o722))
        .expect("introduce writable parent");
    assert!(reader.read().is_err());
}

#[cfg(unix)]
#[test]
fn parent_inode_drift_after_open_is_rejected_with_the_same_authority_inode() {
    let temp = tempfile::tempdir().expect("tempdir");
    let parent = temp.path().join("parent");
    let alternate = temp.path().join("alternate");
    let moved = temp.path().join("moved");
    std::fs::create_dir(&parent).expect("authority parent");
    std::fs::create_dir(&alternate).expect("alternate parent");
    let path = parent.join("authority.json");
    write_file(&path, b"trusted");
    std::fs::hard_link(&path, alternate.join("authority.json"))
        .expect("reuse authority inode before opening");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    std::fs::rename(&parent, &moved).expect("move parent directory");
    std::fs::rename(&alternate, &parent).expect("replace parent without changing authority inode");
    assert!(same_authority_file_version(
        &reader.metadata,
        &std::fs::metadata(&path).expect("same authority file version"),
    ));
    assert!(reader.read().is_err());
}

#[cfg(unix)]
#[test]
fn writable_nonsticky_ancestor_is_rejected_above_a_private_parent() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let private = temp.path().join("private");
    std::fs::create_dir(&private).expect("private authority parent");
    std::fs::set_permissions(&private, std::fs::Permissions::from_mode(0o700))
        .expect("private authority parent");
    let path = private.join("authority.json");
    write_file(&path, b"trusted");
    for mode in [0o720, 0o702, 0o777] {
        std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(mode))
            .expect("writable nonsticky ancestor");
        assert!(ValidatedAuthorityFile::open(&path).is_err());
    }
}

#[cfg(unix)]
#[test]
fn trusted_sticky_ancestor_accepts_a_private_authority_parent() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let private = temp.path().join("private");
    std::fs::create_dir(&private).expect("private authority parent");
    std::fs::set_permissions(&private, std::fs::Permissions::from_mode(0o700))
        .expect("private authority parent");
    let path = private.join("authority.json");
    write_file(&path, b"trusted");
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o1777))
        .expect("trusted sticky ancestor");
    assert_eq!(
        ValidatedAuthorityFile::open(&path)
            .expect("trusted sticky namespace")
            .read()
            .expect("read authority"),
        b"trusted"
    );
}

#[cfg(unix)]
#[test]
fn ancestor_permission_drift_after_open_is_rejected() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let private = temp.path().join("private");
    std::fs::create_dir(&private).expect("private authority parent");
    let path = private.join("authority.json");
    write_file(&path, b"trusted");
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private ancestor");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o1700))
        .expect("change ancestor policy while retaining trusted ownership");
    assert!(reader.read().is_err());
}

#[cfg(unix)]
#[test]
fn final_component_symlink_is_rejected_before_and_after_open() {
    use std::os::unix::fs::symlink;

    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("authority.json");
    let target = temp.path().join("target.json");
    write_file(&path, b"trusted");
    write_file(&target, b"trusted");
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    std::fs::remove_file(&path).expect("remove authority path");
    symlink(&target, &path).expect("substitute symlink");
    assert!(reader.read().is_err());
    assert!(ValidatedAuthorityFile::open(&path).is_err());
}

#[cfg(unix)]
#[test]
fn stable_parent_alias_is_supported_but_retargeting_same_inode_is_rejected() {
    use std::os::unix::fs::symlink;

    let temp = tempfile::tempdir().expect("tempdir");
    let original = temp.path().join("original");
    let alternate = temp.path().join("alternate");
    let alias = temp.path().join("alias");
    std::fs::create_dir(&original).expect("original directory");
    std::fs::create_dir(&alternate).expect("alternate directory");
    write_file(&original.join("authority.json"), b"trusted");
    std::fs::hard_link(
        original.join("authority.json"),
        alternate.join("authority.json"),
    )
    .expect("same inode in both directories");
    symlink(&original, &alias).expect("stable parent alias");
    let path = alias.join("authority.json");
    assert_eq!(
        ValidatedAuthorityFile::open(&path)
            .expect("stable parent alias")
            .read()
            .expect("stable alias read"),
        b"trusted"
    );
    let reader = ValidatedAuthorityFile::open(&path).expect("validated reader");
    std::fs::remove_file(&alias).expect("remove parent alias");
    symlink(&alternate, &alias).expect("retarget parent alias");
    assert!(reader.read().is_err());
}
