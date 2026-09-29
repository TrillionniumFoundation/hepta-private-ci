//! One owned UI worker and a linearized, local cancellation boundary.
//!
//! This admission is NOT a final-use grant. A task becomes non-cancellable just
//! before calling its runtime owner. Once admitted it must finish the owner's
//! durable protocol; a shutdown timeout never detaches or replays that task.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::TryLockError;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::Duration;
use std::time::Instant;

use eframe::egui;

const WAITING: u8 = 0;
const ADMITTED: u8 = 1;
const CANCELLED: u8 = 2;

#[derive(Clone)]
pub(crate) struct TaskAdmission(Arc<AtomicU8>);

impl TaskAdmission {
    /// Linearization point between cancellation and entry into a runtime owner.
    pub(crate) fn begin(&self) -> Result<(), &'static str> {
        match self
            .0
            .compare_exchange(WAITING, ADMITTED, Ordering::AcqRel, Ordering::Acquire)
        {
            Ok(_) => Ok(()),
            Err(CANCELLED) => Err("native task cancelled before runtime admission"),
            Err(_) => Err("native task admission may only be consumed once"),
        }
    }

    /// Taking the mutex is not admission: the caller must still consume begin().
    /// A cancelled or timed-out waiter never enters the runtime owner.
    pub(crate) fn wait_lock<'a, T>(
        &self,
        mutex: &'a Mutex<T>,
        maximum: Duration,
    ) -> Result<MutexGuard<'a, T>, &'static str> {
        let started = Instant::now();
        loop {
            match self.0.load(Ordering::Acquire) {
                WAITING => {}
                CANCELLED => return Err("native task cancelled before runtime admission"),
                _ => return Err("cannot wait for an owner after runtime admission"),
            }
            if started.elapsed() >= maximum {
                return Err("native runtime lock deadline exceeded before admission");
            }
            match mutex.try_lock() {
                Ok(guard) => return Ok(guard),
                Err(TryLockError::Poisoned(_)) => {
                    return Err("native runtime worker lock is poisoned");
                }
                Err(TryLockError::WouldBlock) => {
                    std::thread::sleep(
                        Duration::from_millis(2).min(maximum.saturating_sub(started.elapsed())),
                    );
                }
            }
        }
    }

    fn cancel(&self) -> bool {
        // An admitted operation is deliberately not interrupted.
        self.0
            .compare_exchange(WAITING, CANCELLED, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
    }
}

pub(crate) struct SupervisedTask<T> {
    handle: Option<JoinHandle<T>>,
    admission: TaskAdmission,
}

impl<T: Send + 'static> SupervisedTask<T> {
    pub(crate) fn spawn<F, W>(name: &str, wake: W, work: F) -> std::io::Result<Self>
    where
        F: FnOnce(TaskAdmission) -> T + Send + 'static,
        W: FnOnce() + Send + 'static,
    {
        let admission = TaskAdmission(Arc::new(AtomicU8::new(WAITING)));
        let worker_admission = admission.clone();
        let handle = std::thread::Builder::new()
            .name(name.to_owned())
            .spawn(move || {
                struct WakeOnDrop<W: FnOnce()>(Option<W>);
                impl<W: FnOnce()> Drop for WakeOnDrop<W> {
                    fn drop(&mut self) {
                        if let Some(wake) = self.0.take() {
                            wake();
                        }
                    }
                }
                let _wake = WakeOnDrop(Some(wake));
                work(worker_admission)
            })?;
        Ok(Self {
            handle: Some(handle),
            admission,
        })
    }

    /// Returns true only when this call wins before the runtime admission point.
    pub(crate) fn cancel_before_admission(&self) -> bool {
        self.admission.cancel()
    }

    /// Never blocks on an unfinished thread. A completed thread is joined once.
    pub(crate) fn poll(&mut self) -> Option<Result<T, &'static str>> {
        if !self.handle.as_ref()?.is_finished() {
            return None;
        }
        self.handle.take().map(|handle| {
            handle
                .join()
                .map_err(|_| "native worker panicked; completion is not established")
        })
    }
}

/// File inputs are routed through an explicit, single-use target identity.
///
/// A stale native-picker callback or drag/drop event cannot silently populate a
/// different field after the user cancels, switches screens, or arms a new
/// target. This state is local UI coordination; the selected file is still
/// reopened and validated by `crate::file_input` before any durable operation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum FileInputTarget {
    OperationGrant,
    UpdateManifest,
    UpdatePackage,
}

