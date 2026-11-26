//! Poll-scoped, test-only observation of the two real process-launch tokens.

use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;
use std::cell::Cell;
use std::future::Future;
use std::future::poll_fn;
use std::io::Write;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::rc::Rc;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::System::Threading::OpenProcessToken;

#[path = "legacy_spawn_token_facts_tests.rs"]
mod facts;
use facts::Facts;

const LOG_BYTES: usize = 16 * 1024;
const PREFIX: &str = "HEPTA_LEGACY_SPAWN_TOKEN ";

struct Capture {
    launch: Result<Facts>,
    child: Result<Facts>,
}

#[derive(Default)]
struct Observation {
    polls: Cell<usize>,
    hits: Cell<usize>,
    overlap: Cell<bool>,
    capture: Cell<Option<Capture>>,
}

thread_local! {
    static ACTIVE: Cell<Option<Rc<Observation>>> = const { Cell::new(None) };
}

struct PollScope {
    previous: Option<Rc<Observation>>,
}

impl PollScope {
    fn enter(observation: &Rc<Observation>) -> Self {
        let previous = ACTIVE.with(|slot| slot.replace(Some(Rc::clone(observation))));
        if let Some(previous) = &previous {
            previous.overlap.set(true);
            observation.overlap.set(true);
        }
        Self { previous }
    }
}

impl Drop for PollScope {
    fn drop(&mut self) {
        ACTIVE.with(|slot| slot.set(self.previous.take()));
    }
}

fn actual_child_token(process: HANDLE) -> Result<Facts> {
    let mut raw = 0;
    ensure!(
        unsafe { OpenProcessToken(process, TOKEN_QUERY, &mut raw) } != 0,
        "OpenProcessToken(TOKEN_QUERY): {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        raw != 0 && raw != INVALID_HANDLE_VALUE,
        "OpenProcessToken returned invalid handle"
    );
    let token = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    Facts::capture(token.as_raw_handle() as _)
}

pub(crate) fn observe_created_process(launch_token: HANDLE, process: HANDLE) {
    let observation = ACTIVE.with(|slot| {
        let saved = slot.take();
        let observation = saved.clone();
        slot.set(saved);
        observation
    });
    let Some(observation) = observation else {
        return;
    };
    observation
        .hits
        .set(observation.hits.get().saturating_add(1));
    if observation.hits.get() == 1 {
        // The existing handles remain owned by the original launch path. Only
        // the additional TOKEN_QUERY handle is owned and closed here.
        observation.capture.set(Some(Capture {
            launch: Facts::capture(launch_token),
            child: actual_child_token(process),
        }));
    }
}

fn token_report(result: &Result<Facts>) -> Value {
    match result {
        Ok(facts) => json!({"status": "observed", "facts": facts.summary()}),
        Err(error) => {
            let mut error = error.to_string();
            let end = error.floor_char_boundary(256);
            error.truncate(end);
            json!({"status": "unknown", "error": error})
        }
    }
}

impl Observation {
    fn report(&self) {
        let capture = self.capture.take();
        let complete = self.hits.get() == 1
            && !self.overlap.get()
            && capture
                .as_ref()
                .is_some_and(|capture| capture.launch.is_ok() && capture.child.is_ok());
        let (launch, child, comparison) = match capture {
            Some(capture) => {
                let comparison = match (&capture.launch, &capture.child) {
                    (Ok(launch), Ok(child)) => child.compare(launch),
                    _ => Value::Null,
                };
                (
                    token_report(&capture.launch),
                    token_report(&capture.child),
                    comparison,
                )
            }
            None => (
                json!({"status": "unknown", "reason": "no_hook_capture"}),
                json!({"status": "unknown", "reason": "no_hook_capture"}),
                Value::Null,
            ),
        };
        let record = json!({"status": if complete { "observed" } else { "unknown" },
            "poll_count": self.polls.get(), "hook_count": self.hits.get(), "overlapping_scope": self.overlap.get(),
            "launch_input": launch, "actual_child_primary": child, "comparison": comparison});
        let encoded = serde_json::to_vec(&record);
        let bytes = match &encoded {
            Ok(bytes) if PREFIX.len() + bytes.len() < LOG_BYTES => bytes.as_slice(),
            _ => br#"{"status":"unknown","reason":"serialization_or_log_bound"}"#,
        };
        let mut stderr = std::io::stderr().lock();
        let _ = stderr.write_all(PREFIX.as_bytes());
        let _ = stderr.write_all(bytes);
        let _ = stderr.write_all(b"\n");
    }
}

pub(crate) async fn observe_spawn<F: Future>(future: F) -> F::Output {
    let observation = Rc::new(Observation::default());
    let mut future = std::pin::pin!(future);
    let output = poll_fn(|context| {
        observation
            .polls
            .set(observation.polls.get().saturating_add(1));
        let scope = PollScope::enter(&observation);
        let result = future.as_mut().poll(context);
        // No thread-local registration survives either Pending or Ready.
        drop(scope);
        result
    })
    .await;
    observation.report();
    output
}
