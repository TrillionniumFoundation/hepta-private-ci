//! Private-build observations for one existing evidence test, never authority.
//!
//! Call sites exist only under `hepta_ci_phase_diagnostic`. Events and channel
//! links are bounded and use try_lock: losing an observation marks the trace
//! incomplete without waiting or changing the observed operation's result.
//! Thread context is restored after every future poll, not held across await.

use serde::Deserialize;
use serde::Serialize;
use std::cell::Cell;
use std::future::Future;
use std::io::Write;
use std::marker::PhantomData;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixStream;
use std::pin::Pin;
use std::rc::Rc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::task::Context as TaskContext;
use std::task::Poll;
use std::time::Instant;

const EVENTS: usize = 32_768;
const ENDPOINTS: usize = 256;
const LINKS: usize = 4_096;

/// Private diagnostic expansion; ordinary call sites use a local identity macro.
#[macro_export]
macro_rules! phase_observe {
    (sync, $phase:literal, $value:expr) => {
        $crate::phase_diagnostic::sync($phase, || $value)
    };
    (future, $phase:literal, $value:expr) => {
        $crate::phase_diagnostic::future($phase, $value)
    };
    (future_at, $context:expr, $phase:literal, $value:expr) => {
        $crate::phase_diagnostic::future_at($context, $phase, $value)
    };
}

#[derive(Clone, Copy, Default, Serialize)]
pub struct Context {
    case: u64,
    connection: u64,
    request: u64,
    span: u64,
}

#[derive(Clone, Copy, Default)]
pub struct Endpoint {
    case: u64,
    connection: u64,
}

#[derive(Serialize)]
struct Event {
    context: Context,
    parent: Context,
    thread: u64,
    phase: &'static str,
    start_ns: u64,
    end_ns: u64,
    returned: bool,
    value: u64,
}

struct Recorder {
    origin: Instant,
    next: AtomicU64,
    lost: AtomicU64,
    cleanup: AtomicBool,
    recording: AtomicBool,
    events: Mutex<Vec<Event>>,
    endpoints: Mutex<Vec<(i32, Endpoint)>>,
    links: Mutex<Vec<(u64, u64, Context)>>,
}

static RECORDER: OnceLock<Recorder> = OnceLock::new();
thread_local! {
    static CURRENT: Cell<Context> = const { Cell::new(Context { case: 0, connection: 0, request: 0, span: 0 }) };
    static THREAD: Cell<u64> = const { Cell::new(/*value*/ 0) };
}

fn lost() {
    if let Some(recorder) = RECORDER.get() {
        recorder.lost.fetch_add(/*val*/ 1, Ordering::Relaxed);
    }
}

fn next() -> u64 {
    RECORDER.get().map_or(/*default*/ 0, |recorder| {
        recorder.next.fetch_add(/*val*/ 1, Ordering::Relaxed)
    })
}

fn stamp() -> u64 {
    RECORDER.get().map_or(/*default*/ 0, |recorder| {
        u64::try_from(recorder.origin.elapsed().as_nanos()).unwrap_or(u64::MAX)
    })
}

pub fn capture() -> Context {
    CURRENT.with(Cell::get)
}

pub struct Enter {
    previous: Context,
    // A thread-local guard must never cross an await or a thread boundary.
    thread_only: PhantomData<Rc<()>>,
}

pub fn enter(context: Context) -> Enter {
    Enter {
        previous: CURRENT.with(|current| current.replace(context)),
        thread_only: PhantomData,
    }
}

impl Drop for Enter {
    fn drop(&mut self) {
        CURRENT.with(|current| current.set(self.previous));
    }
}

/// Register the two actually paired fixture descriptors before either moves.
/// Descriptor values stay inside this private map and are never emitted.
pub fn register_pair(client: &UnixStream, server: &UnixStream) {
    let context = capture();
    if context.case == 0 {
        return;
    }
    let Some(recorder) = RECORDER.get() else {
        return;
    };
    let endpoint = Endpoint {
        case: context.case,
        connection: next(),
    };
    let Ok(mut endpoints) = recorder.endpoints.try_lock() else {
        lost();
        return;
    };
    if endpoints.len() + 2 > ENDPOINTS
        || endpoints
            .iter()
            .any(|(fd, _)| *fd == client.as_raw_fd() || *fd == server.as_raw_fd())
    {
        lost();
        return;
    }
    endpoints.push((client.as_raw_fd(), endpoint));
    endpoints.push((server.as_raw_fd(), endpoint));
}

