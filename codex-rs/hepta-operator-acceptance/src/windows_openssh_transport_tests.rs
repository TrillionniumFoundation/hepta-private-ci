//! Real local pipe peers and real owned OpenSSH children; no PID substitutes.

use super::Fixture;
use super::NAMESPACE;
use crate::windows_openssh::BoundChild;
use crate::windows_openssh::OwnedChild;
use crate::windows_openssh::RunCleanup;
use crate::windows_openssh::VERIFY_DEADLINE;
use crate::windows_openssh::identity::TokenIdentity;
use crate::windows_openssh::image::SystemImage;
use crate::windows_openssh::pipe::PrivatePipe;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::process::Command;
use std::process::Stdio;
use std::time::Instant;
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::IO::*;
use windows_sys::Win32::System::Threading::*;

struct ActualChild {
    owned: OwnedChild,
    bound: BoundChild,
    image: SystemImage,
}

impl ActualChild {
    fn waiting_for_original_stdin(fixture: &Fixture) -> Self {
        let image = SystemImage::open().expect("retain actual installed system image");
        let owned = OwnedChild(
            Command::new(&image.path)
                .args(["-Y", "check-novalidate", "-n", NAMESPACE, "-s"])
                .arg(fixture.policy.parent().unwrap().join("statement.sig"))
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .expect("spawn only our real OpenSSH fixture child"),
        );
        let bound = BoundChild::bind(&owned.0, &image, &TokenIdentity::effective().unwrap())
            .expect("bind real kernel HANDLE/PID/image/token, never a provided PID");
        assert_eq!(
            unsafe { WaitForSingleObject(bound.handle.as_raw_handle() as _, 0) },
            WAIT_TIMEOUT,
            "the real child must still be waiting on its retained stdin"
        );
        Self {
            owned,
            bound,
            image,
        }
    }

    fn reap_with_original_cleanup(&mut self, first: &PrivatePipe, second: &PrivatePipe) {
        let mut cleanup = RunCleanup {
            child: &self.bound,
            allowed: first,
            signature: second,
            exited: false,
        };
        cleanup.finish().expect("original owned cleanup succeeds");
        assert_eq!(
            unsafe { WaitForSingleObject(self.bound.handle.as_raw_handle() as _, 0) },
            WAIT_OBJECT_0
        );
        assert!(self.owned.0.try_wait().unwrap().is_some());
        self.image
            .verify()
            .expect("held image unchanged after reap");
        eprintln!(
            "HEPTA_WIN_SSHSIG_OWNED_REAP pid={} signaled=true",
            self.bound.pid
        );
    }
}

struct PendingClientRead {
    file: File,
    byte: Box<u8>,
    overlapped: Box<OVERLAPPED>,
    _event: OwnedHandle,
    active: bool,
}

impl PendingClientRead {
    fn open_and_wait(name: &str) -> Self {
        let name: Vec<u16> = name.encode_utf16().chain([0]).collect();
        let raw = unsafe {
            CreateFileW(
                name.as_ptr(),
                GENERIC_READ,
                0,
                std::ptr::null(),
                OPEN_EXISTING,
                FILE_FLAG_OVERLAPPED,
                0,
            )
        };
        assert_ne!(
            raw,
            INVALID_HANDLE_VALUE,
            "open our actual unrelated-client pipe: {}",
            io::Error::last_os_error()
        );
        let file = unsafe { File::from_raw_handle(raw as _) };
        let raw_event = unsafe { CreateEventW(std::ptr::null(), 1, 0, std::ptr::null()) };
        assert_ne!(raw_event, 0, "create owned client read event");
        let event = unsafe { OwnedHandle::from_raw_handle(raw_event as _) };
        let mut overlapped: Box<OVERLAPPED> = Box::new(unsafe { std::mem::zeroed() });
        overlapped.hEvent = raw_event;
        let mut reader = Self {
            file,
            byte: Box::new(0),
            overlapped,
            _event: event,
            active: false,
        };
        let mut transferred = 0;
        let result = unsafe {
            ReadFile(
                reader.file.as_raw_handle() as _,
                &mut *reader.byte,
                1,
                &mut transferred,
                &mut *reader.overlapped,
            )
        };
        let error = unsafe { GetLastError() };
        if result == 0 && error == ERROR_IO_PENDING {
            reader.active = true;
        }
        assert_eq!(
            (result, error, transferred),
            (0, ERROR_IO_PENDING, 0),
            "one-byte read must actually be pending BEFORE the server attempts any bytes"
        );
        reader
    }

