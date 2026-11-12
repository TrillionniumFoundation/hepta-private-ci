//! Actual Root-owned storage and distinct OS processes. This qualifies only
//! durable refusal mechanics, not a live issuer, an ordinary A run or Adopt.

use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;

use pretty_assertions::assert_eq;

use super::*;

#[path = "authority_host_publication_refusal_fixture_tests.rs"]
mod fixture;

const PRIMARY: &str = "publication-refusal-test-primary";
const CHILD: &str = "authority_host_service::generation_publication::refusal::tests::original_publication_refusal_dedicated_root_child";

fn end() -> Instant {
    Instant::now() + Duration::from_secs(5)
}

fn root() -> anyhow::Result<(tempfile::TempDir, Arc<RootAuthorityDirectory>)> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("publication-refusal-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    Ok((directory, root))
}

fn primary(
    root: Arc<RootAuthorityDirectory>,
    expected: &ReservedPublicationProfile,
) -> io::Result<()> {
    let store = HostAuthorityFrontierStore::<PublicationRecord>::open(root, PRIMARY.into())
        .map_err(io::Error::other)?;
    if store.load(PRIMARY).map_err(io::Error::other)?
        != (PublicationRecord {
            profile: expected.clone(),
            fenced: false,
        })
    {
        return Err(io::Error::other("actual primary differs"));
    }
    Ok(())
}

fn initialize(
    root: Arc<RootAuthorityDirectory>,
    binding: PublicationRefusalBinding,
    original: &ReservedPublicationProfile,
) -> io::Result<Arc<PublicationRefusal>> {
    PublicationRefusal::enroll(
        Arc::clone(&root),
        binding,
        RootGenerationPublicationModeV1::Reserve,
        end(),
        |handle| {
            HostAuthorityFrontierStore::initialize(
                Arc::clone(&root),
                PRIMARY.into(),
                PublicationRecord {
                    profile: original.clone(),
                    fenced: false,
                },
            )
            .map_err(io::Error::other)?;
            primary(root, original)?;
            Ok((handle, original.clone()))
        },
    )
}

