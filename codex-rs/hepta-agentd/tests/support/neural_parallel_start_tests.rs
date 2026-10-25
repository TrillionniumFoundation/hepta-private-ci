use std::io::Write;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Barrier;

use super::start_pair;

fn child() -> Child {
    Command::new("/bin/sh")
        .args(["-c", "read -r value; test \"$value\" = stop"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap()
}

fn stop(child: &mut Child) -> Result<(), String> {
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"stop\n")
        .map_err(|error| error.to_string())?;
    if child.wait().map_err(|error| error.to_string())?.success() {
        Ok(())
    } else {
        Err("owned child failed".to_owned())
    }
}

#[test]
fn two_independent_owned_children_are_live_before_either_start_returns() {
    let both_born = Barrier::new(2);
    let start = || {
        let mut child = child();
        both_born.wait();
        assert!(child.try_wait().unwrap().is_none());
        Ok(child)
    };
    let (mut left, mut right) = start_pair(start, start, stop).unwrap();
    assert_ne!(left.id(), right.id());
    assert!(left.try_wait().unwrap().is_none());
    assert!(right.try_wait().unwrap().is_none());
    stop(&mut left).unwrap();
    stop(&mut right).unwrap();
}

#[test]
fn either_start_failure_or_panic_unloads_the_exact_successful_peer_before_return() {
    for fail_left in [false, true] {
        for panic in [false, true] {
            let born = Barrier::new(2);
            let owned = std::sync::atomic::AtomicU32::new(0);
            let start = |fail| {
                if fail {
                    born.wait();
                    assert!(!panic, "controlled initializer panic");
                    return Err("controlled initializer refusal".to_owned());
                }
                let child = child();
                owned.store(child.id(), std::sync::atomic::Ordering::SeqCst);
                born.wait();
                Ok(child)
            };
            let mut reaped = Vec::new();
            let error = start_pair(
                || start(fail_left),
                || start(!fail_left),
                |child| {
                    reaped.push(child.id());
                    stop(child)
                },
            )
            .unwrap_err();
            assert!(error.contains(if panic { "panicked" } else { "refusal" }));
            assert!(error.contains("survivor unloaded"));
            assert_eq!(reaped, [owned.load(std::sync::atomic::Ordering::SeqCst)]);
        }
    }
}

#[test]
fn peer_failure_keeps_explicit_unload_error_instead_of_claiming_completion() {
    let child = child();
    let pid = child.id();
    let mut retained = None;
    let error = start_pair(
        || Ok(child),
        || Err("controlled failed peer".to_owned()),
        |child| {
            retained = Some(child.id());
            stop(child)?;
            Err("controlled original receipt rejection after exact wait".to_owned())
        },
    )
    .unwrap_err();
    assert_eq!(retained, Some(pid));
    assert!(error.contains("controlled failed peer"));
    assert!(error.contains("survivor unload unresolved"));
    assert!(error.contains("original receipt rejection"));
}
