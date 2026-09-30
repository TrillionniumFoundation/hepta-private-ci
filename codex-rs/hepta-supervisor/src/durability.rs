//! Shared durability primitives and qualification-only fault injection.
//!
//! Product builds always execute the real filesystem operation. The injector
//! exists only in unit tests or when the explicit `qualification` feature is
//! enabled. It is thread-local, one-shot, and cannot affect unrelated writers.

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
    successful_occurrences: u32,
}

#[cfg(any(test, feature = "qualification"))]
thread_local! {
    static QUALIFICATION_FAULT: RefCell<Option<QualificationFault>> = const { RefCell::new(None) };
}

pub(crate) fn write_all(file: &mut File, bytes: &[u8], component: &str) -> io::Result<()> {
    check(component, "file_write")?;
    file.write_all(bytes)
}

pub(crate) fn sync_all(file: &File, component: &str) -> io::Result<()> {
    check(component, "file_sync")?;
    file.sync_all()
}

pub(crate) fn check(component: &str, operation: &str) -> io::Result<()> {
    maybe_fail(&format!("{component}.{operation}"))
}

#[cfg(test)]
pub(crate) fn with_qualification_fault<R>(
    point: impl Into<String>,
    kind: io::ErrorKind,
    action: impl FnOnce() -> R,
) -> R {
    with_qualification_fault_after(point, kind, /*successful_occurrences*/ 0, action)
}

#[cfg(test)]
pub(crate) fn with_qualification_fault_after<R>(
    point: impl Into<String>,
    kind: io::ErrorKind,
    successful_occurrences: u32,
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
            successful_occurrences,
        }));
        assert!(previous.is_none(), "nested durability fault injection");
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
        if fault.successful_occurrences > 0 {
            fault.successful_occurrences -= 1;
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
    fn injected_disk_full_is_one_shot() {
        let dir = tempfile::tempdir().expect("temporary directory");
        let mut file = File::create(dir.path().join("probe")).expect("probe file");
        with_qualification_fault("probe.file_write", io::ErrorKind::StorageFull, || {
            assert_eq!(
                write_all(&mut file, b"first", "probe")
                    .expect_err("disk full")
                    .kind(),
                io::ErrorKind::StorageFull
            );
            write_all(&mut file, b"second", "probe").expect("fault consumed");
        });
    }
}
