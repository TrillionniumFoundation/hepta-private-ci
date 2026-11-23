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

pub(crate) fn thread_cpu_ns()->Option<u64> {
    let mut sample=libc::timespec{tv_sec:0,tv_nsec:0};
    // SAFETY: Linux writes one live timespec for this calling thread.
    if unsafe{libc::clock_gettime(libc::CLOCK_THREAD_CPUTIME_ID,&mut sample)}!=0 || sample.tv_sec<0 || !(0..1_000_000_000).contains(&sample.tv_nsec){return None}
    (sample.tv_sec as u64).checked_mul(1_000_000_000)?.checked_add(sample.tv_nsec as u64)
}

pub(crate) fn pinned_kind(error:&codex_hepta_learning_artifacts::PinnedCandidateLoadError)->&'static str {
    use codex_hepta_learning_artifacts::PinnedCandidateLoadError::*;
    match error {PinMismatch=>"pin_mismatch",FrontierMismatch=>"frontier_mismatch",Ineligible=>"ineligible",Unavailable=>"unavailable",Storage(e)=>storage_kind(e)}
}
fn storage_kind(error:&codex_hepta_learning_artifacts::ArtifactStorageError)->&'static str {
    use codex_hepta_learning_artifacts::ArtifactStorageError::*;
    match error { Io(std::io::ErrorKind::NotFound)=>"storage_io_not_found", Io(std::io::ErrorKind::PermissionDenied)=>"storage_io_permission",
        Io(_)=>"storage_io_other",Busy=>"storage_busy",Unavailable=>"storage_unavailable",Indeterminate=>"storage_indeterminate",
        PayloadMismatch=>"storage_payload_mismatch", _=>"storage_other_category" }
}
pub(crate) fn service_kind(error:&codex_hepta_learning_artifacts::LearningArtifactOwnerServiceError)->&'static str {
    use codex_hepta_learning_artifacts::{LearningArtifactOwnerServiceError as E, ArtifactOwnerHostError as H};
    match error {
        E::Host(H::Io(std::io::ErrorKind::NotFound))=>"host_io_not_found",E::Host(H::Io(std::io::ErrorKind::PermissionDenied))=>"host_io_permission",
        E::Host(H::Io(_))=>"host_io_other",E::Host(H::Storage(e))=>storage_kind(e),E::Host(H::CurrentHeadExpired)=>"host_current_head_expired",
        E::Host(H::CurrentHeadRollback)=>"host_current_head_rollback",E::Host(H::CheckpointMissing)=>"host_checkpoint_missing",
        E::Host(H::WriterFenceBusy)=>"host_writer_fence_busy",E::Host(_)=>"host_other_category",E::Publication(_)=>"publication",
        E::RecoveryRequired(_)=>"recovery_required",E::WithdrawalFrontierConflict=>"withdrawal_frontier_conflict", _=>"service_other_category" }
}
