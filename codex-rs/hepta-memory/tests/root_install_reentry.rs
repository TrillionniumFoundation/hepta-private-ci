//! Real SQLite and process-loss boundaries for the original physical owner.
//! These opt-in Root fixtures create no issuer, Current or writer authority.
#![cfg(target_os = "linux")]

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveCheckpointImage;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::io::Read;
use std::os::unix::ffi::OsStringExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize, Serialize)]
struct ImageInput {
    fleet: PathBuf,
    path: PathBuf,
    cut: CognitiveRecoveryAnchor,
    digest: Sha256Digest,
}

impl ImageInput {
    fn layout(&self) -> Result<HeptaAgentLayout> {
        Ok(HeptaFleetRoot::parse(self.fleet.clone())?
            .layout()
            .agent(&self.cut.owner_agent_id))
    }

    async fn verify(&self) -> Result<CognitiveCheckpointImage> {
        Ok(
            CognitiveStore::verify_retained_checkpoint_image(&self.path, &self.cut, &self.digest)
                .await?,
        )
    }
}

async fn fixture(content: Option<&str>) -> Result<(tempfile::TempDir, ImageInput)> {
    assert_eq!(
        (
            rustix::process::getuid().as_raw(),
            rustix::process::geteuid().as_raw()
        ),
        (0, 0),
        "explicit actual Root qualification required"
    );
    let temp = tempfile::tempdir()?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700))?;
    let fleet = temp.path().join("fleet");
    std::fs::create_dir(&fleet)?;
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
    let layout = HeptaFleetRoot::parse(fleet.clone())?.layout().agent(&agent);
    let store = CognitiveStore::open(&layout).await?;
    if let Some(content) = content {
        store
            .append_source(
                &CognitiveAccess::agent_private(agent),
                &SourceDraft {
                    scope: CognitiveScope::AgentPrivate,
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: "different-independent-image".into(),
                    content: content.as_bytes().to_vec(),
                    observed_at_unix_seconds: 100,
                },
            )
            .await?;
    }
    let cut = store.recovery_anchor().await?;
    let material = temp.path().join("independent-material");
    std::fs::create_dir(&material)?;
    std::fs::set_permissions(&material, std::fs::Permissions::from_mode(0o700))?;
    let path = material.join("original.sqlite3");
    // Only this fresh fixture owns the source. Hold the same real SQLite
    // BEGIN IMMEDIATE publication barrier through the public capture API;
    // the production owner's private serialization capability stays private.
    let barrier_pool = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(
        layout.cognitive_root().to_path_buf(),
    )?)
    .open_read_write_pool(store.path())
    .await?;
    let barrier = barrier_pool.begin_with("BEGIN IMMEDIATE").await?;
    let image =
        CognitiveStore::capture_live_checkpoint_image(&layout, /*source_uid*/ 0, &cut, &path)
            .await?;
    barrier.rollback().await?;
    barrier_pool.close().await;
    store.close().await;
    let digest = image.sha256().clone();
    Ok((
        temp,
        ImageInput {
            fleet,
            path,
            cut,
            digest,
        },
    ))
}

struct ChildGuard(Child);

