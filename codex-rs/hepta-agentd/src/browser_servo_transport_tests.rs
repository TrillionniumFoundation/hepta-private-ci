use std::process::Command;
use std::process::Stdio;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use super::BrowserServoError;
use super::BrowserServoTransport;
use super::ChildBrowserTransport;
use super::MAX_FRAME_BYTES;

fn child(script: &str, channel_wait: Duration) -> ChildBrowserTransport {
    let process = Command::new("/bin/sh")
        .arg("-c")
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("private test child");
    ChildBrowserTransport::from_child(process, channel_wait).expect("private transport")
}

#[test]
fn browser_servo_drop_releases_a_reader_blocked_by_a_full_queue() {
    let transport = child(
        "printf '\\000\\000\\000\\001x\\000\\000\\000\\001x\\000\\000\\000\\001x'; exec sleep 30",
        Duration::from_secs(1),
    );
    let first = transport
        .frames
        .as_ref()
        .expect("frames")
        .recv_timeout(Duration::from_secs(1));
    assert!(first.is_ok(), "child must have begun writing frames");
    thread::sleep(Duration::from_millis(20));
    let (finished, done) = mpsc::channel();
    thread::spawn(move || {
        drop(transport);
        finished.send(()).expect("cleanup receiver");
    });
    done.recv_timeout(Duration::from_secs(1))
        .expect("full response queue must not block cleanup");
}

#[test]
fn browser_servo_blocked_pipe_write_expires_and_closes_the_transport() {
    let mut transport = child("exec sleep 30", Duration::from_millis(50));
    let frame = vec![b'x'; MAX_FRAME_BYTES];
    let started = Instant::now();
    assert!(matches!(
        transport.write_frame(&frame),
        Err(BrowserServoError::Indeterminate(_))
    ));
    assert!(started.elapsed() < Duration::from_secs(1));
    assert!(matches!(
        transport.write_frame(&frame),
        Err(BrowserServoError::Unavailable(_))
    ));
}

#[test]
fn browser_servo_read_deadline_closes_the_transport() {
    let mut transport = child("exec sleep 30", Duration::from_millis(50));
    assert!(matches!(
        transport.read_frame(),
        Err(BrowserServoError::Indeterminate(_))
    ));
    assert!(matches!(
        transport.read_frame(),
        Err(BrowserServoError::Unavailable(_))
    ));
}

#[test]
fn browser_servo_private_child_frame_round_trip() {
    let mut transport = child("exec cat", Duration::from_secs(1));
    let frame = b"\0\0\0\x01x";
    transport.write_frame(frame).expect("bounded child write");
    assert_eq!(transport.read_frame().expect("bounded child read"), frame);
}

#[test]
fn browser_servo_drop_does_not_wait_for_a_descendant_inheriting_stdout() {
    let mut transport = child("sleep 3 & exit 0", Duration::from_secs(1));
    transport.child.wait().expect("parent has exited");
    let started = Instant::now();
    drop(transport);
    assert!(started.elapsed() < Duration::from_secs(1));
}
