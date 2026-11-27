//! Test-only, bounded observations of the unchanged real staged-bundle scan.
//!
//! One scalar summary is captured by libtest per scan. No paths, plist contents,
//! process output, or per-entry logs are retained. A dropped scan can report an
//! in-progress phase; that is not evidence that the normal return was reached.

use std::io;
use std::time::Instant;

#[derive(Clone, Copy, Debug)]
pub(super) enum Phase {
    RootMetadata,
    RootNotDirectory,
    DirectoryOpen,
    Scanning,
    Inspecting,
    EntriesExhausted,
    BundleLimit,
    ScanDeadline,
    InspectionDeadline,
}

#[derive(Clone, Copy, Debug)]
pub(super) enum IoStage {
    RootMetadata,
    DirectoryOpen,
    ReadEntry,
    EntryType,
    ExtractedMetadata,
    BundleMetadata,
}

#[derive(Clone, Copy, Debug)]
enum IoKind {
    NotFound,
    PermissionDenied,
    Other,
}

pub(super) struct ScanObservation {
    started: Instant,
    pub(super) phase: Phase,
    pub(super) entries: u64,
    pub(super) inspected: u64,
    io_errors: u64,
    last_io_error: Option<(IoStage, IoKind, Option<i32>)>,
    pub(super) inspection_errors: u64,
    pub(super) identity_misses: u64,
    pub(super) not_newer: u64,
    pub(super) newer: u64,
    last_inspection_ms: u128,
    max_inspection_ms: u128,
    tail_reached: bool,
    latest: Option<u64>,
}

impl ScanObservation {
    pub(super) fn new() -> Self {
        Self {
            started: Instant::now(),
            phase: Phase::RootMetadata,
            entries: 0,
            inspected: 0,
            io_errors: 0,
            last_io_error: None,
            inspection_errors: 0,
            identity_misses: 0,
            not_newer: 0,
            newer: 0,
            last_inspection_ms: 0,
            max_inspection_ms: 0,
            tail_reached: false,
            latest: None,
        }
    }

    pub(super) fn observe_io<T>(&mut self, stage: IoStage, result: &io::Result<T>) {
        if let Err(error) = result {
            self.io_errors = self.io_errors.saturating_add(1);
            let kind = match error.kind() {
                io::ErrorKind::NotFound => IoKind::NotFound,
                io::ErrorKind::PermissionDenied => IoKind::PermissionDenied,
                _ => IoKind::Other,
            };
            self.last_io_error = Some((stage, kind, error.raw_os_error()));
        }
    }

    pub(super) fn inspection_finished(&mut self, started: Instant) {
        self.last_inspection_ms = started.elapsed().as_millis();
        self.max_inspection_ms = self.max_inspection_ms.max(self.last_inspection_ms);
        self.phase = Phase::Scanning;
    }

    pub(super) fn finish(&mut self, latest: Option<u64>) {
        if matches!(self.phase, Phase::Scanning) {
            self.phase = Phase::EntriesExhausted;
        }
        self.tail_reached = true;
        self.latest = latest;
    }
}

impl Drop for ScanObservation {
    fn drop(&mut self) {
        eprintln!(
            "staged-scan phase={:?} tail_reached={} entries={} inspected={} io_errors={} last_io={:?} inspection_errors={} identity_misses={} not_newer={} newer={} latest={:?} elapsed_ms={} last_inspection_ms={} max_inspection_ms={}",
            self.phase,
            self.tail_reached,
            self.entries,
            self.inspected,
            self.io_errors,
            self.last_io_error,
            self.inspection_errors,
            self.identity_misses,
            self.not_newer,
            self.newer,
            self.latest,
            self.started.elapsed().as_millis(),
            self.last_inspection_ms,
            self.max_inspection_ms,
        );
    }
}