    fn require_no_byte_before_abort(&mut self) {
        let mut count = 0;
        let result = unsafe {
            GetOverlappedResult(
                self.file.as_raw_handle() as _,
                &*self.overlapped,
                &mut count,
                0,
            )
        };
        let error = unsafe { GetLastError() };
        if result != 0 || error != ERROR_IO_INCOMPLETE {
            self.active = false;
        }
        assert_eq!(
            (result, error, count),
            (0, ERROR_IO_INCOMPLETE, 0),
            "a pending read must still have no bytes BEFORE disconnect can discard buffers"
        );
        eprintln!(
            "HEPTA_WIN_SSHSIG_IMPOSTOR pending_read_before_abort=true bytes=0 raw_win32_error={error}"
        );
    }

    fn complete_after_abort(&mut self) {
        let mut count = 0;
        let result = unsafe {
            GetOverlappedResult(
                self.file.as_raw_handle() as _,
                &*self.overlapped,
                &mut count,
                1,
            )
        };
        let error = unsafe { GetLastError() };
        self.active = false;
        assert_eq!(result, 0, "disconnect must not produce successful bytes");
        assert!(matches!(
            error,
            ERROR_BROKEN_PIPE | ERROR_PIPE_NOT_CONNECTED | ERROR_OPERATION_ABORTED | ERROR_NO_DATA
        ));
        assert_eq!(count, 0);
        eprintln!(
            "HEPTA_WIN_SSHSIG_IMPOSTOR completed_after_abort=true bytes={count} raw_win32_error={error}"
        );
    }
}

impl Drop for PendingClientRead {
    fn drop(&mut self) {
        if self.active {
            unsafe {
                CancelIoEx(self.file.as_raw_handle() as _, &*self.overlapped);
                let mut transferred = 0;
                GetOverlappedResult(
                    self.file.as_raw_handle() as _,
                    &*self.overlapped,
                    &mut transferred,
                    1,
                );
            }
        }
    }
}

#[test]
#[ignore = "independent native transport control; preserve original26 scope"]
fn actual_unrelated_pipe_client_receives_no_original_bytes() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    let mut child = ActualChild::waiting_for_original_stdin(&fixture);
    assert_ne!(child.bound.pid, std::process::id());
    let pipe = PrivatePipe::create(owner.security.descriptor_bytes()).unwrap();
    let unused = PrivatePipe::create(owner.security.descriptor_bytes()).unwrap();
    let mut client = PendingClientRead::open_and_wait(&pipe.name);
    let error = pipe
        .send(
            &child.bound,
            b"original bytes must never reach an impostor",
            Instant::now() + VERIFY_DEADLINE,
        )
        .expect_err("an actual wrong client PID must fail before writing");
    assert_eq!(
        error.to_string(),
        "private verifier pipe client is not the retained live child"
    );
    client.require_no_byte_before_abort();
    pipe.abort();
    client.complete_after_abort();
    child.reap_with_original_cleanup(&pipe, &unused);
    owner.verify_policy().unwrap();
}

#[test]
#[ignore = "independent native transport control; preserve original26 scope"]
fn original_deadline_cancels_real_pending_connect_and_reaps_its_owned_child() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    let mut child = ActualChild::waiting_for_original_stdin(&fixture);
    let pipe = PrivatePipe::create(owner.security.descriptor_bytes()).unwrap();
    let unused = PrivatePipe::create(owner.security.descriptor_bytes()).unwrap();
    let start = Instant::now();
    let error = pipe
        .send(
            &child.bound,
            b"own timeout fixture",
            start + VERIFY_DEADLINE,
        )
        .expect_err("actual unconnected native operation must time out");
    assert_eq!(error.kind(), io::ErrorKind::TimedOut);
    assert_eq!(error.to_string(), "native verifier pipe IO deadline");
    eprintln!(
        "HEPTA_WIN_SSHSIG_CONNECT_TIMEOUT elapsed_millis={} original_deadline_millis={}",
        start.elapsed().as_millis(),
        VERIFY_DEADLINE.as_millis()
    );
    child.reap_with_original_cleanup(&pipe, &unused);
    owner.verify_policy().unwrap();
}
