//! Failure-only public diagnostics. Closed phases/enums and scalar metadata
//! cannot authorize, refresh, retry, select a peer, or expose a wire payload.
use crate::AgentdRootAuthorityError;
use crate::HostAuthorityLane;
use crate::root_observation_diagnostic::ObservationDiagnostics;
use codex_hepta_contracts::HostIssuerTransportError;
use std::cell::Cell;
use std::io::Write;

#[derive(Clone, Copy, Debug)]
pub(crate) enum RootClientPhase {
    BootstrapClock,
    BootstrapStream,
    WriterProofRead,
    WriterProofShape,
    WriterProofVerification,
    InitialObservation,
    ReactorStart,
    InitialRevocations,
    ActivateConsumers,
}

#[derive(Clone, Copy, Debug)]
enum ObservationFailureKind {
    NoneRecorded,
    TransportTimeout,
    TransportIo,
    TransportFraming,
    TransportLifetime,
    TransportUnavailable,
    ReactorStartup,
    CacheAgeOrRollback,
    CacheSample,
    CacheProjection,
    CacheOrdering,
    CacheClock,
    ProofMismatch,
    LeaseExpiry,
    LifetimeExpiry,
    SessionOrWorkerExit,
    ConsumerSynchronization,
    OtherInternal,
}

impl ObservationFailureKind {
    fn from_stage(stage: Option<&'static str>) -> Self {
        match stage {
            None => Self::NoneRecorded,
            Some(
                "stream_read_timeout" | "stream_deadline_elapsed_before" | "stream_response_late",
            ) => Self::TransportTimeout,
            Some(
                "stream_request_prefix_write"
                | "stream_request_body_write"
                | "stream_response_prefix_read"
                | "stream_response_body_read"
                | "stream_root_readable_error",
            ) => Self::TransportIo,
            Some(
                "stream_request_serialize"
                | "stream_request_length"
                | "stream_response_length"
                | "stream_response_malformed",
            ) => Self::TransportFraming,
            Some(
                "stream_read_lifetime_before"
                | "stream_read_lifetime_after"
                | "stream_transfer_lifetime"
                | "stream_root_readable"
                | "live_root_lifetime_before"
                | "live_root_lifetime_after",
            ) => Self::TransportLifetime,
            Some("stream_slot_busy" | "stream_slot_empty" | "stream_read_cancelled") => {
                Self::TransportUnavailable
            }
            Some("refresh_worker_transfer" | "refresh_worker_spawn" | "refresh_worker_start") => {
                Self::ReactorStartup
            }
            Some("cache_current_age_or_rollback") => Self::CacheAgeOrRollback,
            Some("cache_accept_sample") => Self::CacheSample,
            Some("cache_accept_projection" | "cache_current_projection") => Self::CacheProjection,
            Some("cache_accept_previous") => Self::CacheOrdering,
            Some(
                "cache_accept_clock"
                | "cache_current_clock"
                | "refresh_started_clock"
                | "refresh_ended_clock",
            ) => Self::CacheClock,
            Some("live_root_proof_mismatch" | "refresh_proof_mismatch") => Self::ProofMismatch,
            Some("live_root_lease_expiry") => Self::LeaseExpiry,
            Some("live_root_boottime_or_expiry") => Self::LifetimeExpiry,
            Some("session_drop" | "refresh_worker_exit") => Self::SessionOrWorkerExit,
            Some(
                "activation_lock_timeout"
                | "activation_consumer_sync"
                | "activation_incomplete"
                | "refresh_consumer_sync",
            ) => Self::ConsumerSynchronization,
            Some(_) => Self::OtherInternal,
        }
    }
}

pub(crate) fn client_failure(
    phase: RootClientPhase,
    error: AgentdRootAuthorityError,
    diagnostics: Option<&ObservationDiagnostics>,
) {
    let first = diagnostics.and_then(ObservationDiagnostics::first);
    let kind = ObservationFailureKind::from_stage(first.map(|failure| failure.stage));
    // Every Debug value below is a closed enum or a scalar-only structure.
    // The internal stage string, error Display and authority payloads are excluded.
    let _ = writeln!(
        std::io::stderr(),
        "HEPTA_ROOT_CLIENT_FAILURE phase={phase:?} error={error:?} kind={kind:?} duration_ns={:?} now_ns={:?} started_ns={:?} ended_ns={:?} previous_started_ns={:?} previous_checked_ns={:?} projected_unix_ms={:?} ceiling_unix_ms={:?} os_error={:?} io_error_kind={:?} poll_result={:?} poll_revents={:?} progress={:?}",
        first.and_then(|failure| failure.duration_ns),
        first.and_then(|failure| failure.now_ns),
        first.and_then(|failure| failure.started_ns),
        first.and_then(|failure| failure.ended_ns),
        first.and_then(|failure| failure.previous_started_ns),
        first.and_then(|failure| failure.previous_checked_ns),
        first.and_then(|failure| failure.projected_unix_ms),
        first.and_then(|failure| failure.ceiling_unix_ms),
        first.and_then(|failure| failure.os_error),
        first.and_then(|failure| failure.io_error_kind),
        first.and_then(|failure| failure.poll_result),
        first.and_then(|failure| failure.poll_revents),
        first.and_then(|failure| failure.progress),
    );
}

#[derive(Clone, Copy, Debug)]
pub(crate) enum RootServicePhase {
    CheckpointPeer,
    ChannelOpen,
    Exchange,
    WriterObservation,
    WriterProof,
    WriterRevocations,
    WriterProjection,
    WriterLeaseAfter,
    WriterEncoding,
}

#[derive(Clone, Copy)]
struct RootWriterFailure {
    phase: RootServicePhase,
    kind: std::io::ErrorKind,
    os_error: Option<i32>,
}

/// One synchronous `serve` invocation owns this collector. It is neither
/// shared between lanes nor retained across connections. Recording only copies
/// public scalar metadata; it never writes, locks, clears or changes authority.
pub(crate) struct RootServiceDiagnostics {
    phase: Cell<RootServicePhase>,
    first_writer: Cell<Option<RootWriterFailure>>,
}

impl RootServiceDiagnostics {
    pub(crate) fn new() -> Self {
        Self {
            phase: Cell::new(RootServicePhase::ChannelOpen),
            first_writer: Cell::new(None),
        }
    }

    pub(crate) fn stage(&self, phase: RootServicePhase) {
        self.phase.set(phase);
    }

    pub(crate) fn record_writer(&self, phase: RootServicePhase, error: &std::io::Error) {
        if self.first_writer.get().is_none() {
            self.first_writer.set(Some(RootWriterFailure {
                phase,
                kind: error.kind(),
                os_error: error.raw_os_error(),
            }));
        }
    }

    /// Called only after `serve_inner` returned and released every original
    /// stream/channel/pidfd. Synchronous output can still take unbounded time;
    /// it cannot defer the original channel's shutdown or resource drop.
    pub(crate) fn report_after_release(
        &self,
        lane: HostAuthorityLane,
        error: HostIssuerTransportError,
    ) {
        if let Some(RootWriterFailure {
            phase,
            kind,
            os_error,
        }) = self.first_writer.get()
        {
            let _ = writeln!(
                std::io::stderr(),
                "HEPTA_ROOT_SERVICE_FAILURE lane=Observation phase={phase:?} io_error_kind={kind:?} os_error={os_error:?}"
            );
        }
        let phase = self.phase.get();
        let _ = writeln!(
            std::io::stderr(),
            "HEPTA_ROOT_SERVICE_FAILURE lane={lane:?} phase={phase:?} error={error:?}"
        );
    }
}
