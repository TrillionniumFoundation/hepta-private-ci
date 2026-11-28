//! Actual CLI ownership/refusal controls with synthetic socket descriptors.
//! No control provisions Root authority, a physical login, or training data.

use super::run;
use pretty_assertions::assert_eq;
use std::ffi::OsString;
use std::io::Read;
use std::os::fd::IntoRawFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

fn arguments() -> Vec<OsString> {
    [
        "serve-fresh-session",
        "--config",
        "unopened-config",
        "--registration",
        "unopened-registration",
        "--owner-pidfd-stdin",
        "--native-profile",
        "unopened-native-profile",
        "--paired-training-profile",
        "unopened-paired-profile",
    ]
    .map(OsString::from)
    .to_vec()
}

fn offer(
    args: &mut Vec<OsString>,
    peers: &mut Vec<UnixStream>,
    slot: &str,
) -> std::io::Result<String> {
    let (offered, peer) = UnixStream::pair()?;
    let number = offered.into_raw_fd().to_string();
    args.extend([OsString::from(slot), OsString::from(&number)]);
    peers.push(peer);
    Ok(number)
}

fn assert_closed(peers: Vec<UnixStream>) -> std::io::Result<()> {
    for mut peer in peers {
        peer.set_read_timeout(Some(Duration::from_secs(1)))?;
        assert_eq!(peer.read(&mut [0])?, 0);
    }
    Ok(())
}

#[test]
fn incomplete_paired_group_is_refused_before_claim_or_root_open() {
    let mut args = arguments();
    args.extend(["--original-login-pidfd", "0"].map(OsString::from));
    let mut open_only = arguments();
    open_only[0] = OsString::from("serve-session");
    for slot in [
        "--root-handoff-fd",
        "--root-pidfd",
        "--original-login-pidfd",
        "--root-paired-training-handoff-fd",
        "--paired-training-failure-fd",
        "--paired-training-correction-fd",
    ] {
        open_only.extend([OsString::from(slot), OsString::from("0")]);
    }
    for input in [args, open_only] {
        let error = run(input).unwrap_err();
        assert_eq!(
            error.to_string(),
            "paired training requires its complete profile/material/handoff group and the original fresh native launch, login and Root descriptors"
        );
    }
}

#[test]
fn paired_handoff_cannot_alias_original_root_and_all_claims_close() -> std::io::Result<()> {
    let mut args = arguments();
    let mut peers = Vec::new();
    offer(&mut args, &mut peers, "--root-handoff-fd")?;
    let root = offer(&mut args, &mut peers, "--root-pidfd")?;
    offer(&mut args, &mut peers, "--original-login-pidfd")?;
    args.extend(
        [
            "--root-paired-training-handoff-fd",
            &root,
            "--paired-training-failure-fd",
            "0",
            "--paired-training-correction-fd",
            "0",
        ]
        .map(OsString::from),
    );
    let error = run(args).unwrap_err();
    assert_eq!(
        error.to_string(),
        "one distinct inherited descriptor numbered at least 3 is required per slot"
    );
    assert_closed(peers)
}

#[test]
fn paired_material_slots_cannot_alias_and_rejection_closes_originals() -> std::io::Result<()> {
    let mut args = arguments();
    let mut peers = Vec::new();
    for slot in [
        "--root-handoff-fd",
        "--root-pidfd",
        "--original-login-pidfd",
        "--root-paired-training-handoff-fd",
    ] {
        offer(&mut args, &mut peers, slot)?;
    }
    let failure = offer(&mut args, &mut peers, "--paired-training-failure-fd")?;
    args.extend([
        OsString::from("--paired-training-correction-fd"),
        OsString::from(failure),
    ]);
    let error = run(args).unwrap_err();
    assert_eq!(
        error.to_string(),
        "one distinct inherited descriptor numbered at least 3 is required per slot"
    );
    assert_closed(peers)
}

#[test]
fn absent_paired_material_fd_refuses_before_any_runtime_or_root_open() -> std::io::Result<()> {
    let mut args = arguments();
    let mut peers = Vec::new();
    for slot in [
        "--root-handoff-fd",
        "--root-pidfd",
        "--original-login-pidfd",
        "--root-paired-training-handoff-fd",
    ] {
        offer(&mut args, &mut peers, slot)?;
    }
    args.extend(
        [
            "--paired-training-failure-fd",
            "2147483647",
            "--paired-training-correction-fd",
            "0",
        ]
        .map(OsString::from),
    );
    let error = run(args).unwrap_err();
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .unwrap()
            .raw_os_error(),
        Some(libc::EBADF)
    );
    assert_closed(peers)
}