impl Drop for ChildGuard {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

#[test]
#[ignore = "internal subprocess fixture, selected only by its crash-boundary parent"]
fn install_in_subprocess_until_parent_kills() -> Result<()> {
    let input = PathBuf::from(
        std::env::var_os("HEPTA_INSTALL_CRASH_TEST_INPUT").ok_or("fixture input absent")?,
    );
    let ready = input.with_extension("ready");
    let input: ImageInput = serde_json::from_slice(&std::fs::read(input)?)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let installed = runtime.block_on(async {
        Ok::<_, Box<dyn std::error::Error>>(
            CognitiveStore::install_root_checkpoint_image(&input.layout()?, input.verify().await?)
                .await?,
        )
    })?;
    let pending = ready.with_extension("pending");
    std::fs::write(&pending, installed.path().as_os_str().as_encoded_bytes())?;
    std::fs::rename(pending, ready)?;
    // Keep the actual original exclusive lock alive until the parent kills us.
    // This is an external process-loss boundary, not a success/error fixture.
    let mut byte = [0];
    std::io::stdin().read_exact(&mut byte)?;
    drop(installed);
    Ok(())
}

#[derive(Debug, Eq, PartialEq)]
struct Entry {
    identity: (u64, u64, u32, u32, u64),
    bytes: Vec<u8>,
}

fn inventory(root: &Path) -> Result<BTreeMap<PathBuf, Entry>> {
    let mut result = BTreeMap::new();
    for entry in std::fs::read_dir(root)? {
        let path = entry?.path();
        let metadata = path.symlink_metadata()?;
        let bytes = if metadata.file_type().is_symlink() {
            std::fs::read_link(&path)?
                .as_os_str()
                .as_encoded_bytes()
                .to_vec()
        } else if metadata.is_file() {
            std::fs::read(&path)?
        } else {
            Vec::new()
        };
        result.insert(
            path,
            Entry {
                identity: (
                    metadata.dev(),
                    metadata.ino(),
                    metadata.uid(),
                    metadata.mode(),
                    metadata.nlink(),
                ),
                bytes,
            },
        );
    }
    Ok(result)
}

#[tokio::test]
#[ignore = "explicit isolated Root physical-install process-loss qualification"]
async fn killed_installer_reopens_exact_inode_and_pointer_without_republication() -> Result<()> {
    let (temp, input) = fixture(/*content*/ None).await?;
    let layout = input.layout()?;
    let path = temp.path().join("child-input.json");
    std::fs::write(&path, serde_json::to_vec(&input)?)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let ready = path.with_extension("ready");
    let mut child = ChildGuard(
        Command::new(std::env::current_exe()?)
            .args([
                "--exact",
                "install_in_subprocess_until_parent_kills",
                "--ignored",
                "--nocapture",
            ])
            .env("HEPTA_INSTALL_CRASH_TEST_INPUT", &path)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()?,
    );
    let end = Instant::now() + Duration::from_secs(20);
    while !ready.exists() {
        assert!(
            child.0.try_wait()?.is_none(),
            "installer exited before the boundary"
        );
        assert!(
            Instant::now() < end,
            "installer did not reach the bounded physical boundary"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    let installed_path = PathBuf::from(std::fs::read_to_string(ready)?);
    let before = inventory(layout.cognitive_root())?;
    assert!(
        CognitiveStore::install_root_checkpoint_image(&layout, input.verify().await?)
            .await
            .is_err()
    );
    child.0.kill()?;
    assert!(!child.0.wait()?.success());
    let reopened =
        CognitiveStore::install_root_checkpoint_image(&layout, input.verify().await?).await?;
    assert_eq!(reopened.path(), installed_path);
    assert_eq!(inventory(layout.cognitive_root())?, before);
    assert_eq!(std::fs::read(reopened.path())?, std::fs::read(&input.path)?);
    drop(reopened);
    let again =
        CognitiveStore::install_root_checkpoint_image(&layout, input.verify().await?).await?;
    assert_eq!(again.path(), installed_path);
    assert_eq!(inventory(layout.cognitive_root())?, before);
    Ok(())
}

#[tokio::test]
#[ignore = "explicit isolated Root independent-image identity qualification"]
async fn a_different_valid_independent_image_cannot_replace_an_unreleased_installation()
-> Result<()> {
    let (_original, input) = fixture(/*content*/ None).await?;
    let (_alternative, different) = fixture(Some("a distinct original source event")).await?;
    assert_ne!(input.cut, different.cut);
    assert_ne!(input.digest, different.digest);
    let layout = input.layout()?;
    let installed =
        CognitiveStore::install_root_checkpoint_image(&layout, input.verify().await?).await?;
    let path = installed.path().to_path_buf();
    drop(installed);
    let before = inventory(layout.cognitive_root())?;
    assert!(
        CognitiveStore::install_root_checkpoint_image(&layout, different.verify().await?)
            .await
            .is_err()
    );
    assert_eq!(inventory(layout.cognitive_root())?, before);
    let reopened =
        CognitiveStore::install_root_checkpoint_image(&layout, input.verify().await?).await?;
    assert_eq!(reopened.path(), path);
    assert_eq!(inventory(layout.cognitive_root())?, before);
    Ok(())
}

#[tokio::test]
#[ignore = "explicit isolated Root partial-material qualification"]
async fn ambiguous_partial_and_aliased_installations_are_preserved_and_refused() -> Result<()> {
    #[derive(Debug)]
    enum Damage {
        Bytes,
        Unpublished,
        Second,
        PointerAlias,
        TargetAlias,
        NonUtf8,
        HardLink,
    }
    for attack in [
        Damage::Bytes,
        Damage::Unpublished,
        Damage::Second,
        Damage::PointerAlias,
        Damage::TargetAlias,
        Damage::NonUtf8,
        Damage::HardLink,
    ] {
        let (temp, input) = fixture(/*content*/ None).await?;
        let layout = input.layout()?;
        let installed =
            CognitiveStore::install_root_checkpoint_image(&layout, input.verify().await?).await?;
        let path = installed.path().to_path_buf();
        drop(installed); // An uncertain attempt cannot supply a live installation handle.
        let pointer = layout.cognitive_root().join(".cognitive-active-v1");
        match attack {
            Damage::Bytes => std::fs::OpenOptions::new()
                .write(true)
                .open(&path)?
                .set_len(512)?,
            Damage::Unpublished => std::fs::remove_file(&pointer)?,
            Damage::Second => {
                let second = layout
                    .cognitive_root()
                    .join(format!("cognitive_recovered_v1_{}.sqlite3", "a".repeat(64)));
                std::fs::copy(&path, second)?;
            }
            Damage::PointerAlias => {
                let saved = temp.path().join("preserved-pointer");
                std::fs::rename(&pointer, &saved)?;
                symlink(saved, &pointer)?;
            }
            Damage::TargetAlias => {
                let saved = temp.path().join("preserved-installation");
                std::fs::rename(&path, &saved)?;
                symlink(saved, &path)?;
            }
            Damage::NonUtf8 => {
                let mut name = b"cognitive_recovered_v1_".to_vec();
                name.push(0xff);
                std::fs::write(layout.cognitive_root().join(OsString::from_vec(name)), b"")?;
            }
            Damage::HardLink => {
                std::fs::hard_link(&path, temp.path().join("aliased-installation"))?
            }
        }
        let before = inventory(layout.cognitive_root())?;
        assert!(
            CognitiveStore::install_root_checkpoint_image(&layout, input.verify().await?)
                .await
                .is_err(),
            "accepted {attack:?}"
        );
        assert_eq!(inventory(layout.cognitive_root())?, before);
    }
    Ok(())
}
