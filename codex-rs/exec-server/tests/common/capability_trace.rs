//! Opt-in child observation of existing request and discovery span lifetimes.
//! Only fixed labels and numeric fields reach the inherited stderr. A close is
//! not proof of socket delivery, and a missing close does not identify a helper.

use std::fmt;
use std::io::Write as _;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Instant;

use tracing::Metadata;
use tracing::field::Field;
use tracing::field::Visit;
use tracing::span::Attributes;
use tracing::span::Id;
use tracing::span::Record;
use tracing_subscriber::Layer;
use tracing_subscriber::Registry;
use tracing_subscriber::layer::Context;

const LINE_BYTES: usize = 256;
const MAX_RECORDS: usize = 32;

#[derive(Default)]
pub(super) struct DiscoveryTrace {
    records: AtomicUsize,
}

#[derive(Clone, Copy)]
struct Observation {
    kind: &'static str,
    method: &'static str,
    result: &'static str,
    roots: Option<u64>,
    started: Instant,
}

impl Visit for Observation {
    fn record_u64(&mut self, field: &Field, value: u64) {
        if field.name() == "root_count" {
            self.roots = Some(value);
        }
    }

    fn record_str(&mut self, field: &Field, value: &str) {
        match field.name() {
            "method" => {
                self.method = match value {
                    "initialize" => "initialize",
                    "capabilityRoots/discoverV1" => "discover",
                    _ => "other",
                };
            }
            "result" => {
                self.result = match value {
                    "success" => "success",
                    "error" => "error",
                    "disconnected" => "disconnected",
                    _ => "other",
                };
            }
            _ => {}
        }
    }

    fn record_debug(&mut self, _field: &Field, _value: &dyn fmt::Debug) {}
}

fn span_kind(metadata: &Metadata<'_>) -> Option<&'static str> {
    if !metadata.is_span() {
        return None;
    }
    match (metadata.target(), metadata.name()) {
        ("codex_exec_server::connection", "codex.exec_server.request") => Some("request"),
        ("codex_exec_server::capability_discovery", "capability_roots.discover_v1") => {
            Some("generic")
        }
        ("codex_exec_server::sandboxed_file_system", "capability_roots.discover_v1") => {
            Some("whole_helper")
        }
        _ => None,
    }
}

impl DiscoveryTrace {
    fn emit(&self, event: &str, id: &Id, observation: Observation) {
        if self
            .records
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |count| {
                (count < MAX_RECORDS).then_some(count + 1)
            })
            .is_err()
        {
            return;
        }
        let span = id.into_u64();
        let Observation {
            kind,
            method,
            result,
            roots,
            started,
        } = observation;
        let elapsed_ms = started.elapsed().as_millis();
        let mut line = [0_u8; LINE_BYTES];
        let mut writer = line.as_mut_slice();
        if writeln!(
            writer,
            "capability_trace event={event} kind={kind} span={span} method={method} result={result} roots={roots:?} elapsed_ms={elapsed_ms}",
        )
        .is_err()
        {
            return;
        }
        let written = LINE_BYTES - writer.len();
        // One write, after releasing span extensions. Short writes and errors
        // do not replace the original result. Byte limits do not bound delay.
        let _ = std::io::stderr().write(&line[..written]);
    }
}

impl Layer<Registry> for DiscoveryTrace {
    fn enabled(&self, metadata: &Metadata<'_>, _context: Context<'_, Registry>) -> bool {
        span_kind(metadata).is_some()
    }

    fn on_new_span(&self, attributes: &Attributes<'_>, id: &Id, context: Context<'_, Registry>) {
        let Some(kind) = span_kind(attributes.metadata()) else {
            return;
        };
        let mut observation = Observation {
            kind,
            method: "unset",
            result: "unset",
            roots: None,
            started: Instant::now(),
        };
        attributes.record(&mut observation);
        {
            let Some(span) = context.span(id) else {
                return;
            };
            span.extensions_mut().insert(observation);
        }
        self.emit("NEW", id, observation);
    }

    fn on_record(&self, id: &Id, values: &Record<'_>, context: Context<'_, Registry>) {
        if let Some(span) = context.span(id) {
            let mut extensions = span.extensions_mut();
            if let Some(observation) = extensions.get_mut::<Observation>() {
                values.record(observation);
            }
        }
    }

    fn on_close(&self, id: Id, context: Context<'_, Registry>) {
        let observation = {
            let Some(span) = context.span(&id) else {
                return;
            };
            let extensions = span.extensions();
            extensions.get::<Observation>().copied()
        };
        if let Some(observation) = observation {
            self.emit("CLOSE", &id, observation);
        }
    }
}