pub fn take_endpoint(stream: &UnixStream) -> Endpoint {
    let Some(recorder) = RECORDER.get() else {
        return Endpoint::default();
    };
    let Ok(mut endpoints) = recorder.endpoints.try_lock() else {
        lost();
        return Endpoint::default();
    };
    endpoints
        .iter()
        .position(|(fd, _)| *fd == stream.as_raw_fd())
        .map(|index| endpoints.swap_remove(index).1)
        .unwrap_or_default()
}

#[derive(Deserialize)]
struct RequestOrdinal {
    request_id: u64,
}

impl Endpoint {
    pub fn waiting(self) -> Context {
        Context {
            case: self.case,
            connection: self.connection,
            request: 0,
            span: capture().span,
        }
    }

    /// Read only the existing ordinal from the already encoded original frame.
    /// Missing/invalid correlation disables this observation, never the request.
    pub fn request_bytes(self, bytes: &[u8], sender: bool) -> Context {
        if self.case == 0 {
            return Context::default();
        }
        let Ok(request) = serde_json::from_slice::<RequestOrdinal>(bytes) else {
            lost();
            return Context::default();
        };
        self.request(request.request_id, sender)
    }

    pub fn request(self, request: u64, sender: bool) -> Context {
        if self.case == 0 || !(1..=128).contains(&request) {
            if self.case != 0 {
                lost();
            }
            return Context::default();
        }
        let mut parent = capture();
        let Some(recorder) = RECORDER.get() else {
            return Context::default();
        };
        if let Ok(mut links) = recorder.links.try_lock() {
            if sender {
                if !links.iter().any(|(connection, ordinal, _)| {
                    *connection == self.connection && *ordinal == request
                }) {
                    if links.len() == LINKS {
                        lost();
                    } else {
                        links.push((self.connection, request, parent));
                    }
                }
            } else if let Some((_, _, original)) = links.iter().find(|(connection, ordinal, _)| {
                *connection == self.connection && *ordinal == request
            }) {
                parent = *original;
            } else {
                lost();
            }
        } else {
            lost();
        }
        let context = Context {
            case: self.case,
            connection: self.connection,
            request,
            span: next(),
        };
        Timer {
            context,
            parent,
            phase: if sender {
                "channel.sender_link"
            } else {
                "channel.receiver_link"
            },
            start: stamp(),
            done: false,
            value: 0,
            active: recorder.recording.load(Ordering::Relaxed),
        }
        .finish();
        context
    }
}

/// A timer does not install thread context and may cross a blocking-task move.
pub struct Timer {
    context: Context,
    parent: Context,
    phase: &'static str,
    start: u64,
    done: bool,
    value: u64,
    active: bool,
}

pub fn timer_at(parent: Context, phase: &'static str) -> Timer {
    Timer {
        context: Context {
            span: if parent.case == 0 { 0 } else { next() },
            ..parent
        },
        parent,
        phase,
        start: stamp(),
        done: false,
        value: 0,
        active: RECORDER
            .get()
            .is_some_and(|recorder| recorder.recording.load(Ordering::Relaxed)),
    }
}

pub fn timer(phase: &'static str) -> Timer {
    timer_at(capture(), phase)
}

impl Timer {
    pub fn context(&self) -> Context {
        self.context
    }

    pub fn finish(mut self) {
        self.record(/*returned*/ true);
    }

    pub fn correlate(&mut self, request: Context) {
        self.context.case = request.case;
        self.context.connection = request.connection;
        self.context.request = request.request;
    }

    fn record(&mut self, returned: bool) {
        let end_ns = stamp();
        if self.done || self.context.case == 0 || !self.active {
            self.done = true;
            return;
        }
        self.done = true;
        let Some(recorder) = RECORDER.get() else {
            return;
        };
        let thread = THREAD.with(|thread| {
            let value = thread.get();
            if value != 0 {
                value
            } else {
                let value = next();
                thread.set(value);
                value
            }
        });
        let Ok(mut events) = recorder.events.try_lock() else {
            lost();
            return;
        };
        if events.len() == EVENTS {
            lost();
            return;
        }
        events.push(Event {
            context: self.context,
            parent: self.parent,
            thread,
            phase: self.phase,
            start_ns: self.start,
            end_ns,
            returned,
            value: self.value,
        });
    }
}