fn child(path: &Path, phase: &str) -> anyhow::Result<()> {
    let mut child = Command::new(std::env::current_exe()?)
        .args(["--ignored", "--exact", CHILD, "--nocapture"])
        .env("HEPTA_PUBLICATION_REFUSAL_TEST_ROOT", path)
        .env("HEPTA_PUBLICATION_REFUSAL_TEST_PHASE", phase)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let pid = child.id();
    let deadline = Instant::now() + Duration::from_secs(15);
    while child.try_wait()?.is_none() {
        if Instant::now() >= deadline {
            child.kill()?;
            child.wait()?;
            anyhow::bail!("actual refusal child exceeded its original test deadline");
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    let output = child.wait_with_output()?;
    let receipt = format!("actual-publication-refusal:{phase}:{pid}");
    anyhow::ensure!(
        output.status.success() && String::from_utf8_lossy(&output.stdout).contains(&receipt),
        "phase={phase} status={} stdout={} stderr={}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    Ok(())
}

fn write_primary(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

#[test]
#[ignore = "actual UID0 and Root-owned original directory required"]
fn root_publication_refusal_cold_restore_rejects_after_observed_primary_corruption()
-> anyhow::Result<()> {
    let (directory, root) = root()?;
    let (binding, original) = fixture::profile()?;
    drop(initialize(root, binding, &original)?);
    // Prove this exact child/filter/path can first recover the complete record.
    child(directory.path(), "baseline")?;
    let path = directory.path().join(format!(
        "frontier-v1-{}.json",
        Digest32::of_bytes(PRIMARY.as_bytes())
    ));
    let retained = std::fs::read(&path)?;
    let mut corrupted = retained.clone();
    anyhow::ensure!(!corrupted.is_empty(), "actual nonempty primary required");
    corrupted[0] = b'!';
    write_primary(&path, &corrupted)?;
    // This child observes the real broken record and exits from inside action,
    // before an error handler could persist a separate refusal after the read.
    child(directory.path(), "observe-and-exit")?;
    write_primary(&path, &retained)?;
    assert_eq!(std::fs::read(&path)?, retained);
    child(directory.path(), "restored-refused")?;
    Ok(())
}

#[test]
#[ignore = "actual UID0 and Root-owned original directory required"]
fn root_publication_refusal_cross_handle_attempts_and_missing_marker_fail_closed()
-> anyhow::Result<()> {
    let (_directory, root) = root()?;
    let (binding, original) = fixture::profile()?;
    let first = initialize(Arc::clone(&root), binding.clone(), &original)?;
    let second = PublicationRefusal::enroll(
        Arc::clone(&root),
        binding.clone(),
        RootGenerationPublicationModeV1::Recover,
        end(),
        |handle| {
            primary(Arc::clone(&root), &original)?;
            Ok((handle, original.clone()))
        },
    )?;
    let mut substituted = binding.clone();
    substituted.target = substituted.previous.clone();
    assert_eq!(substituted.owner(), binding.owner());
    assert!(
        PublicationRefusal::enroll::<()>(
            Arc::clone(&root),
            substituted,
            RootGenerationPublicationModeV1::Recover,
            end(),
            |_| panic!("another target must not select another refusal slot"),
        )
        .is_err()
    );
    let old_arm = first.inspect(&original, end(), || {
        primary(Arc::clone(&root), &original)?;
        first.store.load(&first.owner).map_err(io::Error::other)
    })?;
    let mut stale_ready = old_arm.clone();
    stale_ready.phase = Phase::Ready;
    second.inspect(&original, end(), || {
        let armed = second.store.load(&second.owner).map_err(io::Error::other)?;
        assert_eq!(armed.attempt, old_arm.attempt + 1);
        assert!(
            first
                .store
                .compare_and_set(&first.owner, &old_arm, &stale_ready)
                .is_err()
        );
        assert_eq!(
            second.store.load(&second.owner).map_err(io::Error::other)?,
            armed
        );
        primary(Arc::clone(&root), &original)
    })?;
    assert!(first.inspect(&original, end(), || second.refuse()).is_err());
    second.refuse()?;
    assert!(
        PublicationRefusal::enroll::<()>(
            Arc::clone(&root),
            binding.clone(),
            RootGenerationPublicationModeV1::Recover,
            end(),
            |_| panic!("refused operation must not enter the physical reader"),
        )
        .is_err()
    );

    let (_missing, missing) = self::root()?;
    HostAuthorityFrontierStore::initialize(
        Arc::clone(&missing),
        PRIMARY.into(),
        PublicationRecord {
            profile: original.clone(),
            fenced: false,
        },
    )?;
    assert!(
        PublicationRefusal::enroll::<()>(
            Arc::clone(&missing),
            binding.clone(),
            RootGenerationPublicationModeV1::Recover,
            end(),
            |_| panic!("missing marker must not admit an old primary"),
        )
        .is_err()
    );
    assert!(initialize(Arc::clone(&missing), binding, &original).is_err());
    primary(missing, &original)?;
    Ok(())
}

#[test]
#[ignore = "dedicated actual Root child, only invoked by its parent test"]
fn original_publication_refusal_dedicated_root_child() -> anyhow::Result<()> {
    original_root()?;
    let root = RootAuthorityDirectory::open(Path::new(&std::env::var(
        "HEPTA_PUBLICATION_REFUSAL_TEST_ROOT",
    )?))?;
    let phase = std::env::var("HEPTA_PUBLICATION_REFUSAL_TEST_PHASE")?;
    let (binding, original) = fixture::profile()?;
    match phase.as_str() {
        "baseline" => {
            PublicationRefusal::enroll(
                root.clone(),
                binding,
                RootGenerationPublicationModeV1::Recover,
                end(),
                |_| {
                    primary(root, &original)?;
                    Ok(((), original))
                },
            )?;
        }
        "observe-and-exit" => {
            let result: io::Result<()> = PublicationRefusal::enroll(
                root.clone(),
                binding,
                RootGenerationPublicationModeV1::Recover,
                end(),
                |_| {
                    assert!(primary(root, &original).is_err());
                    println!("actual-publication-refusal:{phase}:{}", std::process::id());
                    std::io::stdout().flush()?;
                    std::process::exit(0);
                },
            );
            result?;
            anyhow::bail!("the actual corruption child did not exit from its armed action");
        }
        "restored-refused" => {
            let called = AtomicBool::new(false);
            let result: io::Result<()> = PublicationRefusal::enroll(
                root.clone(),
                binding,
                RootGenerationPublicationModeV1::Recover,
                end(),
                |_| {
                    called.store(true, Ordering::SeqCst);
                    primary(root, &original)?;
                    Ok(((), original))
                },
            );
            assert!(result.is_err());
            assert!(!called.load(Ordering::SeqCst));
        }
        phase => anyhow::bail!("unknown actual publication refusal child phase: {phase}"),
    }
    println!("actual-publication-refusal:{phase}:{}", std::process::id());
    Ok(())
}
