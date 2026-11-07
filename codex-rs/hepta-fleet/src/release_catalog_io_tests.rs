use super::*;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

#[test]
fn opened_file_growth_and_truncation_are_refused_with_the_original_read_budget() -> TestResult {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("growing");
    let original = vec![b'a'; 65_537];
    std::fs::write(&path, &original)?;
    let mut snapshot = Snapshot::open(&path, original.len() as u64, FileRule::Regular)?;
    let mut writer = OpenOptions::new().append(true).open(&path)?;
    let mut visited = 0;
    assert!(
        snapshot
            .consume(|chunk| {
                if visited == 0 {
                    writer.write_all(b"overflow")?;
                }
                visited += chunk.len();
                Ok(())
            })
            .is_err()
    );
    assert_eq!(visited, original.len());
    std::fs::write(&path, &original)?;
    let mut snapshot = Snapshot::open(&path, original.len() as u64, FileRule::Regular)?;
    OpenOptions::new().write(true).open(&path)?.set_len(3)?;
    assert!(snapshot.consume(|_| Ok(())).is_err());
    Ok(())
}

#[test]
fn regular_read_keeps_exact_bound_and_rejects_an_oversized_opened_file() -> TestResult {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("control");
    let bytes = vec![b' '; super::super::MAX_RELEASE_MANIFEST_BYTES as usize];
    std::fs::write(&path, &bytes)?;
    assert_eq!(read(&path, bytes.len() as u64, FileRule::Regular)?, bytes);
    OpenOptions::new()
        .append(true)
        .open(&path)?
        .write_all(b"x")?;
    assert!(read(&path, bytes.len() as u64, FileRule::Regular).is_err());
    assert!(sha256(&path, bytes.len() as u64).is_err());
    assert!(read(temp.path(), u64::MAX, FileRule::Regular).is_err());
    Ok(())
}

#[cfg(unix)]
mod unix {
    use super::*;
    use crate::release_authority_tests::Fixture;
    use pretty_assertions::assert_eq;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;
    use std::path::PathBuf;
    use std::sync::mpsc;
    use std::time::Duration;

