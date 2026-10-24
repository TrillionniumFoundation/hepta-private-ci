//! Real child-process SIGKILL at durable owner boundaries, not a state-model
//! substitute for Agentd RPC, physical provider I/O or target-host qualification.

use super::*;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

struct ChildGuard(Child);
impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn child_boundary() {
    let Ok(point) = std::env::var("HEPTA_TEST_NATIVE_CRASH_POINT") else {
        return;
    };
    let journal = PathBuf::from(std::env::var_os("HEPTA_TEST_NATIVE_JOURNAL").unwrap());
    let marker = PathBuf::from(std::env::var_os("HEPTA_TEST_NATIVE_MARKER").unwrap());
    let stop = |current: &str| {
        if current == point {
            std::fs::write(&marker, current).unwrap();
            std::fs::File::open(&marker).unwrap().sync_all().unwrap();
            loop {
                std::thread::park();
            }
        }
    };
    let mut control = DurableInferenceControl::open(&journal, 8).unwrap();
    stop("before-reserve");
    control.reserve_native(request("r1"), 1).unwrap();
    stop("after-reserve");
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch())
        .unwrap();
    stop("after-dispatch");
    if point.starts_with("after-abort") {
        control
            .prepare_native_abort_before_effect(token, "definitely unsent".to_string())
            .unwrap();
        stop("after-abort-prepare");
        control.complete_native_abort_before_effect("r1").unwrap();
        stop("after-abort-ack");
    } else {
        drop(token);
        control.native_started("r1", "turn-1".to_string()).unwrap();
        stop("after-started");
        if point == "after-cancel" {
            control.cancel_native("r1").unwrap();
            stop("after-cancel");
        }
        control
            .settle_native("r1", output(NativeRunStatus::Completed, Some(7)))
            .unwrap();
        stop("after-terminal");
    }
    panic!("unrecognized crash point {point}");
}

#[test]
fn sigkill_reopen_preserves_owner_lock_and_no_replay() {
    // The child is this test executable. The environment seam exists only in a
    // cfg(test) module and cannot kill a production process.
    for point in [
        "before-reserve",
        "after-reserve",
        "after-dispatch",
        "after-abort-prepare",
        "after-abort-ack",
        "after-started",
        "after-cancel",
        "after-terminal",
    ] {
        let journal = path(point);
        let marker = journal.with_extension("ready");
        let mut child = ChildGuard(
            Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "durable_control::native::tests::crash::child_boundary",
                    "--nocapture",
                ])
                .env("HEPTA_TEST_NATIVE_CRASH_POINT", point)
                .env("HEPTA_TEST_NATIVE_JOURNAL", &journal)
                .env("HEPTA_TEST_NATIVE_MARKER", &marker)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap(),
        );
        let deadline = Instant::now() + Duration::from_secs(15);
        while !marker.exists() {
            assert!(
                child.0.try_wait().unwrap().is_none(),
                "child exited before {point}"
            );
            assert!(Instant::now() < deadline, "child did not reach {point}");
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(
            DurableInferenceControl::open(&journal, 8).is_err(),
            "duplicate live owner at {point}"
        );
        child.0.kill().unwrap();
        assert!(!child.0.wait().unwrap().success());
        let mut reopened = DurableInferenceControl::open(&journal, 8).unwrap();
        match point {
            "before-reserve" => assert!(reopened.native_record("r1").is_none()),
            "after-reserve" => assert_eq!(
                reopened.native_record("r1").unwrap().state,
                NativeReservationState::Reserved
            ),
            "after-abort-prepare" => {
                assert!(
                    reopened
                        .native_record("r1")
                        .unwrap()
                        .pre_effect_abort_pending
                );
                reopened.complete_native_abort_before_effect("r1").unwrap();
            }
            "after-abort-ack" | "after-terminal" => assert_eq!(
                reopened.native_record("r1").unwrap().state,
                NativeReservationState::Released
            ),
            "after-dispatch" | "after-started" | "after-cancel" => assert_ne!(
                reopened.native_record("r1").unwrap().state,
                NativeReservationState::Released
            ),
            _ => unreachable!(),
        }
        if !matches!(point, "before-reserve" | "after-reserve") {
            assert!(
                reopened
                    .dispatch_native_with_pre_effect_abort("r1", dispatch())
                    .is_err(),
                "replayed after {point}"
            );
        }
        drop(reopened);
        std::fs::remove_file(journal).unwrap();
        std::fs::remove_file(marker).unwrap();
    }
}
