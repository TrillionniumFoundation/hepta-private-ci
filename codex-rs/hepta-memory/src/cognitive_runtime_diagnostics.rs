//! Test-only phase observations. No owner IDs, paths, grant bytes or query text
//! are emitted. This module is absent from non-test builds.

use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_memory_federation::FederatedResultV2;
use codex_hepta_memory_federation::FederatedValidityV2;
use codex_hepta_memory_federation::FederationV2Error;
use serde::Serialize;

const NOT_ENTERED: u8 = 0;
const ACTIVE: u8 = 1;
const COMPLETED: u8 = 2;
const FAILED: u8 = 3;
const ENDED_WITHOUT_SUCCESS: u8 = 4;

#[derive(Clone, Copy)]
pub(super) enum Stage {
    Discovery,
    Preflight,
    Transport,
    Postflight,
}

impl Stage {
    const ALL: [Self; 4] = [
        Self::Discovery,
        Self::Preflight,
        Self::Transport,
        Self::Postflight,
    ];

    const fn index(self) -> usize {
        match self {
            Self::Discovery => 0,
            Self::Preflight => 1,
            Self::Transport => 2,
            Self::Postflight => 3,
        }
    }

    const fn name(self) -> &'static str {
        match self {
            Self::Discovery => "discovery",
            Self::Preflight => "preflight",
            Self::Transport => "transport",
            Self::Postflight => "postflight",
        }
    }
}

#[derive(Default)]
struct Phase {
    state: AtomicU8,
    entered_us: AtomicU64,
    ended_us: AtomicU64,
}

pub(super) struct Trace {
    pub(super) owner_index: usize,
    attempt_index: Option<usize>,
    started_at: Instant,
    authority_calls: AtomicUsize,
    last_entered: AtomicUsize,
    terminal: AtomicU8,
    terminal_us: AtomicU64,
    phases: [Phase; 4],
}

impl Trace {
    pub(super) fn new(
        owner_index: usize,
        attempt_index: Option<usize>,
        started_at: Instant,
    ) -> Self {
        Self {
            owner_index,
            attempt_index,
            started_at,
            authority_calls: AtomicUsize::default(),
            last_entered: AtomicUsize::default(),
            terminal: AtomicU8::default(),
            terminal_us: AtomicU64::default(),
            phases: std::array::from_fn(|_| Phase::default()),
        }
    }

    fn elapsed_us(&self) -> u64 {
        u64::try_from(self.started_at.elapsed().as_micros()).unwrap_or(u64::MAX)
    }

