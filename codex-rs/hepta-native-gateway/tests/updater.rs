#![forbid(unsafe_code)]
#![allow(dead_code)]

use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Result;
use anyhow::bail;
use pretty_assertions::assert_eq;

#[path = "../src/shell_runtime.rs"]
mod shell_runtime;
#[path = "../src/platform_adapter.rs"]
mod platform_adapter;
#[path = "../src/security.rs"]
mod security;
#[path = "../src/updater.rs"]
mod updater;

use platform_adapter::NativePlatform;
use security::DetachedSignatureVerifier;
use updater::ArtifactDigest;
use updater::PlatformArtifactVerifier;
use updater::TransactionalUpdater;
use updater::UpdateCandidate;
use updater::UpdateDisposition;
use updater::UpdateVerifier;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
const D2: &str = "2222222222222222222222222222222222222222222222222222222222222222";
const D3: &str = "3333333333333333333333333333333333333333333333333333333333333333";

#[derive(Clone, Debug)]
struct FixtureSignatures {
    accept: bool,
    messages: Arc<Mutex<Vec<Vec<u8>>>>,
}

impl FixtureSignatures {
    fn accepting() -> Self {
        Self {
            accept: true,
            messages: Arc::new(Mutex::new(Vec::new())),
        }
    }

    fn rejecting() -> Self {
        Self {
            accept: false,
            messages: Arc::new(Mutex::new(Vec::new())),
        }
    }
}

impl DetachedSignatureVerifier for FixtureSignatures {
    fn verify(&self, message: &[u8], _signature: &[u8]) -> Result<bool> {
        self.messages
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .push(message.to_vec());
        Ok(self.accept)
    }
}

#[derive(Clone, Copy, Debug)]
struct FixtureDigest;

