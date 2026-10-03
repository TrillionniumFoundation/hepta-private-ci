use super::*;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;

#[test]
fn ordinary_agent_cannot_consume_any_fixed_role_slot() {
    if rustix::process::geteuid().as_raw() == 0 {
        return;
    }
    let directory = tempfile::tempdir().unwrap();
    let output = directory.path().join("out.json");
    assert!(reserve_original_fixed_role_output_v1(&output).is_err());
    assert!(!output.exists());
}

#[test]
#[ignore = "requires actual UID/GID 0; original output slot only, no role signing claim"]
fn actual_root_fixed_role_completion_is_cold_exact_and_unknown_never_relaunches() -> ReviewResult<()>
{
    root()?;
    let directory = tempfile::tempdir()?;
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
