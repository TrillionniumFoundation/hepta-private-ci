use super::*;
use std::collections::BTreeMap;
use std::os::unix::fs::PermissionsExt;

fn require_closed(owner: &Path) -> anyhow::Result<()> {
    let lock = fs::File::options()
        .read(true)
        .write(true)
        .open(owner.join("authority.lock"))?;
    lock.try_lock()
        .map_err(|error| anyhow::anyhow!("Browser FinalUse owner is still open: {error}"))?;
    drop(lock);
    Ok(())
}

fn copy_closed(source: &Path, target: &Path) -> anyhow::Result<()> {
    let metadata = fs::symlink_metadata(source)?;
    anyhow::ensure!(metadata.is_dir() && !target.exists());
    fs::create_dir(target)?;
    fs::set_permissions(target, metadata.permissions())?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let destination = target.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_closed(&entry.path(), &destination)?;
        } else {
            anyhow::ensure!(
                entry.file_type()?.is_file(),
                "nonregular closed fixture entry"
            );
            fs::copy(entry.path(), &destination)?;
            fs::set_permissions(&destination, entry.metadata()?.permissions())?;
            fs::File::open(destination)?.sync_all()?;
        }
    }
    fs::File::open(target)?.sync_all()?;
    Ok(())
}

fn image(root: &Path) -> anyhow::Result<BTreeMap<PathBuf, (u32, Vec<u8>)>> {
    let mut image = BTreeMap::new();
    let mut pending = vec![PathBuf::new()];
    while let Some(relative) = pending.pop() {
        anyhow::ensure!(image.len() < 128, "closed fixture exceeds its file count");
        let path = root.join(&relative);
        let metadata = fs::symlink_metadata(&path)?;
        let bytes = if metadata.is_dir() {
            for entry in fs::read_dir(&path)? {
                pending.push(relative.join(entry?.file_name()));
            }
            Vec::new()
        } else {
            anyhow::ensure!(
                metadata.is_file() && metadata.len() < 1024 * 1024,
                "nonregular or oversized closed fixture"
            );
            fs::read(path)?
        };
        image.insert(relative, (metadata.permissions().mode(), bytes));
    }
    Ok(image)
}

#[test]
fn cold_restore_of_all_browser_local_files_refuses_consumed_nonce_and_revoked_history()
-> anyhow::Result<()> {
    for revoke in [false, true] {
        let fixture = Fixture::new()?;
        let invocation = fixture.invocation(/*nonce*/ 46, NOW + 30_000)?;
        let host = BrowserServoHost::open(&fixture.config_path)?;
        assert_eq!(host.authority.owner.capacity()?.used_nonces, 0);
        drop(host);
        require_closed(&fixture.local.join("authority"))?;
        let snapshot = fixture.root.path().join("closed-before");
        copy_closed(&fixture.local, &snapshot)?;
        let initial_image = image(&fixture.local)?;
        let h = harness(&fixture, &invocation)?;
        if revoke {
            let mut head = fixture.head.clone();
            head.revision += 1;
            head.revoked_grant_ids
                .insert(invocation.signed_grant.grant.grant_id.clone());
            fixture.publish(head, NOW + 60_000)?;
            assert!(matches!(
                h.port.call(BrowserServoCall::effect(
                    json!({"operationId":"revoked"}),
                    invocation.clone()
                )?),
                Err(BrowserServoError::Authority(FinalUseError::Revoked))
            ));
            assert_eq!(h.owner.capacity()?.used_nonces, 0);
            assert_eq!(entries(&h.output), 0);
        } else {
            h.port.call(BrowserServoCall::effect(
                json!({"operationId":"consumed"}),
                invocation.clone(),
            )?)?;
            assert_eq!(h.owner.capacity()?.used_nonces, 1);
            assert_eq!(entries(&h.output), 1);
        }
        let future = fs::read(fixture.trust_root.join("frontier.json"))?;
        drop(h);
        require_closed(&fixture.local.join("authority"))?;
        fs::rename(
            &fixture.local,
            fixture.root.path().join("retained-future-local"),
        )?;
        copy_closed(&snapshot, &fixture.local)?;
        assert_eq!(image(&fixture.local)?, initial_image);
        // Restore configuration, signed feed and every local owner byte, but
        // retain the external frontier and clock outside the cold snapshot.
        for _ in 0..2 {
            assert!(
                matches!(BrowserServoHost::open(&fixture.config_path), Err(BrowserServoError::Invalid(message))
                if message == "PQ Browser authority: AntiRollbackViolation")
            );
            require_closed(&fixture.local.join("authority"))?;
            assert_eq!(image(&fixture.local)?, initial_image);
            assert_eq!(fs::read(fixture.trust_root.join("frontier.json"))?, future);
        }
    }
    Ok(())
}
