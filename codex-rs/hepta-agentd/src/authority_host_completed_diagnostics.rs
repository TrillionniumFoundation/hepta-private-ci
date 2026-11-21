//! Bounded, payload-free observations for one already validated request.
//! Recording performs no I/O. Only the transport's terminal Err path emits
//! the fixed report, after all original authority and deadline postchecks.

use std::cell::Cell;
use std::io;
use std::io::Write;

const MAX_FAILURES: usize = 8;
const REPORT_BOUND: usize = 2048;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum CompletedStage {
    Checkpoint,
    OriginalTask,
    FrozenProfile,
    OriginalTaskPostchecks,
    ProfileScope,
    IndependentB,
    Publication,
    JournalSignatures,
    AcceptanceWindow,
    AcceptanceFact,
    JournalPostchecks,
    PublicationPostchecks,
    IndependentBPostchecks,
    ContextEntry,
    RecipientContext,
    TerminalCheckpoint,
    OriginalLedger,
    TrustActivation,
    ContextAction,
    ContextTrustPostcheck,
    ContextSignerPostcheck,
    ContextMetadataPostcheck,
    ContextDeadlinePostcheck,
    RecipientPostchecks,
    ContextExitMetadata,
    ContextExitDeadline,
    TerminalAccept,
    TerminalRead,
    ProviderPostchecks,
}

impl CompletedStage {
    fn label(self) -> &'static str {
        match self {
            Self::Checkpoint => "checkpoint",
            Self::OriginalTask => "original_task",
            Self::FrozenProfile => "frozen_profile",
            Self::OriginalTaskPostchecks => "original_task_postchecks",
            Self::ProfileScope => "profile_scope",
            Self::IndependentB => "independent_b",
            Self::Publication => "publication",
            Self::JournalSignatures => "journal_signatures",
            Self::AcceptanceWindow => "acceptance_window",
            Self::AcceptanceFact => "acceptance_fact",
            Self::JournalPostchecks => "journal_postchecks",
            Self::PublicationPostchecks => "publication_postchecks",
            Self::IndependentBPostchecks => "independent_b_postchecks",
            Self::ContextEntry => "context_entry",
            Self::RecipientContext => "recipient_context",
            Self::TerminalCheckpoint => "terminal_checkpoint",
            Self::OriginalLedger => "original_ledger",
            Self::TrustActivation => "trust_activation",
            Self::ContextAction => "context_action",
            Self::ContextTrustPostcheck => "context_trust_postcheck",
            Self::ContextSignerPostcheck => "context_signer_postcheck",
            Self::ContextMetadataPostcheck => "context_metadata_postcheck",
            Self::ContextDeadlinePostcheck => "context_deadline_postcheck",
            Self::RecipientPostchecks => "recipient_postchecks",
            Self::ContextExitMetadata => "context_exit_metadata",
            Self::ContextExitDeadline => "context_exit_deadline",
            Self::TerminalAccept => "terminal_accept",
            Self::TerminalRead => "terminal_read",
            Self::ProviderPostchecks => "provider_postchecks",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Failure {
    stage: CompletedStage,
    kind: io::ErrorKind,
    errno: Option<i32>,
}

pub(super) struct CompletedDiagnostics {
    request_id: u64,
    failures: Cell<[Option<Failure>; MAX_FAILURES]>,
    stored: Cell<usize>,
    truncated: Cell<bool>,
}

impl CompletedDiagnostics {
    pub(super) fn new(request_id: u64) -> Self {
        Self {
            request_id,
            failures: Cell::new([None; MAX_FAILURES]),
            stored: Cell::new(0),
            truncated: Cell::new(false),
        }
    }

    pub(super) fn check<T>(
        &self,
        stage: CompletedStage,
        action: impl FnOnce() -> io::Result<T>,
    ) -> io::Result<T> {
        let result = action();
        self.record_result(stage, &result);
        result
    }

    pub(super) fn record_result<T>(&self, stage: CompletedStage, result: &io::Result<T>) {
        if let Err(error) = result {
            let mut failures = self.failures.get();
            let stored = self.stored.get();
            if stored == MAX_FAILURES {
                self.truncated.set(true);
                return;
            }
            failures[stored] = Some(Failure {
                stage,
                kind: error.kind(),
                errno: error.raw_os_error(),
            });
            self.failures.set(failures);
            self.stored.set(stored + 1);
        }
    }

    pub(super) fn log_failure(&self, returned: &io::Error) {
        let mut bytes = [0_u8; REPORT_BOUND];
        let mut output = io::Cursor::new(bytes.as_mut_slice());
        if self.write_report(returned, &mut output).is_ok() {
            let length = output.position() as usize;
            let _ = io::stderr().write_all(&bytes[..length]);
        }
    }

    fn write_report(&self, returned: &io::Error, output: &mut impl Write) -> io::Result<()> {
        let request_id = self.request_id;
        for (index, failure) in self.failures.get().into_iter().flatten().enumerate() {
            let stage = failure.stage.label();
            let kind = safe_kind(failure.kind);
            write!(
                output,
                "root_diagnostic=completed request_id={request_id} index={index} stage={stage} kind={kind} errno="
            )?;
            match failure.errno {
                Some(errno) => writeln!(output, "{errno}")?,
                None => output.write_all(b"none\n")?,
            }
        }
        let stored = self.stored.get();
        let truncated = self.truncated.get();
        let kind = safe_kind(returned.kind());
        write!(
            output,
            "root_diagnostic=completed_return request_id={request_id} stored={stored} truncated={truncated} kind={kind} errno="
        )?;
        match returned.raw_os_error() {
            Some(errno) => writeln!(output, "{errno}"),
            None => output.write_all(b"none\n"),
        }
    }
}

fn safe_kind(kind: io::ErrorKind) -> &'static str {
    match kind {
        io::ErrorKind::NotFound => "not_found",
        io::ErrorKind::PermissionDenied => "permission_denied",
        io::ErrorKind::ConnectionRefused => "connection_refused",
        io::ErrorKind::ConnectionReset => "connection_reset",
        io::ErrorKind::ConnectionAborted => "connection_aborted",
        io::ErrorKind::NotConnected => "not_connected",
        io::ErrorKind::BrokenPipe => "broken_pipe",
        io::ErrorKind::AlreadyExists => "already_exists",
        io::ErrorKind::WouldBlock => "would_block",
        io::ErrorKind::InvalidInput => "invalid_input",
        io::ErrorKind::InvalidData => "invalid_data",
        io::ErrorKind::TimedOut => "timed_out",
        io::ErrorKind::WriteZero => "write_zero",
        io::ErrorKind::Interrupted => "interrupted",
        io::ErrorKind::UnexpectedEof => "unexpected_eof",
        io::ErrorKind::Unsupported => "unsupported",
        io::ErrorKind::OutOfMemory => "out_of_memory",
        io::ErrorKind::Other => "other",
        _ => "unclassified",
    }
}

#[cfg(test)]
#[path = "authority_host_completed_diagnostics_tests.rs"]
mod tests;
