//! Test-only timing for the unchanged original federation path. No grants,
//! paths, payloads or database contents are recorded. Only failing product
//! attempts emit the bounded retained trace; successful I/O has no log output.

use std::collections::BTreeMap;
use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

const MAX_EVENTS: usize = 4096;

tokio::task_local! {
    static ACTIVE: Arc<Trace>;
}

#[derive(serde::Serialize)]
struct Event {
    phase: &'static str,
    owner: String,
    stage: &'static str,
    elapsed_us: u128,
}

#[derive(Default)]
struct State {
    events: Vec<Event>,
    authority_calls: BTreeMap<String, u32>,
    omitted_events: u64,
}

pub(crate) struct Trace {
    started: Instant,
    state: Mutex<State>,
}

impl Trace {
    pub(crate) fn new() -> Arc<Self> {
        Arc::new(Self {
            started: Instant::now(),
            state: Mutex::new(State::default()),
        })
    }

    fn record(&self, phase: &'static str, owner: &str, stage: &'static str) {
        let Ok(mut state) = self.state.lock() else {
            return;
        };
        if state.events.len() >= MAX_EVENTS {
            state.omitted_events = state.omitted_events.saturating_add(1);
            return;
        }
        state.events.push(Event {
            phase,
            owner: owner.into(),
            stage,
            elapsed_us: self.started.elapsed().as_micros(),
        });
    }

    fn authority_phase(&self, capability: &str) -> &'static str {
        let Ok(mut state) = self.state.lock() else {
            return "authority_lock_unavailable";
        };
        let count = state.authority_calls.entry(capability.into()).or_default();
        *count = count.saturating_add(1);
        match *count {
            1 => "preflight_authority",
            2 => "post_io_authority",
            _ => "additional_authority_call",
        }
    }

    pub(crate) fn emit_failure(&self, outcome: &str, budget_ms: u128) {
        let Ok(state) = self.state.lock() else {
            eprintln!("HEPTA_FEDERATION_PHASES_V1 trace_lock_unavailable");
            return;
        };
        eprintln!(
            "HEPTA_FEDERATION_PHASES_V1 {}",
            serde_json::json!({
                "schema_version":1,"elapsed_us":self.started.elapsed().as_micros(),
                "budget_ms":budget_ms,"outcome":outcome,"omitted_events":state.omitted_events,
                "events":state.events,
            })
        );
    }
}

pub(crate) async fn capture<T>(trace: Arc<Trace>, future: impl Future<Output = T>) -> T {
    ACTIVE.scope(trace, future).await
}

pub(crate) struct Phase {
    trace: Option<Arc<Trace>>,
    phase: &'static str,
    owner: String,
    completed: bool,
}

impl Phase {
    pub(crate) fn start(phase: &'static str, owner: &str) -> Self {
        let trace = ACTIVE.try_with(Arc::clone).ok();
        let owner = if trace.is_some() {
            owner.to_owned()
        } else {
            String::new()
        };
        if let Some(trace) = &trace {
            trace.record(phase, &owner, "start");
        }
        Self {
            trace,
            phase,
            owner,
            completed: false,
        }
    }

    pub(crate) fn authority(owner: &str, capability: &str) -> Self {
        let phase = ACTIVE
            .try_with(|trace| trace.authority_phase(capability))
            .unwrap_or("authority");
        Self::start(phase, owner)
    }

    pub(crate) fn stage(&self, stage: &'static str) {
        if let Some(trace) = &self.trace {
            trace.record(self.phase, &self.owner, stage);
        }
    }

    pub(crate) fn finish(&mut self) {
        self.stage("end");
        self.completed = true;
    }
}

impl Drop for Phase {
    fn drop(&mut self) {
        if !self.completed {
            self.stage("cancelled_or_returned_error");
        }
    }
}
