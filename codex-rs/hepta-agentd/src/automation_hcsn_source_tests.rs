use std::os::unix::fs::symlink;

use super::*;

const SUPERVISOR: &str = "qualification/hcsn_training/supervisor.py";
const HELPER: &str = "qualification/hcsn/nested/test_helper.py";

fn source_tree() -> anyhow::Result<(tempfile::TempDir, HcsnSourceManifest)> {
    let root = tempfile::tempdir()?;
    fs::create_dir_all(root.path().join("qualification/hcsn/nested"))?;
    fs::create_dir_all(root.path().join("qualification/hcsn_training"))?;
    let mut entries = BTreeMap::new();
    for (relative, bytes) in [
        (SUPERVISOR, b"# supervisor\n".as_slice()),
        (HELPER, b"value = 1\n"),
    ] {
        fs::write(root.path().join(relative), bytes)?;
        entries.insert(relative.to_string(), Sha256Digest::for_bytes(bytes));
    }
    let manifest = serde_json::from_value(serde_json::to_value(entries)?)?;
    Ok((root, manifest))
}

#[test]
fn exact_source_inventory_rejects_helper_drift_and_root_package_injection() -> anyhow::Result<()> {
    for fault in ["changed", "missing", "extra", "root-init"] {
        let (root, manifest) = source_tree()?;
        manifest.verify(root.path())?;
        let supervisor = fs::read(root.path().join(SUPERVISOR))?;
        match fault {
            "changed" => fs::write(root.path().join(HELPER), b"value = 2\n")?,
            "missing" => fs::remove_file(root.path().join(HELPER))?,
            "extra" => fs::write(
                root.path().join("qualification/hcsn_training/extra.py"),
                b"",
            )?,
            "root-init" => fs::write(root.path().join(ROOT_INIT), b"# new package initializer\n")?,
            _ => anyhow::bail!("unknown source fault"),
        }
        assert!(manifest.verify(root.path()).is_err(), "accepted {fault}");
        assert_eq!(fs::read(root.path().join(SUPERVISOR))?, supervisor);
    }
    let (root, mut manifest) = source_tree()?;
    fs::write(root.path().join(ROOT_INIT), b"")?;
    manifest
        .0
        .insert(ROOT_INIT.to_string(), Sha256Digest::for_bytes(b""));
    manifest.verify(root.path())?;
    fs::remove_file(root.path().join(ROOT_INIT))?;
    assert!(manifest.verify(root.path()).is_err());
    Ok(())
}

#[test]
fn source_aliases_are_rejected_even_when_their_bytes_match() -> anyhow::Result<()> {
    for fault in ["symlink", "hardlink", "directory-symlink"] {
        let (root, manifest) = source_tree()?;
        let helper = root.path().join(HELPER);
        let outside = root.path().join("same-source.py");
        fs::copy(&helper, &outside)?;
        match fault {
            "symlink" => {
                fs::remove_file(&helper)?;
                symlink(&outside, &helper)?;
            }
            "hardlink" => {
                fs::remove_file(&helper)?;
                fs::hard_link(&outside, &helper)?;
            }
            "directory-symlink" => {
                let nested = root.path().join("qualification/hcsn/nested");
                let moved = root.path().join("moved-nested");
                fs::rename(&nested, &moved)?;
                symlink(&moved, &nested)?;
            }
            _ => anyhow::bail!("unknown alias fault"),
        }
        assert!(manifest.verify(root.path()).is_err(), "accepted {fault}");
    }
    Ok(())
}

#[test]
fn manifest_decode_and_source_reads_enforce_bounds() -> anyhow::Result<()> {
    let digest = Sha256Digest::for_bytes(b"");
    let duplicate = format!(
        r#"{{"{SUPERVISOR}":"{}","{SUPERVISOR}":"{}"}}"#,
        digest.as_str(),
        digest.as_str()
    );
    assert!(serde_json::from_str::<HcsnSourceManifest>(&duplicate).is_err());
    let oversized: BTreeMap<_, _> = (0..=MAX_SOURCE_FILES)
        .map(|index| (format!("qualification/hcsn/{index}.py"), digest.clone()))
        .collect();
    assert!(
        serde_json::from_value::<HcsnSourceManifest>(serde_json::to_value(oversized)?).is_err()
    );
    for relative in [
        "qualification/hcsn/../foreign.py",
        "qualification/hcsn//alias.py",
        "qualification/foreign.py",
    ] {
        let map = BTreeMap::from([(relative, digest.clone())]);
        assert!(serde_json::from_value::<HcsnSourceManifest>(serde_json::to_value(map)?).is_err());
    }
    let (root, manifest) = source_tree()?;
    File::create(root.path().join(HELPER))?.set_len(MAX_SOURCE_BYTES + 1)?;
    assert!(manifest.verify(root.path()).is_err());
    Ok(())
}