    pub(super) fn enter(&self, stage: Stage) -> PhaseGuard<'_> {
        let phase = &self.phases[stage.index()];
        phase.entered_us.store(self.elapsed_us(), Ordering::Relaxed);
        phase.state.store(ACTIVE, Ordering::Release);
        self.last_entered
            .store(stage.index() + 1, Ordering::Release);
        PhaseGuard { trace: self, stage }
    }

    pub(super) fn enter_authority(&self) -> PhaseGuard<'_> {
        // The unchanged execute_once calls authority once before dispatch and
        // once after a terminal response. Record the count as well as the phase.
        let call = self.authority_calls.fetch_add(1, Ordering::Relaxed);
        self.enter(if call == 0 {
            Stage::Preflight
        } else {
            Stage::Postflight
        })
    }

    pub(super) fn finish_discovery(&self, success: bool) {
        // The discovery future has ended before join_all returns its outcome.
        // Preserve the guard's actual end time, not this later collection time.
        self.phases[Stage::Discovery.index()]
            .state
            .store(if success { COMPLETED } else { FAILED }, Ordering::Release);
    }

    pub(super) fn finish_attempt(&self, result: &Result<FederatedResultV2, FederationV2Error>) {
        let terminal = match result {
            Ok(result) if result.validity == FederatedValidityV2::Valid => 1,
            Ok(_) => 2,
            Err(FederationV2Error::DeadlineExpired) => 3,
            Err(FederationV2Error::AttemptCancelled) => 4,
            Err(FederationV2Error::LeaseExpired) => 5,
            Err(FederationV2Error::ResponseExpired) => 6,
            Err(_) => 7,
        };
        self.terminal_us.store(self.elapsed_us(), Ordering::Relaxed);
        self.terminal.store(terminal, Ordering::Release);
    }

    fn snapshot(&self) -> Observation {
        let terminal = self.terminal.load(Ordering::Acquire);
        let last_entered = self.last_entered.load(Ordering::Acquire);
        Observation {
            owner_index: self.owner_index,
            attempt_index: self.attempt_index,
            last_entered: last_entered
                .checked_sub(1)
                .and_then(|index| Stage::ALL.get(index))
                .map(|stage| stage.name()),
            authority_calls: self.authority_calls.load(Ordering::Relaxed),
            terminal: match terminal {
                0 => None,
                1 => Some("valid"),
                2 => Some("invalid"),
                3 => Some("deadline_expired"),
                4 => Some("attempt_cancelled"),
                5 => Some("lease_expired"),
                6 => Some("response_expired"),
                _ => Some("error"),
            },
            terminal_elapsed_us: (terminal != 0).then(|| self.terminal_us.load(Ordering::Relaxed)),
            phases: Stage::ALL.map(|stage| {
                let phase = &self.phases[stage.index()];
                let state = phase.state.load(Ordering::Acquire);
                let entered_us =
                    (state != NOT_ENTERED).then(|| phase.entered_us.load(Ordering::Relaxed));
                let ended_us = matches!(state, COMPLETED | FAILED | ENDED_WITHOUT_SUCCESS)
                    .then(|| phase.ended_us.load(Ordering::Relaxed));
                PhaseObservation {
                    phase: stage.name(),
                    state: match state {
                        NOT_ENTERED => "not_entered",
                        ACTIVE => "active",
                        COMPLETED => "completed",
                        FAILED => "failed",
                        _ => "ended_without_success",
                    },
                    entered_us,
                    ended_us,
                    duration_us: entered_us
                        .zip(ended_us)
                        .map(|(entered, ended)| ended.saturating_sub(entered)),
                }
            }),
        }
    }

    pub(super) fn report(&self, context: &'static str) {
        match serde_json::to_string(&self.snapshot()) {
            Ok(line) => eprintln!("MEM_FEDERATION_OWNER context={context} {line}"),
            Err(_) => eprintln!("MEM_FEDERATION_OWNER context={context} diagnostic_format_error"),
        }
    }
}

pub(super) struct PhaseGuard<'a> {
    trace: &'a Trace,
    stage: Stage,
}

impl PhaseGuard<'_> {
    pub(super) fn finish(self, success: bool) {
        let phase = &self.trace.phases[self.stage.index()];
        phase
            .ended_us
            .store(self.trace.elapsed_us(), Ordering::Relaxed);
        phase
            .state
            .store(if success { COMPLETED } else { FAILED }, Ordering::Release);
    }
}

impl Drop for PhaseGuard<'_> {
    fn drop(&mut self) {
        let phase = &self.trace.phases[self.stage.index()];
        if phase.state.load(Ordering::Acquire) == ACTIVE {
            phase
                .ended_us
                .store(self.trace.elapsed_us(), Ordering::Relaxed);
            phase.state.store(ENDED_WITHOUT_SUCCESS, Ordering::Release);
        }
    }
}

#[derive(Debug, Serialize)]
struct PhaseObservation {
    phase: &'static str,
    state: &'static str,
    entered_us: Option<u64>,
    ended_us: Option<u64>,
    duration_us: Option<u64>,
}

#[derive(Debug, Serialize)]
struct Observation {
    owner_index: usize,
    attempt_index: Option<usize>,
    last_entered: Option<&'static str>,
    authority_calls: usize,
    terminal: Option<&'static str>,
    terminal_elapsed_us: Option<u64>,
    phases: [PhaseObservation; 4],
}

#[path = "cognitive_runtime_diagnostics_tests.rs"]
mod tests;
