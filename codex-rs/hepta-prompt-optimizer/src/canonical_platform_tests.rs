use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;

type Fixture<T> = Result<T, Box<dyn std::error::Error>>;

fn capture_tree(root: &Path) -> Fixture<BTreeMap<PathBuf, Option<Vec<u8>>>> {
    let mut image = BTreeMap::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(directory)? {
            let path = entry?.path();
            let relative = path.strip_prefix(root)?.to_path_buf();
            if path.is_dir() {
                image.insert(relative, None);
                pending.push(path);
            } else {
                image.insert(relative, Some(std::fs::read(path)?));
            }
        }
    }
    Ok(image)
}

fn existing_state(parent: &Path) -> Fixture<PathBuf> {
    let root = parent.join("existing");
    std::fs::create_dir(&root)?;
    for (name, content) in [
        ("registry.sqlite", b"original state".as_slice()),
        ("registry.sqlite-wal", b"original WAL".as_slice()),
        ("registry.sqlite-shm", b"original shared state".as_slice()),
        ("active.json", b"original active pointer".as_slice()),
    ] {
        std::fs::write(root.join(name), content)?;
    }
    Ok(root)
}

#[test]
fn unsupported_prompt_registry_rejects_without_creating_or_rewriting_state() -> Fixture<()> {
    let temporary = tempfile::tempdir()?;
    let existing = existing_state(temporary.path())?;
    let before = capture_tree(temporary.path())?;
    for root in [temporary.path().join("missing"), existing] {
        assert!(matches!(
            DurablePromptRegistry::open_state_dir(&root, 64),
            Err(DurableRegistryError::UnsafeStateDirectory)
        ));
        assert_eq!(capture_tree(temporary.path())?, before);
    }
    Ok(())
}

#[test]
fn unsupported_final_use_authority_rejects_without_creating_or_rewriting_state() -> Fixture<()> {
    let temporary = tempfile::tempdir()?;
    let existing = existing_state(temporary.path())?;
    let before = capture_tree(temporary.path())?;
    let key = ed25519_dalek::SigningKey::from_bytes(&[23; 32]);
    for root in [temporary.path().join("missing"), existing] {
        assert!(matches!(
            FinalUseAuthority::open_state_dir(
                &root,
                "review-authority:prompt".to_owned(),
                key.verifying_key().to_bytes(),
                FinalUseRevocations {
                    authority_epoch: 1,
                    revision: 1,
                    revoked_grant_ids: BTreeSet::new(),
                },
            ),
            Err(FinalUseError::UnsafeStateDirectory)
        ));
        assert_eq!(capture_tree(temporary.path())?, before);
    }
    Ok(())
}
