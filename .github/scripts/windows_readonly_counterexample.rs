//! Native counterexample only; no change to the original readonly constructor.
use super::*;
use serde_json::json;

#[test]
fn readonly_ambient_identity_does_not_write_or_delete() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    // SAFETY: retain sole ownership of the original process token throughout.
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-131-242-353-464")?;
    // SAFETY: both byte allocations hold complete live Windows SIDs.
    let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
    let mut everyone = unsafe { world_sid()? };
    // Only this newly owned disposable fixture receives broad ambient grants.
    // The readonly capability is deliberately not granted any write access.
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[logon.as_mut_ptr().cast(), everyone.as_mut_ptr().cast()],
            FILE_ALL_ACCESS,
        )?;
    }
    let outside = fixture.path().join("outside.txt");
    let created = fixture.path().join("created.txt");
    let outside_dir = fixture.path().join("outside-dir");
    std::fs::write(&outside, b"original outside bytes")?;
    std::fs::create_dir(&outside_dir)?;
    // SAFETY: use the original production readonly factory with retained inputs.
    let token = OwnedToken(unsafe {
        create_readonly_token_with_caps_from(base.0, &[capability.as_ptr()])?
    });
    // SAFETY: the token and all original SID allocations remain retained.
    let restricting_membership = unsafe {
        [
            token_has_restricting_sid(token.0, capability.as_ptr())?,
            token_has_restricting_sid(token.0, logon.as_mut_ptr().cast())?,
            token_has_restricting_sid(token.0, everyone.as_mut_ptr().cast())?,
        ]
    };
    let (read, results) = {
        // SAFETY: original RAII guard reverts this exact thread after native calls.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        let read = std::fs::read(&outside)?;
        let results = [
            std::fs::write(&outside, b"overwritten"),
            std::fs::write(&created, b"created"),
            std::fs::remove_file(&outside),
            std::fs::remove_dir(&outside_dir),
        ]
        .map(|result| result.err().map(|error| error.kind()));
        (read, results)
    };
    eprintln!(
        "HEPTA_READONLY_COUNTEREXAMPLE={}",
        json!({
            "schema":"hepta.readonly-ambient-identity-counterexample.v1",
            "originalReadonlyFactory":true,
            "restrictingMembershipCapabilityLogonEveryone":restricting_membership,
            "outsideReadPreserved":read == b"original outside bytes",
            "outsideErrors":results.map(|error|error.map(|kind|format!("{kind:?}"))),
            "outsideFileExists":outside.exists(),
            "outsideDirectoryExists":outside_dir.exists(),
            "outsideCreatedFileExists":created.exists(),
            "fixtureScopeOnly":true,
            "productionAuthorityGranted":false,
            "securityQualification":false
        })
    );
    assert_eq!(results, [Some(std::io::ErrorKind::PermissionDenied); 4]);
    assert_eq!(read, b"original outside bytes");
    Ok(())
}
