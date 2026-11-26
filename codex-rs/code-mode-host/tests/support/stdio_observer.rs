//! Observe existing stderr-forwarding events without changing the handshake.
//!
//! The subscriber is process-wide so spawned Tokio tasks remain observable.
//! Events may belong to any concurrent case: this is not a per-test transcript.
//! Only the first panicking case emits a report, bounded to 4,096 bytes. Missing
//! events do not establish empty stderr, child liveness, or a completed phase.

use std::fmt;
use std::fmt::Write as _;
use std::io::Write as _;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use tracing::Event;
use tracing::Metadata;
use tracing::field::Field;
use tracing::field::Visit;
use tracing_subscriber::Layer;
use tracing_subscriber::Registry;
use tracing_subscriber::layer::Context;
use tracing_subscriber::layer::SubscriberExt;

const TARGET: &str = "codex_code_mode::remote_session::connection";
const CAPTURE_BYTES: usize = 4096;
const EVENT_BYTES: usize = 1024;
const REPORT_BYTES: usize = 4096;
static OBSERVER: OnceLock<Observer> = OnceLock::new();

struct BoundedText {
    text: String,
    limit: usize,
    truncated: bool,
}

impl BoundedText {
    fn new(limit: usize) -> Self {
        Self {
            text: String::with_capacity(limit),
            limit,
            truncated: false,
        }
    }
}

impl fmt::Write for BoundedText {
    fn write_str(&mut self, text: &str) -> fmt::Result {
        let mut bytes = text.len().min(self.limit - self.text.len());
        while !text.is_char_boundary(bytes) {
            bytes -= 1;
        }
        self.text.push_str(&text[..bytes]);
        if bytes == text.len() {
            Ok(())
        } else {
            self.truncated = true;
            Err(fmt::Error)
        }
    }
}

struct Message(BoundedText);

impl Visit for Message {
    fn record_debug(&mut self, field: &Field, value: &dyn fmt::Debug) {
        if field.name() == "message" {
            let _ = write!(self.0, "{value:?}");
        }
    }

    fn record_str(&mut self, field: &Field, value: &str) {
        if field.name() == "message" {
            let _ = self.0.write_str(value);
        }
    }
}

struct Capture {
    text: Mutex<BoundedText>,
    seen: AtomicBool,
    contended: AtomicBool,
    emitted: AtomicBool,
}

struct StderrLayer(Arc<Capture>);

impl Layer<Registry> for StderrLayer {
    fn enabled(&self, metadata: &Metadata<'_>, _context: Context<'_, Registry>) -> bool {
        metadata.is_event() && metadata.target() == TARGET
    }

    fn on_event(&self, event: &Event<'_>, _context: Context<'_, Registry>) {
        let mut message = Message(BoundedText::new(EVENT_BYTES));
        event.record(&mut message);
        if !message.0.text.starts_with("code-mode host stderr: ")
            && !message
                .0
                .text
                .starts_with("failed to read code-mode host stderr: ")
        {
            return;
        }
        self.0.seen.store(true, Ordering::Relaxed);
        if let Ok(mut text) = self.0.text.try_lock() {
            text.truncated |= message.0.truncated;
            let _ = writeln!(text, "{}", message.0.text);
        } else {
            self.0.contended.store(true, Ordering::Relaxed);
        }
    }
}

struct Observer {
    capture: Arc<Capture>,
    installed: bool,
}

impl Observer {
    fn install() -> Self {
        let capture = Arc::new(Capture {
            text: Mutex::new(BoundedText::new(CAPTURE_BYTES)),
            seen: AtomicBool::new(false),
            contended: AtomicBool::new(false),
            emitted: AtomicBool::new(false),
        });
        let subscriber = tracing_subscriber::registry().with(StderrLayer(Arc::clone(&capture)));
        // Never replace another subscriber. A conflict remains an unavailable
        // observation and does not change the original test result.
        let installed = tracing::subscriber::set_global_default(subscriber).is_ok();
        Self { capture, installed }
    }
}

/// Keep this guard alive for the original test, including its existing awaits.
pub(crate) struct FailureObservation;

pub(crate) fn observe_process_stderr() -> FailureObservation {
    OBSERVER.get_or_init(Observer::install);
    FailureObservation
}

impl Drop for FailureObservation {
    fn drop(&mut self) {
        if !std::thread::panicking() {
            return;
        }
        let Some(observer) = OBSERVER.get() else {
            return;
        };
        if observer.capture.emitted.swap(true, Ordering::Relaxed) {
            return;
        }
        // Reserve the last byte for a newline even if escaped text expands.
        let mut report = BoundedText::new(REPORT_BYTES - 1);
        let _ = write!(
            report,
            "stdio stderr observation scope=process case_attribution=unavailable installed={} matching_event_seen={} contention_or_poison={} absence_is_not_empty_stderr=true ",
            observer.installed,
            observer.capture.seen.load(Ordering::Relaxed),
            observer.capture.contended.load(Ordering::Relaxed),
        );
        if let Ok(text) = observer.capture.text.try_lock() {
            let _ = write!(
                report,
                "capture_truncated={} captured_prefix={:?}",
                text.truncated, text.text,
            );
        } else {
            let _ = report.write_str("capture_unavailable=true");
        }
        report.text.push('\n');
        // Failure-only, bounded output. An unavailable stderr must not replace
        // the original panic. No child handle, pipe reader, or deadline is added.
        let _ = std::io::stderr().write_all(report.text.as_bytes());
    }
}
