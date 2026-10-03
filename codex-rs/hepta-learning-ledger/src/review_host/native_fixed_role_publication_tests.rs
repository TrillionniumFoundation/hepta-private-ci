use super::*;
use std::os::unix::process::CommandExt;

struct OriginalSlotDirectory(std::path::PathBuf);
impl OriginalSlotDirectory {
    fn new() -> std::io::Result<Self> {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let parent = if root(None).is_ok() { std::path::PathBuf::from("/run") } else { std::env::temp_dir() };
        let path = parent.join(format!("hepta-original-fixed-role-test-{}-{}", std::process::id(), NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)));
        std::fs::create_dir(&path)?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700))?;
        Ok(Self(path))
    }
    fn path(&self) -> &std::path::Path { &self.0 }
}
impl Drop for OriginalSlotDirectory {
    fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); }
}

#[test]
#[ignore = "requires actual UID0 parent and kernel child enrolled nonzero Group"]
fn actual_root_original_frozen_group_survives_shared_slot_and_new_purpose_denies() {
    const CHILD: &str = "HEPTA_FROZEN_SLOT_ENROLLED_GROUP_FIXTURE_CHILD";
    if std::env::var_os(CHILD).is_none() {
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "review_host::native_fixed_role_publication::tests::actual_root_original_frozen_group_survives_shared_slot_and_new_purpose_denies", "--ignored", "--nocapture"])
            .env(CHILD, "1")
            .gid(65534)
            .output().unwrap();
        assert!(
            output.status.success(),
            "{}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        return;
    }
    let status = std::fs::read_to_string("/proc/self/status").unwrap();
    assert!(
        status
            .lines()
            .find(|line| line.starts_with("Uid:"))
            .unwrap()
            .split_whitespace()
            .skip(1)
            .all(|value| value == "0")
    );
    assert!(
        status
            .lines()
            .find(|line| line.starts_with("Gid:"))
            .unwrap()
            .split_whitespace()
            .skip(1)
            .all(|value| value == "65534")
    );
    assert!(root(None).is_ok());
    assert!(root(Some(OriginalFixedRolePurposeV1::FrozenGenerator)).is_ok());
    assert!(root(Some(OriginalFixedRolePurposeV1::CycleSelector)).is_err());
    let directory = OriginalSlotDirectory::new().unwrap();
    let output = directory.path().join("original-g.output");
    let request = Digest32::of_bytes(b"original exact group request");
    let program = Digest32::of_bytes(b"original real terminal program");
    let completed = execute_original_fixed_role_publication_v1(
        OriginalFixedRolePurposeV1::FrozenGenerator,
        &output,
        request,
        program,
        |mut stdout, _stderr| {
            use std::io::Write;
            stdout.write_all(b"original full frozen group publication")?;
            stdout.sync_all()?;
            Ok(std::process::Command::new("/usr/bin/true").status()?)
        },
        |bytes| {
            if bytes == b"original full frozen group publication" {
                Ok(())
            } else {
                Err("whole original bytes changed".into())
            }
        },
    )
    .unwrap()
    .unwrap();
    assert_eq!(completed, b"original full frozen group publication");
    assert_eq!(
        observe_original_fixed_role_publication_v1(
            OriginalFixedRolePurposeV1::FrozenGenerator,
            &output,
            request,
            program
        )
        .unwrap(),
        Some(completed)
    );
}
use std::io::Write;
use std::os::unix::fs::PermissionsExt;

#[test]
fn ordinary_agent_cannot_consume_any_fixed_role_slot() {
    if root(None).is_ok() {
        return;
    }
    let directory = OriginalSlotDirectory::new().unwrap();
    let output = directory.path().join("out.json");
    assert!(reserve_original_fixed_role_output_v1(&output).is_err());
    assert!(!output.exists());
}

#[test]
#[ignore = "requires actual UID/GID 0; original output slot only, no role signing claim"]
fn actual_root_fixed_role_completion_is_cold_exact_and_unknown_never_relaunches() -> ReviewResult<()>
{
    root(Some(OriginalFixedRolePurposeV1::PairedEvaluator))?;
    let directory = OriginalSlotDirectory::new()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let output = directory.path().join("original-e.json");
    let request = Digest32::of_bytes(b"actual fixed E request");
    let program = Digest32::of_bytes(b"actual E ELF");
    let verify = |bytes: &[u8]| -> ReviewResult<()> {
        if bytes != b"whole original result" {
            return Err("fixture whole result differs".into());
        }
        Ok(())
    };
    let completed = execute_original_fixed_role_publication_v1(
        OriginalFixedRolePurposeV1::PairedEvaluator,
        &output,
        request,
        program,
        |mut stdout, stderr| {
            stdout.write_all(b"whole original result")?;
            stdout.sync_all()?;
            stderr.sync_all()?;
            Ok(std::process::Command::new("/usr/bin/true").status()?)
        },
        verify,
    )?
    .ok_or("actual terminal result absent")?;
    assert_eq!(completed, b"whole original result");
    assert_eq!(
        observe_original_fixed_role_publication_v1(
            OriginalFixedRolePurposeV1::PairedEvaluator,
            &output,
            request,
            program
        )?,
        Some(completed.clone())
    );
    assert!(
        observe_original_fixed_role_publication_v1(
            OriginalFixedRolePurposeV1::CanaryObserver,
            &output,
            request,
            program
        )?
        .is_none()
    );
    assert!(
        observe_original_fixed_role_publication_v1(
            OriginalFixedRolePurposeV1::PairedEvaluator,
            &output,
            Digest32::of_bytes(b"changed request"),
            program
        )?
        .is_none()
    );
    let retained = execute_original_fixed_role_publication_v1(
        OriginalFixedRolePurposeV1::PairedEvaluator,
        &output,
        request,
        program,
        |_, _| panic!("completed effect reissued"),
        verify,
    )?;
    assert_eq!(retained, Some(completed));
    let partial = directory.path().join("unknown.json");
    let (mut consumed, _) = reserve_original_fixed_role_output_v1(&partial)?;
    consumed.write_all(b"whole original result")?;
    consumed.sync_all()?;
    drop(consumed);
    assert!(
        execute_original_fixed_role_publication_v1(
            OriginalFixedRolePurposeV1::PairedEvaluator,
            &partial,
            request,
            program,
            |_, _| panic!("unknown effect reissued"),
            verify
        )?
        .is_none()
    );
    let failed = directory.path().join("failed.json");
    assert!(
        execute_original_fixed_role_publication_v1(
            OriginalFixedRolePurposeV1::CanaryObserver,
            &failed,
            request,
            program,
            |_, _| Ok(std::process::Command::new("/usr/bin/false").status()?),
            |_| Ok(())
        )?
        .is_none()
    );
    assert!(
        execute_original_fixed_role_publication_v1(
            OriginalFixedRolePurposeV1::CanaryObserver,
            &failed,
            request,
            program,
            |_, _| panic!("failed consumed effect reissued"),
            |_| Ok(())
        )?
        .is_none()
    );
    Ok(())
}
