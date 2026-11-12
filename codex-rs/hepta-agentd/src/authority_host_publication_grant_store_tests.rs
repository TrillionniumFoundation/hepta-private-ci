//! Actual UID0 stores and fresh OS processes. These test nonce-attempt storage,
//! not the original publication admission or an ordinary A/B/C positive.

use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::SystemAuthorityClock;
use pretty_assertions::assert_eq;

use super::*;

const CHILD: &str = "authority_host_service::generation_publication::grant_store::tests::original_publication_grant_dedicated_root_child";

fn original() -> anyhow::Result<ReservedPublicationProfile> {
    ReservedPublicationProfile::retain_original(super::super::versions::tests::profile(
        PublicationVersion::DurableV2,
    )?)
    .map_err(Into::into)
}

fn root() -> anyhow::Result<(tempfile::TempDir, Arc<RootAuthorityDirectory>)> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("root-publication-grant-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    Ok((directory, root))
}

fn primary(
    path: &Path,
    original: &ReservedPublicationProfile,
) -> anyhow::Result<std::path::PathBuf> {
    let profile = original.original_for_version(PublicationVersion::DurableV2)?;
    let owner = format!(
        "publication-grant/{}",
        Digest32::of_bytes(profile.learning_operation.as_bytes())
    );
    Ok(path.join(format!(
        "frontier-v1-{}.json",
        Digest32::of_bytes(owner.as_bytes())
    )))
}