impl Drop for Timer {
    fn drop(&mut self) {
        self.record(/*returned*/ false);
    }
}

pub struct Scope {
    timer: Option<Timer>,
    _entered: Enter,
}

pub fn scope(phase: &'static str) -> Scope {
    let timer = timer(phase);
    Scope {
        _entered: enter(timer.context()),
        timer: Some(timer),
    }
}

impl Scope {
    pub fn finish(mut self) {
        if let Some(timer) = self.timer.take() {
            timer.finish();
        }
    }
}

/// Evaluate once, return the identical value, and restore context before return.
pub fn sync<T>(phase: &'static str, body: impl FnOnce() -> T) -> T {
    let measured = scope(phase);
    let result = body();
    measured.finish();
    result
}

/// No added Send/Clone/Unpin bound. Each outer poll delegates exactly one poll.
pub struct Timed<F> {
    future: Pin<Box<F>>,
    timer: Option<Timer>,
    context: Context,
}

pub fn future_at<F: Future>(context: Context, phase: &'static str, future: F) -> Timed<F> {
    let timer = timer_at(context, phase);
    Timed {
        future: Box::pin(future),
        context: timer.context(),
        timer: Some(timer),
    }
}

pub fn future<F: Future>(phase: &'static str, future: F) -> Timed<F> {
    future_at(capture(), phase, future)
}

impl<F: Future> Future for Timed<F> {
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, task: &mut TaskContext<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let _entered = enter(this.context);
        let result = this.future.as_mut().poll(task);
        if result.is_ready()
            && let Some(timer) = this.timer.take()
        {
            timer.finish();
        }
        result
    }
}

pub fn cleanup_complete() {
    if let Some(recorder) = RECORDER.get() {
        recorder.cleanup.store(/*val*/ true, Ordering::Relaxed);
    }
}

pub fn begin_measurement() {
    if let Some(recorder) = RECORDER.get() {
        recorder.recording.store(/*val*/ true, Ordering::Relaxed);
        let mut root = timer("measurement_root");
        root.context = capture();
        root.parent = Context::default();
        root.finish();
    }
}

pub fn deadline(phase: &'static str, deadline: Instant) {
    let Some(recorder) = RECORDER.get() else {
        return;
    };
    let mut event = timer(phase);
    event.value = u64::try_from(
        deadline
            .saturating_duration_since(recorder.origin)
            .as_nanos(),
    )
    .unwrap_or(u64::MAX);
    event.finish();
}

struct Flush;

impl Drop for Flush {
    fn drop(&mut self) {
        let Some(recorder) = RECORDER.get() else {
            return;
        };
        let mut stderr = std::io::stderr().lock();
        let Ok(events) = recorder.events.try_lock() else {
            let _ = writeln!(stderr, "HEPTA_PHASE_TRACE_INCOMPLETE recorder_busy");
            return;
        };
        let mut written = 0;
        for event in events.iter() {
            if write!(stderr, "HEPTA_PHASE_EVENT ").is_err()
                || serde_json::to_writer(&mut stderr, event).is_err()
                || writeln!(stderr).is_err()
            {
                return;
            }
            written += 1;
        }
        let _ = writeln!(
            stderr,
            "HEPTA_PHASE_TRACE_END events={written} lost={} cleanup_complete={}",
            recorder.lost.load(Ordering::Relaxed),
            recorder.cleanup.load(Ordering::Relaxed)
        );
    }
}

pub async fn run_case<F: Future>(case: u64, body: F) -> F::Output {
    let recorder = Recorder {
        origin: Instant::now(),
        next: AtomicU64::new(/*v*/ 1),
        lost: AtomicU64::new(/*v*/ 0),
        cleanup: AtomicBool::new(/*v*/ false),
        recording: AtomicBool::new(/*v*/ false),
        events: Mutex::new(Vec::with_capacity(EVENTS)),
        endpoints: Mutex::new(Vec::with_capacity(ENDPOINTS)),
        links: Mutex::new(Vec::with_capacity(LINKS)),
    };
    if RECORDER.set(recorder).is_err() {
        lost();
    }
    let _flush = Flush;
    future_at(
        Context {
            case,
            ..Context::default()
        },
        "case",
        body,
    )
    .await
}