    fn mode(path: &Path, mode: u32) -> std::io::Result<()> {
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))
    }

    fn fifo(path: &Path) -> TestResult {
        assert!(
            std::process::Command::new("mkfifo")
                .arg(path)
                .status()?
                .success()
        );
        Ok(())
    }

    fn refuses_without_waiting_for_a_fifo_peer(
        path: PathBuf,
        operation: impl FnOnce() -> bool + Send + 'static,
    ) -> TestResult {
        let (sender, receiver) = mpsc::channel();
        let worker = std::thread::spawn(move || sender.send(operation()).unwrap());
        let result = receiver.recv_timeout(Duration::from_secs(2));
        if matches!(result, Err(mpsc::RecvTimeoutError::Timeout)) {
            // Unblock a regressed blocking open before joining the fixture;
            // failure still remains a failure, never a timeout relaxation.
            let rescue = OpenOptions::new()
                .write(true)
                .custom_flags(libc::O_NONBLOCK)
                .open(path)?;
            drop(rescue);
            worker.join().unwrap();
            panic!("catalog observation waited for a FIFO peer: {result:?}");
        }
        worker.join().unwrap();
        assert!(result?);
        Ok(())
    }

    #[test]
    fn path_replacement_does_not_mix_metadata_and_contents_from_two_files() -> TestResult {
        let temp = tempfile::tempdir()?;
        let path = temp.path().join("current");
        let replacement = temp.path().join("replacement");
        std::fs::write(&path, b"original")?;
        std::fs::write(&replacement, b"different")?;
        let mut snapshot = Snapshot::open(&path, 32, FileRule::Regular)?;
        std::fs::rename(&replacement, &path)?;
        assert_eq!(
            hash(&mut snapshot)?,
            format!("{:x}", Sha256::digest(b"original"))
        );
        assert_eq!(read(&path, 32, FileRule::Regular)?, b"different");
        Ok(())
    }

    #[test]
    fn symlinks_hardlinks_modes_and_fifo_are_refused_on_the_opened_object() -> TestResult {
        let temp = tempfile::tempdir()?;
        let path = temp.path().join("program");
        std::fs::write(&path, b"program")?;
        mode(&path, 0o555)?;
        let digest = format!("{:x}", Sha256::digest(b"program"));
        check_program(&path, 7, &digest)?;
        let link = temp.path().join("symlink");
        symlink(&path, &link)?;
        assert!(read(&link, 32, FileRule::Regular).is_err());
        let hard = temp.path().join("hardlink");
        std::fs::hard_link(&path, &hard)?;
        assert!(check_program(&path, 7, &digest).is_err());
        std::fs::remove_file(&hard)?;
        mode(&path, 0o444)?;
        assert!(check_program(&path, 7, &digest).is_err());
        mode(&path, 0o755)?;
        assert!(check_program(&path, 7, &digest).is_err());
        let path = temp.path().join("fifo");
        fifo(&path)?;
        let probe = path.clone();
        refuses_without_waiting_for_a_fifo_peer(path.clone(), move || sha256(&probe, 32).is_err())?;
        let probe = path.clone();
        refuses_without_waiting_for_a_fifo_peer(path, move || {
            read(&probe, 32, FileRule::Regular).is_err()
        })
    }

    #[test]
    fn ordinary_pq_guard_rechecks_actual_program_bytes_before_current_authority() -> TestResult {
        let mut fixture = Fixture::new()?;
        let id = fixture.install("catalog-v1")?;
        fixture.allow(&id)?;
        let guard = fixture.registry.admit_release(&fixture.agent, &id)?;
        let path = guard.release().program.clone();
        let original = std::fs::read(&path)?;
        let mut changed = original.clone();
        changed[0] ^= 1;
        mode(&path, 0o755)?;
        std::fs::write(&path, changed)?;
        mode(&path, 0o555)?;
        assert!(guard.revalidate().is_err());
        mode(&path, 0o755)?;
        std::fs::write(&path, original)?;
        mode(&path, 0o555)?;
        guard.revalidate()?;
        Ok(())
    }

    #[test]
    fn ordinary_pq_guard_and_fresh_admission_reject_rehashed_local_manifest_substitution()
    -> TestResult {
        let mut fixture = Fixture::new()?;
        let id = fixture.install("catalog-v1")?;
        fixture.allow(&id)?;
        let guard = fixture.registry.admit_release(&fixture.agent, &id)?;
        let manifest = fixture
            .registry
            .layout()
            .releases_root()
            .join(id.as_str())
            .join("release.json");
        let mut value: serde_json::Value = serde_json::from_slice(&std::fs::read(&manifest)?)?;
        value["agentd"]["args"]
            .as_array_mut()
            .unwrap()
            .push("--substituted".into());
        let bytes = crate::release_authority_set::record_bytes(&value)?;
        mode(&manifest, 0o644)?;
        std::fs::write(&manifest, &bytes)?;
        mode(&manifest, 0o444)?;
        assert!(guard.revalidate().is_err());
        drop(guard);
        let record = fixture
            .registry
            .load()?
            .agent(&fixture.agent)
            .cloned()
            .unwrap();
        let allowance = record
            .layout
            .releases_root()
            .join(format!("allow-{id}.json"));
        let mut value: serde_json::Value = serde_json::from_slice(&std::fs::read(&allowance)?)?;
        value["manifest_sha256"] = format!("{:x}", Sha256::digest(&bytes)).into();
        mode(&allowance, 0o644)?;
        std::fs::write(
            &allowance,
            crate::release_authority_set::record_bytes(&value)?,
        )?;
        mode(&allowance, 0o444)?;
        assert!(fixture.registry.admit_release(&fixture.agent, &id).is_err());
        Ok(())
    }

    #[test]
    fn ordinary_pq_admission_refuses_a_restored_fifo_manifest_without_waiting() -> TestResult {
        let mut fixture = Fixture::new()?;
        let id = fixture.install("catalog-v1")?;
        fixture.allow(&id)?;
        let root = fixture.registry.layout().releases_root().join(id.as_str());
        let manifest = root.join("release.json");
        mode(&root, 0o755)?;
        std::fs::remove_file(&manifest)?;
        fifo(&manifest)?;
        mode(&root, 0o555)?;
        let registry = fixture.registry.clone();
        let agent = fixture.agent.clone();
        refuses_without_waiting_for_a_fifo_peer(manifest, move || {
            registry.admit_release(&agent, &id).is_err()
        })
    }
}
