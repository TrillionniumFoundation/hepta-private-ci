//! Test-only, process-relative monotonic measurement for the two original Q24 cases.
use std::cell::Cell;
use std::io::Write;

use std::time::Instant;

thread_local! {
    static CASE: Cell<Option<&'static str>> = const { Cell::new(None) };
}

pub(crate) fn case() -> Option<&'static str> {
    CASE.get().or_else(|| {
        let t = std::thread::current();
        match t.name()?.rsplit("::").next()? {
            "original_next_use_evidence_timing_diagnostic" => Some("timing"),
            "q24_next_use_command_healthy_evidence_readback_then_publication_withdrawal" => Some("healthy"),
            _ => None,
        }
    })
}

pub(crate) fn inherit<F: FnOnce() -> T, T>(f: F) -> impl FnOnce() -> T {
    let label = case();
    move || {
        CASE.set(label);
        f()
    }
}

fn us() -> u64 {
    codex_hepta_contracts::q24_clock_observer::micros(Instant::now())
}

pub(crate) struct Span {
    label: Option<&'static str>,
    layer: &'static str,
    tag: u64,
    points: Vec<(&'static str, u64)>,
    clock_bound: Option<(&'static str,u64)>,
}

impl Span {
    pub(crate) fn new(layer: &'static str, tag: u64) -> Self {
        Self::from_ticket(layer, (case(), tag))
    }

    pub(crate) fn ticket(&self, tag: u64) -> (Option<&'static str>, u64) {
        (self.label, tag)
    }

    pub(crate) fn from_ticket(layer: &'static str, ticket: (Option<&'static str>, u64)) -> Self {
        let mut this = Self { label: ticket.0, layer, tag: ticket.1, points: Vec::new(), clock_bound: None };
        this.mark("start");
        this
    }

    pub(crate) fn bound(&mut self, deadline: Instant, end: Instant) {
        self.clock_bound=Some((if deadline==end {"lifetime"} else {"per_request"},codex_hepta_contracts::q24_clock_observer::micros(deadline)));
    }
    pub(crate) fn mark(&mut self, name: &'static str) {
        if self.label.is_some() {
            self.points.push((name, us()));
        }
    }
}

impl Drop for Span {
    fn drop(&mut self) {
        if let Some(label) = self.label {
            self.mark("end");
            let mut line = format!("\nQ24_STAGE case={label} pid={} thread={:?} layer={} tag={}",
                std::process::id(), std::thread::current().id(), self.layer, self.tag);
            for (name, stamp) in &self.points {
                use std::fmt::Write as _;
                let _ = write!(line, " {name}={stamp}");
            }
            line.push('\n');
            if let Some((kind,deadline))=self.clock_bound {
                use std::fmt::Write as _;
                let _=writeln!(line,"Q24_BOUND case={label} pid={} thread={:?} layer={} tag={} start={} bound={kind} deadline={deadline}",std::process::id(), std::thread::current().id(),self.layer,self.tag,self.points[0].1);
            }
            let _ = std::io::stderr().lock().write_all(line.as_bytes());
        }
    }
}
