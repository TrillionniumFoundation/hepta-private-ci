//! Shared durability primitives and qualification-only fault injection.
//!
//! Product builds always execute the real filesystem operation. The fault
//! injector exists only in unit tests or when the explicit `qualification`
//! feature is enabled; it is thread-local so parallel tests cannot corrupt
//! unrelated writers.

use std::fs::File;
use std::io;
use std::io::Write;

#[cfg(any(test, feature = "qualification"))]
use std::cell::RefCell;

#[cfg(any(test, feature = "qualification"))]
#[derive(Clone, Debug)]
struct QualificationFault {
    point: String,
    kind: io::ErrorKind,
    remaining: u32,
}

#[cfg(any(test, feature = "qualification"))]
thread_local! {
    static QUALIFICATION_FAULT: RefCell<Option<QualificationFault>> = const { RefCell::new(None) };
}

pub(crate) fn write_all(
    file: &mut File,
    bytes: &[u8],
    component: &str,
) -> io::Result<()> {
    check(component, "file_write")?;
    file.write_all(bytes)
}

pub(crate) fn sync_all(file: &File, component: &str) -> io::Result<()> {
    check(component, "file_sync")?;
    file.sync_all()
}

pub(crate) fn check(component: &str, operation: &str) -> io::Result<()> {
    let point = format!("{component}.{operation}");
    maybe_fail(&point)
}

#[cfg(any(test, feature = "qualification"))]
pub(crate) fn with_qualification_fault<R>(
    point: impl Into<String>,
    kind: io::ErrorKind,
    action: impl FnOnce() -> R,
) -> R {
    struct Reset;

    impl Drop for Reset {
        fn drop(&mut self) {
            QUALIFICATION_FAULT.with(|slot| {
                slot.replace(None);
            });
        }
    }

    QUALIFICATION_FAULT.with(|slot| {
        let previous = slot.replace(Some(QualificationFault {
            point: point.into(),
            kind,
            remaining: 1,
        }));
        assert!(
            previous.is_none(),
            "nested runtime.supervisor durability fault injection is not supported"
        );
    });
    let _reset = Reset;
    action()
}

#[cfg(any(test, feature = "qualification"))]
fn maybe_fail(point: &str) -> io::Result<()> {
    QUALIFICATION_FAULT.with(|slot| {
        let mut slot = slot.borrow_mut();
        let Some(fault) = slot.as_mut() else {
            return Ok(());
        };
        if fault.point != point || fault.remaining == 0 {
            return Ok(());
        }
        fault.remaining -= 1;
        Err(io::Error::new(
            fault.kind,
            format!("qualification fault at {point}"),
        ))
    })
}

#[cfg(not(any(test, feature = "qualification")))]
fn maybe_fail(_point: &str) -> io::Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qualification_fault_is_one_shot_and_thread_local() {
        let dir = tempfile::tempdir().expect("temporary directory");
        let path = dir.path().join("probe");
        let mut file = File::create(path).expect("probe file");
        with_qualification_fault("probe.file_write", io::ErrorKind::StorageFull, || {
            assert_eq!(
                write_all(&mut file, b"first", "probe")
                    .expect_err("injected disk full")
                    .kind(),
                io::ErrorKind::StorageFull
            );
            write_all(&mut file, b"second", "probe").expect("one-shot fault consumed");
        });
    }
}
