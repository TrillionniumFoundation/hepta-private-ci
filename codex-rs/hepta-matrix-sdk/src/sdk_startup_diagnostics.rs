//! Opt-in startup observations. Only source-defined labels and monotonic elapsed
//! time are emitted; never format SDK errors, identities, paths or credentials.
use std::io::Write;
use std::time::Instant;

pub(super) struct StartupPhase {
    name: &'static str,
    started: Instant,
    enabled: bool,
    finished: bool,
}

impl StartupPhase {
    pub(super) fn new(name: &'static str) -> Self {
        let phase = Self {
            name,
            started: Instant::now(),
            enabled: std::env::var_os("HEPTA_MATRIX_STARTUP_DIAGNOSTICS")
                .is_some_and(|value| value == "1"),
            finished: false,
        };
        phase.report("started");
        phase
    }

    pub(super) fn advance(&mut self, name: &'static str) {
        self.report("complete");
        self.name = name;
        self.started = Instant::now();
        self.report("started");
    }

    pub(super) fn finish(&mut self, outcome: &'static str) {
        self.report(outcome);
        self.finished = true;
    }

    fn report(&self, outcome: &'static str) {
        if self.enabled {
            let _ = writeln!(
                std::io::stderr().lock(),
                "matrix_startup phase={} outcome={outcome} elapsed_ms={}",
                self.name,
                self.started.elapsed().as_millis(),
            );
        }
    }
}

impl Drop for StartupPhase {
    fn drop(&mut self) {
        if !self.finished {
            // Can be cancellation, an early error, or unwind. Do not infer which.
            self.report("dropped-without-completion");
        }
    }
}