fn child(path: &Path, phase: &str) -> anyhow::Result<()> {
    let mut child = Command::new(std::env::current_exe()?)
        .args(["--ignored", "--exact", CHILD, "--nocapture"])
        .env("HEPTA_PUBLICATION_GRANT_TEST_ROOT", path)
        .env("HEPTA_PUBLICATION_GRANT_TEST_PHASE", phase)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let pid = child.id();
    let end = Instant::now() + Duration::from_secs(15);
    while child.try_wait()?.is_none() {
        if Instant::now() >= end {
            child.kill()?;
            child.wait()?;
            anyhow::bail!("actual C grant child exceeded its original test deadline");
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    let output = child.wait_with_output()?;
    let receipt = format!("actual-c-grant:{phase}:{pid}");
    anyhow::ensure!(
        output.status.success() && String::from_utf8_lossy(&output.stdout).contains(&receipt),
        "phase={phase} status={} stdout={} stderr={}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(())
}

#[test]
#[ignore = "actual UID0 and Root-owned original directory required"]
fn root_publication_grant_attempt_survives_process_exit_without_new_nonce() -> anyhow::Result<()> {
    let (directory, root) = root()?;
    let original = original()?;
    let held = RegisteredPublicationGrant::enroll(
        root,
        &original,
        RootGenerationPublicationModeV1::Reserve,
    )?;
    let path = primary(directory.path(), &original)?;
    let available = std::fs::read(&path)?;
    // A real fresh child first proves this exact fixture/filter can reopen.
    child(directory.path(), "available")?;
    assert_eq!(std::fs::read(&path)?, available);
    held.begin()?;
    assert!(held.begin().is_err());
    assert!(held.require_exact().is_err());
    drop(held);
    let attempted = std::fs::read(&path)?;
    assert_ne!(attempted, available);
    child(directory.path(), "attempted")?;
    assert_eq!(std::fs::read(&path)?, attempted);
    Ok(())
}

#[test]
#[ignore = "actual UID0 and Root-owned original directory required"]
fn root_publication_grant_retains_actual_signature_and_reopen_never_issues() -> anyhow::Result<()> {
    let (directory, root) = root()?;
    let original = original()?;
    let binding = original
        .original_for_version(PublicationVersion::DurableV2)?
        .intent
        .binding()?;
    let issuer = crate::DeploymentFinalUseIssuer::create(
        &directory.path().join("component-issuer"),
        "component-original-issuer".into(),
        vec![crate::DeploymentGrantPolicy {
            subject_id: binding.subject_id.clone(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            lifetime_ms: 30_000,
        }],
        Arc::new(SystemAuthorityClock),
    )?;
    let held = RegisteredPublicationGrant::enroll(
        root,
        &original,
        RootGenerationPublicationModeV1::Reserve,
    )?;
    held.begin()?;
    // This actual local issuer is a storage-test input, not Root admission.
    let signed = issuer
        .issue(&binding)?
        .ok_or_else(|| anyhow::anyhow!("actual component policy must sign"))?;
    held.finish(&signed)?;
    assert!(held.begin().is_err());
    assert!(held.finish(&signed).is_err());
    assert_eq!(held.load_original()?.state, GrantPhase::Issued { signed });
    drop(held);
    let path = primary(directory.path(), &original)?;
    let issued = std::fs::read(&path)?;
    child(directory.path(), "issued")?;
    assert_eq!(std::fs::read(&path)?, issued);
    Ok(())
}

#[test]
#[ignore = "actual UID0 and Root-owned original directory required"]
fn root_publication_grant_recovery_refuses_missing_and_substituted_profile() -> anyhow::Result<()> {
    let (directory, root) = root()?;
    let original = original()?;
    let path = primary(directory.path(), &original)?;
    child(directory.path(), "missing")?;
    assert!(!path.exists());
    drop(RegisteredPublicationGrant::enroll(
        root,
        &original,
        RootGenerationPublicationModeV1::Reserve,
    )?);
    let available = std::fs::read(&path)?;
    child(directory.path(), "available")?;
    child(directory.path(), "different-profile")?;
    assert_eq!(std::fs::read(&path)?, available);
    Ok(())
}

#[test]
#[ignore = "dedicated actual Root child; requires exact phase and directory"]
fn original_publication_grant_dedicated_root_child() -> anyhow::Result<()> {
    original_root()?;
    let path = std::env::var_os("HEPTA_PUBLICATION_GRANT_TEST_ROOT")
        .ok_or_else(|| anyhow::anyhow!("original Root test directory required"))?;
    let phase = std::env::var("HEPTA_PUBLICATION_GRANT_TEST_PHASE")?;
    let root = RootAuthorityDirectory::open(Path::new(&path))?;
    let original = original()?;
    match phase.as_str() {
        "available" => {
            let held = RegisteredPublicationGrant::enroll(
                root,
                &original,
                RootGenerationPublicationModeV1::Recover,
            )?;
            assert_eq!(held.load_original()?.state, GrantPhase::Available {});
            assert!(held.begin().is_err());
        }
        "attempted" | "missing" => {
            assert!(
                RegisteredPublicationGrant::enroll(
                    root,
                    &original,
                    RootGenerationPublicationModeV1::Recover
                )
                .is_err()
            );
        }
        "issued" => {
            let held = RegisteredPublicationGrant::enroll(
                root,
                &original,
                RootGenerationPublicationModeV1::Recover,
            )?;
            let GrantPhase::Issued { signed } = held.load_original()?.state else {
                anyhow::bail!("actual retained signature required");
            };
            assert!(held.begin().is_err());
            assert!(held.finish(&signed).is_err());
        }
        "different-profile" => {
            let mut changed = original
                .original_for_version(PublicationVersion::DurableV2)?
                .clone();
            changed.decision = Digest32::of_bytes(b"different-actual-decision").to_string();
            changed.binding = changed.digest()?;
            let changed = ReservedPublicationProfile::retain_original(changed)?;
            assert!(
                RegisteredPublicationGrant::enroll(
                    root,
                    &changed,
                    RootGenerationPublicationModeV1::Recover
                )
                .is_err()
            );
        }
        _ => anyhow::bail!("unknown actual C grant test phase"),
    }
    println!("actual-c-grant:{phase}:{}", std::process::id());
    Ok(())
}
