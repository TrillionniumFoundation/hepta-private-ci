//! Actual Root CLI refusal and ownership controls, using synthetic descriptors.
//! These do not represent an authorized human or a successful physical login.

use super::run;
use pretty_assertions::assert_eq;
use std::ffi::OsString;
use std::io::Read;
use std::os::fd::IntoRawFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

#[test]
fn original_login_requires_native_profile_before_any_descriptor_is_claimed() {
    for command in ["serve-session", "serve-fresh-session"] {
        let error = run([
            command,
            "--config",
            "unopened-config",
            "--registration",
            "unopened-registration",
            "--owner-pidfd-stdin",
            "--original-login-pidfd",
            "0",
        ]
        .map(OsString::from))
        .unwrap_err();
        assert_eq!(
            error.to_string(),
            "original login pidfd requires the original native profile"
        );
    }
}

#[test]
fn original_login_rejects_standard_and_absent_descriptors_before_root_open() {
    for command in ["serve-session", "serve-fresh-session"] {
        for number in ["0", "1", "2", "2147483647"] {
            let error = run([
                command,
                "--config",
                "unopened-config",
                "--registration",
                "unopened-registration",
                "--owner-pidfd-stdin",
                "--native-profile",
                "unopened-native-profile",
                "--original-login-pidfd",
                number,
            ]
            .map(OsString::from))
            .unwrap_err();
            if number == "2147483647" {
                assert_eq!(
                    error
                        .downcast_ref::<std::io::Error>()
                        .unwrap()
                        .raw_os_error(),
                    Some(libc::EBADF)
                );
            } else {
                assert_eq!(
                    error.to_string(),
                    "one distinct inherited descriptor numbered at least 3 is required per slot"
                );
            }
        }
    }
}

#[test]
fn original_login_cannot_alias_root_and_rejection_closes_the_claimed_original() {
    for command in ["serve-session", "serve-fresh-session"] {
        let (offered, mut peer) = UnixStream::pair().unwrap();
        let number = offered.into_raw_fd().to_string();
        let error = run([
            command,
            "--config",
            "unopened-config",
            "--registration",
            "unopened-registration",
            "--owner-pidfd-stdin",
            "--native-profile",
            "unopened-native-profile",
            "--root-pidfd",
            &number,
            "--original-login-pidfd",
            &number,
        ]
        .map(OsString::from))
        .unwrap_err();
        assert_eq!(
            error.to_string(),
            "one distinct inherited descriptor numbered at least 3 is required per slot"
        );
        peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
        assert_eq!(
            peer.read(&mut [0]).unwrap(),
            0,
            "the first claimed slot closes its original endpoint on alias refusal"
        );
    }
}