impl ArtifactDigest for FixtureDigest {
    fn sha256(&self, path: &Path) -> Result<String> {
        match std::fs::read(path)?.as_slice() {
            b"old" => Ok(D1.to_string()),
            b"new" => Ok(D2.to_string()),
            _ => bail!("fixture artifact has no digest"),
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct FixturePlatformArtifact {
    accept: bool,
}

impl PlatformArtifactVerifier for FixturePlatformArtifact {
    fn verify(&self, _platform: NativePlatform, _path: &Path) -> Result<()> {
        if self.accept {
            Ok(())
        } else {
            bail!("fixture OS signing rejection")
        }
    }
}

fn root(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after unix epoch")
        .as_nanos();
    std::env::temp_dir().join(format!("hepta-native-update-{name}-{nonce}"))
}

fn layout(name: &str) -> Result<(PathBuf, PathBuf, PathBuf, PathBuf, PathBuf)> {
    let root = root(name);
    std::fs::create_dir_all(&root)?;
    let active = root.join("hepta-active");
    let rollback = root.join("hepta-rollback");
    let stage = root.join("hepta-stage");
    let journal = root.join("update.journal");
    let package = root.join("hepta-package");
    std::fs::write(&active, b"old")?;
    std::fs::write(&package, b"new")?;
    Ok((active, rollback, stage, journal, package))
}

fn candidate(package: PathBuf) -> UpdateCandidate {
    UpdateCandidate {
        package_path: package,
        package_digest: D2.to_string(),
        predecessor_digest: D1.to_string(),
        evidence_digest: D3.to_string(),
        producer_id: "release.builder".to_string(),
        selector_id: "release.reviewer".to_string(),
        channel: "stable".to_string(),
        platform: NativePlatform::Linux,
        architecture: "x86_64".to_string(),
        backend_protocol_version: 1,
        release_signature: vec![1, 2, 3],
        selection_signature: vec![4, 5, 6],
    }
}

fn verifier(
    release: FixtureSignatures,
    selection: FixtureSignatures,
) -> Result<
    UpdateVerifier<
        FixtureSignatures,
        FixtureSignatures,
        FixtureDigest,
        FixturePlatformArtifact,
    >,
> {
    UpdateVerifier::new(
        release,
        selection,
        FixtureDigest,
        FixturePlatformArtifact { accept: true },
        "stable".to_string(),
        NativePlatform::Linux,
        "x86_64".to_string(),
        1,
    )
}

#[test]
fn update_requires_release_and_independent_selection_signatures() -> Result<()> {
    let (_, _, _, _, package) = layout("verify")?;
    let verified = verifier(FixtureSignatures::accepting(), FixtureSignatures::accepting())?
        .verify(candidate(package.clone()))?;
    assert_eq!(verified.candidate.package_digest, D2);

    let error = verifier(FixtureSignatures::rejecting(), FixtureSignatures::accepting())?
        .verify(candidate(package.clone()))
        .unwrap_err();
    assert!(error.to_string().contains("release signature"));

    let error = verifier(FixtureSignatures::accepting(), FixtureSignatures::rejecting())?
        .verify(candidate(package.clone()))
        .unwrap_err();
    assert!(error.to_string().contains("selection signature"));

    let mut self_selected = candidate(package);
    self_selected.selector_id = self_selected.producer_id.clone();
    let error = verifier(FixtureSignatures::accepting(), FixtureSignatures::accepting())?
        .verify(self_selected)
        .unwrap_err();
    assert!(error.to_string().contains("independent"));
    Ok(())
}

#[test]
fn update_requires_selected_channel_and_os_signing_gate() -> Result<()> {
    let (_, _, _, _, package) = layout("platform-signing")?;
    let mut wrong_channel = candidate(package.clone());
    wrong_channel.channel = "beta".to_string();
    let error = verifier(FixtureSignatures::accepting(), FixtureSignatures::accepting())?
        .verify(wrong_channel)
        .unwrap_err();
    assert!(error.to_string().contains("channel"));

    let verifier = UpdateVerifier::new(
        FixtureSignatures::accepting(),
        FixtureSignatures::accepting(),
        FixtureDigest,
        FixturePlatformArtifact { accept: false },
        "stable".to_string(),
        NativePlatform::Linux,
        "x86_64".to_string(),
        1,
    )?;
    let error = verifier.verify(candidate(package)).unwrap_err();
    assert!(error.to_string().contains("OS signing/notarization"));
    Ok(())
}

#[test]
fn stage_does_not_replace_running_artifact_before_helper_activation() -> Result<()> {
    let (active, rollback, stage, journal, package) = layout("stage-only")?;
    let verified = verifier(FixtureSignatures::accepting(), FixtureSignatures::accepting())?
        .verify(candidate(package))?;
    let updater = TransactionalUpdater::open(
        FixtureDigest,
        active.clone(),
        rollback.clone(),
        stage.clone(),
        journal,
    )?;
    assert_eq!(
        updater.apply(&verified)?,
        UpdateDisposition::RestartRequired
    );
    assert_eq!(std::fs::read(&active)?, b"old");
    assert_eq!(std::fs::read(&rollback)?, b"old");
    assert_eq!(std::fs::read(&stage)?, b"new");
    std::fs::remove_dir_all(active.parent().expect("fixture root"))?;
    Ok(())
}

#[test]
fn update_is_confirmed_only_after_helper_activation_and_new_process_identity() -> Result<()> {
    let (active, rollback, stage, journal, package) = layout("confirm")?;
    let verified = verifier(FixtureSignatures::accepting(), FixtureSignatures::accepting())?
        .verify(candidate(package))?;
    let updater = TransactionalUpdater::open(
        FixtureDigest,
        active.clone(),
        rollback.clone(),
        stage.clone(),
        journal.clone(),
    )?;
    assert_eq!(
        updater.apply(&verified)?,
        UpdateDisposition::RestartRequired
    );
    drop(updater);

    let helper = TransactionalUpdater::open(
        FixtureDigest,
        active.clone(),
        rollback.clone(),
        stage,
        journal.clone(),
    )?;
    assert_eq!(
        helper.activate_staged()?,
        UpdateDisposition::RestartRequired
    );
    assert_eq!(std::fs::read(&active)?, b"new");
    drop(helper);

    let restarted = TransactionalUpdater::open(
        FixtureDigest,
        active.clone(),
        rollback.clone(),
        active.with_extension("unused-stage"),
        journal,
    )?;
    assert_eq!(
        restarted.recover_or_confirm(D2)?,
        UpdateDisposition::Confirmed
    );
    assert_eq!(std::fs::read(&active)?, b"new");
    assert!(!rollback.exists());
    std::fs::remove_dir_all(active.parent().expect("fixture root"))?;
    Ok(())
}

#[test]
fn failed_restart_identity_rolls_back_predecessor() -> Result<()> {
    let (active, rollback, stage, journal, package) = layout("rollback")?;
    let verified = verifier(FixtureSignatures::accepting(), FixtureSignatures::accepting())?
        .verify(candidate(package))?;
    let updater = TransactionalUpdater::open(
        FixtureDigest,
        active.clone(),
        rollback.clone(),
        stage.clone(),
        journal.clone(),
    )?;
    assert_eq!(
        updater.apply(&verified)?,
        UpdateDisposition::RestartRequired
    );
    drop(updater);

    let helper = TransactionalUpdater::open(
        FixtureDigest,
        active.clone(),
        rollback.clone(),
        stage,
        journal.clone(),
    )?;
    helper.activate_staged()?;
    drop(helper);

    let restarted = TransactionalUpdater::open(
        FixtureDigest,
        active.clone(),
        rollback,
        active.with_extension("unused-stage"),
        journal,
    )?;
    assert_eq!(
        restarted.recover_or_confirm(D1)?,
        UpdateDisposition::RolledBack
    );
    assert_eq!(std::fs::read(&active)?, b"old");
    std::fs::remove_dir_all(active.parent().expect("fixture root"))?;
    Ok(())
}
