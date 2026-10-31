//! Bounded, opt-in lifecycle evidence that survives an unfinished libtest capture.
//! This module is compiled only for unit tests and records no conversation content.

use codex_protocol::ThreadId;
use std::collections::HashMap;
use std::fmt::Arguments;
use std::io::Write;
use std::sync::LazyLock;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::time::Instant;

const MAX_RECORDS_PER_THREAD: usize = 128;

struct Trace {
    started: Instant,
    subscribers: usize,
    remaining: usize,
}

static TRACES: LazyLock<Mutex<HashMap<ThreadId, Trace>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

pub(crate) struct Subscription {
    thread_id: ThreadId,
}

pub(crate) fn subscribe(thread_id: ThreadId) -> Subscription {
    let mut traces = TRACES.lock().unwrap_or_else(PoisonError::into_inner);
    let trace = traces.entry(thread_id).or_insert_with(|| Trace {
        started: Instant::now(),
        subscribers: 0,
        remaining: MAX_RECORDS_PER_THREAD,
    });
    trace.subscribers += 1;
    Subscription { thread_id }
}

impl Drop for Subscription {
    fn drop(&mut self) {
        let mut traces = TRACES.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(trace) = traces.get_mut(&self.thread_id) {
            trace.subscribers -= 1;
            if trace.subscribers == 0 {
                traces.remove(&self.thread_id);
            }
        }
    }
}

pub(crate) fn record(thread_id: ThreadId, event: Arguments<'_>) {
    record_to(thread_id, event, &mut std::io::stderr());
}

fn record_to(thread_id: ThreadId, event: Arguments<'_>, writer: &mut impl Write) {
    let (sequence, elapsed_ms) = {
        let mut traces = TRACES.lock().unwrap_or_else(PoisonError::into_inner);
        let Some(trace) = traces.get_mut(&thread_id) else {
            return;
        };
        if trace.remaining == 0 {
            return;
        }
        trace.remaining -= 1;
        (
            MAX_RECORDS_PER_THREAD - trace.remaining,
            trace.started.elapsed().as_millis(),
        )
    };
    // Never hold the registry lock while writing or turn an I/O error in this
    // diagnostic into a change to the lifecycle being observed.
    let _ = writeln!(
        writer,
        "lifecycle diagnostic: thread={thread_id} seq={sequence} elapsed_ms={elapsed_ms} {event}"
    );
}

#[cfg(test)]
#[path = "lifecycle_test_diagnostics_tests.rs"]
mod tests;