impl FileInputTarget {
    pub(crate) fn english_name(self) -> &'static str {
        match self {
            Self::OperationGrant => "signed operation grant",
            Self::UpdateManifest => "signed update manifest",
            Self::UpdatePackage => "update package",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct FileInputTicket {
    generation: u64,
    target: FileInputTarget,
}

impl FileInputTicket {
    pub(crate) fn target(self) -> FileInputTarget {
        self.target
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum FileInputError {
    GenerationExhausted,
    NoActiveIntent,
    StaleIntent,
    WrongTarget {
        expected: FileInputTarget,
        actual: FileInputTarget,
    },
    InvalidSelectionCount {
        actual: usize,
    },
    MissingFilesystemPath,
    RelativePath,
}

impl std::fmt::Display for FileInputError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::GenerationExhausted => {
                formatter.write_str("file-input generation exhausted; restart the application")
            }
            Self::NoActiveIntent => {
                formatter.write_str("arm an exact file-input target before dropping a file")
            }
            Self::StaleIntent => {
                formatter.write_str("stale file-input result rejected; arm the target again")
            }
            Self::WrongTarget { expected, actual } => write!(
                formatter,
                "file-input target mismatch: expected {}, received {}",
                expected.english_name(),
                actual.english_name()
            ),
            Self::InvalidSelectionCount { actual } => write!(
                formatter,
                "exactly one file is required for the armed target; received {actual}"
            ),
            Self::MissingFilesystemPath => formatter.write_str(
                "the dropped item has no filesystem path; in-memory or URI drops are rejected",
            ),
            Self::RelativePath => formatter.write_str("the selected file path must be absolute"),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub(crate) struct FileInputIntent {
    generation: u64,
    active: Option<FileInputTicket>,
}

impl FileInputIntent {
    pub(crate) fn arm(
        &mut self,
        target: FileInputTarget,
    ) -> Result<FileInputTicket, FileInputError> {
        self.generation = self
            .generation
            .checked_add(1)
            .ok_or(FileInputError::GenerationExhausted)?;
        let ticket = FileInputTicket {
            generation: self.generation,
            target,
        };
        self.active = Some(ticket);
        Ok(ticket)
    }

    pub(crate) fn active(&self) -> Option<FileInputTicket> {
        self.active
    }

    pub(crate) fn cancel(&mut self) -> Option<FileInputTicket> {
        self.active.take()
    }

    pub(crate) fn accept(
        &mut self,
        ticket: FileInputTicket,
        target: FileInputTarget,
        paths: &[Option<PathBuf>],
    ) -> Result<PathBuf, FileInputError> {
        let active = self.active.ok_or(FileInputError::NoActiveIntent)?;
        if active != ticket {
            return Err(FileInputError::StaleIntent);
        }
        if ticket.target != target {
            return Err(FileInputError::WrongTarget {
                expected: ticket.target,
                actual: target,
            });
        }
        if paths.len() != 1 {
            return Err(FileInputError::InvalidSelectionCount {
                actual: paths.len(),
            });
        }
        let path = paths[0]
            .as_ref()
            .ok_or(FileInputError::MissingFilesystemPath)?;
        if !path.is_absolute() {
            return Err(FileInputError::RelativePath);
        }
        self.active = None;
        Ok(path.clone())
    }
}

const FILE_INPUT_INTENT_ID: &str = "hepta-native-file-input-intent-v1";

fn mutate_file_input_intent<R>(
    context: &egui::Context,
    mutate: impl FnOnce(&mut FileInputIntent) -> R,
) -> R {
    context.data_mut(|data| {
        let id = egui::Id::new(FILE_INPUT_INTENT_ID);
        let mut intent = data.get_temp::<FileInputIntent>(id).unwrap_or_default();
        let output = mutate(&mut intent);
        data.insert_temp(id, intent);
        output
    })
}

pub(crate) fn arm_file_input(
    context: &egui::Context,
    target: FileInputTarget,
) -> Result<FileInputTicket, FileInputError> {
    mutate_file_input_intent(context, |intent| intent.arm(target))
}

pub(crate) fn active_file_input(context: &egui::Context) -> Option<FileInputTicket> {
    mutate_file_input_intent(context, |intent| intent.active())
}

pub(crate) fn cancel_file_input(context: &egui::Context) -> Option<FileInputTicket> {
    mutate_file_input_intent(context, FileInputIntent::cancel)
}

/// Accept a result from an asynchronous native picker or another callback source.
/// The adapter must retain and return the exact ticket it received when opened.
pub(crate) fn accept_file_input_result(
    context: &egui::Context,
    ticket: FileInputTicket,
    target: FileInputTarget,
    paths: &[Option<PathBuf>],
) -> Result<PathBuf, FileInputError> {
    mutate_file_input_intent(context, |intent| intent.accept(ticket, target, paths))
}

pub(crate) fn accept_active_dropped_file(
    context: &egui::Context,
    files: &[egui::DroppedFileHandle],
) -> Result<(FileInputTarget, PathBuf), FileInputError> {
    let paths = files
        .iter()
        .map(|file| Some(file.path().to_path_buf()))
        .collect::<Vec<_>>();
    let ticket = active_file_input(context).ok_or(FileInputError::NoActiveIntent)?;
    let target = ticket.target();
    let path = accept_file_input_result(context, ticket, target, &paths)?;
    Ok((target, path))
}

#[cfg(test)]
#[path = "task_supervisor_tests.rs"]
mod tests;
