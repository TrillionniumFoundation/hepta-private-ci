//! Isolated filesystem qualification only. These fixtures do NOT authenticate
//! production CAS, CNS, migration, final-use or Supervisor receipts.

use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use tempfile::TempDir;

fn id(raw: &str) -> StableId {
    StableId::new(raw).expect("id")
}

fn digest(raw: &[u8]) -> Digest32 {
    Digest32::of_bytes(raw)
}

fn gen(raw: u64) -> Generation {
    Generation::new(raw).expect("generation")
}

fn plan() -> WriterHandoffPlanV1 {
    WriterHandoffPlanV1 {
        operation_id: id("cell.split.test.1"),
        domain_id: id("cell.scope.test.1"),
        source_writer: id("cell.parent"),
        target_writer: id("cell.child"),
        old_generation: gen(7),
        new_generation: gen(8),
        authority_epoch: 17,
        migration_plan_digest: digest(b"migration"),
        schema_digest: digest(b"schema"),
        rollback_predecessor_digest: digest(b"predecessor"),
    }
}

fn binding() -> CellSplitBindingV1 {
    CellSplitBindingV1 {
        operation_id: plan().operation_id,
        selected_artifact_digest: digest(b"artifact"),
        predecessor_route_digest: digest(b"route-v1"),
        successor_route_digest: digest(b"route-v2"),
    }
}

fn file(root: &TempDir) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(root.path().join("split-journal"))
        .expect("journal file")
}

fn persist_create_only(path: &Path, value: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(value)?;
    file.sync_all()?;
    #[cfg(unix)]
    File::open(path.parent().expect("parent"))?.sync_all()?;
    Ok(())
}

struct FilesystemNative {
    root: PathBuf,
    binding: CellSplitBindingV1,
    indeterminate: Option<WriterHandoffPhaseV1>,
    bad_cas: bool,
    bad_child: bool,
    bad_route: bool,
    drift: bool,
    execute_count: usize,
}

impl FilesystemNative {
    fn open(root: &TempDir) -> Self {
        let native = root.path().join("native");
        fs::create_dir_all(&native).expect("native root");
        Self {
            root: native,
            binding: binding(),
            indeterminate: None,
            bad_cas: false,
            bad_child: false,
            bad_route: false,
            drift: false,
            execute_count: 0,
        }
    }

    fn stage(&self, phase: WriterHandoffPhaseV1) -> PathBuf {
        self.root.join(format!("stage-{}.ack", phase_tag(phase)))
    }

    fn marker(plan: &WriterHandoffPlanV1, phase: WriterHandoffPhaseV1) -> Vec<u8> {
        format!("native-owner:{}:{}\n", plan.operation_id, phase_tag(phase)).into_bytes()
    }

    fn observed(
        &self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
        ack: Digest32,
    ) -> io::Result<CellSplitObservedReceiptV1> {
        let artifact = self.binding.selected_artifact_digest;
        let child = digest(&fs::read(self.root.join("child-state")).unwrap_or_default());
        let evidence = match phase {
            WriterHandoffPhaseV1::AdmissionStopped => {
                CellSplitNativeEvidenceV1::AdmissionStopped { native_ack: ack }
            }
            WriterHandoffPhaseV1::Drained => CellSplitNativeEvidenceV1::Drained {
                native_ack: ack,
                outbox_watermark: 42,
                unknown_effects: 0,
            },
            WriterHandoffPhaseV1::OldWriterFenced => {
                CellSplitNativeEvidenceV1::OldWriterFenced {
                    native_ack: ack,
                    observed_generation: plan.old_generation,
                }
            }
            WriterHandoffPhaseV1::Snapshotted => {
                let readback = digest(&fs::read(self.root.join("cas-artifact"))?);
                CellSplitNativeEvidenceV1::ArtifactCasCommitted {
                    native_ack: ack,
                    payload_digest: artifact,
                    readback_digest: if self.bad_cas { digest(b"wrong") } else { readback },
                    registry_head_digest: digest(b"native-registry-head"),
                }
            }
            WriterHandoffPhaseV1::Migrated => CellSplitNativeEvidenceV1::ChildMigrated {
                native_ack: ack,
                artifact_digest: artifact,
                source_state_digest: digest(b"source-state"),
                child_state_digest: child,
            },
            WriterHandoffPhaseV1::Validated => CellSplitNativeEvidenceV1::ChildValidated {
                native_ack: ack,
                artifact_digest: artifact,
                child_state_digest: if self.bad_child { digest(b"wrong-child") } else { child },
            },
            WriterHandoffPhaseV1::NewWriterFenced => {
                CellSplitNativeEvidenceV1::NewWriterFenced {
                    native_ack: ack,
                    observed_generation: plan.new_generation,
                }
            }
            WriterHandoffPhaseV1::RoutePublished => {
                let route = digest(&fs::read(self.root.join("cns-route"))?);
                CellSplitNativeEvidenceV1::CnsRouteCutover {
                    native_ack: ack,
                    predecessor_digest: self.binding.predecessor_route_digest,
                    successor_digest: route,
                    observed_generation: if self.bad_route { plan.old_generation } else { plan.new_generation },
                }
            }
            WriterHandoffPhaseV1::Retired => {
                let route = digest(&fs::read(self.root.join("cns-route"))?);
                CellSplitNativeEvidenceV1::Retired {
                    native_ack: ack,
                    retired_generation: plan.old_generation,
                    active_generation: plan.new_generation,
                    active_route_digest: route,
                }
            }
            WriterHandoffPhaseV1::Prepared | WriterHandoffPhaseV1::Quarantined => {
                return Err(io::Error::new(io::ErrorKind::InvalidInput, "not executable"));
            }
        };
        Ok(CellSplitObservedReceiptV1 {
            operation_id: plan.operation_id.clone(),
            domain_id: plan.domain_id.clone(),
            old_generation: plan.old_generation,
            new_generation: plan.new_generation,
            authority_epoch: plan.authority_epoch,
            handoff_plan_digest: handoff_plan_digest(plan),
            binding_digest: if self.drift { digest(b"stale-binding") } else { self.binding.digest() },
            evidence,
        })
    }
}

impl CellSplitNativeOwnerV1 for FilesystemNative {
    type Error = io::Error;

    fn lookup(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<CellSplitLookupV1, Self::Error> {
        if self.indeterminate == Some(phase) {
            return Ok(CellSplitLookupV1::Indeterminate);
        }
        let path = self.stage(phase);
        let bytes = match fs::read(path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                // A native side effect without its publication receipt is
                // indeterminate, not proof that it never happened.
                let partial_path = match phase {
                    WriterHandoffPhaseV1::Snapshotted => Some("cas-artifact"),
                    WriterHandoffPhaseV1::Migrated => Some("child-state"),
                    WriterHandoffPhaseV1::RoutePublished => Some("cns-route"),
                    _ => None,
                };
                if partial_path.is_some_and(|name| self.root.join(name).exists()) {
                    return Ok(CellSplitLookupV1::Indeterminate);
                }
                return Ok(CellSplitLookupV1::Absent);
            }
            Err(error) => return Err(error),
        };
        if bytes != Self::marker(plan, phase) {
            return Ok(CellSplitLookupV1::Indeterminate);
        }
        self.observed(plan, phase, digest(&bytes))
            .map(CellSplitLookupV1::Observed)
    }

    fn execute(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<(), Self::Error> {
        // File create_new makes a second execution observable as an error.
        // Production adapters must use real idempotency keys and owner leases.
        match phase {
            WriterHandoffPhaseV1::Snapshotted => {
                persist_create_only(&self.root.join("cas-artifact"), b"artifact")?;
            }
            WriterHandoffPhaseV1::Migrated => {
                persist_create_only(&self.root.join("child-state"), b"child-state")?;
            }
            WriterHandoffPhaseV1::RoutePublished => {
                persist_create_only(&self.root.join("cns-route"), b"route-v2")?;
            }
            _ => {}
        }
        persist_create_only(&self.stage(phase), &Self::marker(plan, phase))?;
        self.execute_count += 1;
        Ok(())
    }
}

fn advance(
    journal: &mut DurableWriterHandoffJournalV1,
    native: &mut FilesystemNative,
) -> Result<WriterHandoffCheckpointV1, CellSplitOwnerErrorV1<io::Error>> {
    CellSplitOwnerV1::new(journal, native, binding())?.advance_once()
}

#[test]
fn every_phase_is_durable_recoverable_and_never_reexecuted_on_reopen() {
    let root = TempDir::new().expect("temp");
    let mut native = FilesystemNative::open(&root);
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    let stages = [
        WriterHandoffPhaseV1::AdmissionStopped,
        WriterHandoffPhaseV1::Drained,
        WriterHandoffPhaseV1::OldWriterFenced,
        WriterHandoffPhaseV1::Snapshotted,
        WriterHandoffPhaseV1::Migrated,
        WriterHandoffPhaseV1::Validated,
        WriterHandoffPhaseV1::NewWriterFenced,
        WriterHandoffPhaseV1::RoutePublished,
        WriterHandoffPhaseV1::Retired,
    ];
    for stage in stages {
        let checkpoint = advance(&mut journal, &mut native).expect("advance with native readback");
        assert_eq!(checkpoint.phase, stage);
        drop(journal);
        journal = DurableWriterHandoffJournalV1::recover_at_least(file(&root), &checkpoint)
            .expect("recover acknowledged phase");
        assert_eq!(journal.checkpoint(), &checkpoint);
    }
    assert_eq!(native.execute_count, stages.len());
    assert_eq!(advance(&mut journal, &mut native).expect("idempotent terminal").phase,
               WriterHandoffPhaseV1::Retired);
    assert_eq!(native.execute_count, stages.len());
}

#[test]
fn native_effect_preceding_journal_append_is_reused_without_second_execution() {
    let root = TempDir::new().expect("temp");
    let mut native = FilesystemNative::open(&root);
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    native.execute(&plan(), WriterHandoffPhaseV1::AdmissionStopped).expect("native effect");
    assert_eq!(advance(&mut journal, &mut native).expect("recover native effect").revision, 2);
    assert_eq!(native.execute_count, 1);
}

#[test]
fn indeterminate_and_missing_acknowledged_receipts_stop_execution() {
    let root = TempDir::new().expect("temp");
    let mut native = FilesystemNative::open(&root);
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    native.indeterminate = Some(WriterHandoffPhaseV1::AdmissionStopped);
    assert!(matches!(advance(&mut journal, &mut native), Err(CellSplitOwnerErrorV1::Indeterminate)));
    assert_eq!(native.execute_count, 0);
    native.indeterminate = None;
    advance(&mut journal, &mut native).expect("first stage");
    fs::remove_file(native.stage(WriterHandoffPhaseV1::AdmissionStopped)).expect("remove receipt");
    assert!(matches!(
        advance(&mut journal, &mut native),
        Err(CellSplitOwnerErrorV1::ObservationMissing)
    ));
    assert_eq!(native.execute_count, 1);
    assert_eq!(journal.checkpoint().phase, WriterHandoffPhaseV1::AdmissionStopped);
}

#[test]
fn frozen_binding_drift_prevents_route_and_artifact_progress() {
    let root = TempDir::new().expect("temp");
    let mut native = FilesystemNative::open(&root);
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    advance(&mut journal, &mut native).expect("admission");
    native.drift = true;
    assert!(matches!(
        advance(&mut journal, &mut native),
        Err(CellSplitOwnerErrorV1::InvalidObservation)
    ));
    assert_eq!(journal.checkpoint().phase, WriterHandoffPhaseV1::AdmissionStopped);
    assert_eq!(native.execute_count, 1);
}

#[test]
fn cas_readback_and_migration_state_mismatch_fail_closed() {
    let root = TempDir::new().expect("temp");
    let mut native = FilesystemNative::open(&root);
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    for _ in 0..3 { advance(&mut journal, &mut native).expect("pre CAS"); }
    native.bad_cas = true;
    assert!(matches!(
        advance(&mut journal, &mut native),
        Err(CellSplitOwnerErrorV1::InvalidObservation)
    ));
    assert_eq!(journal.checkpoint().phase, WriterHandoffPhaseV1::OldWriterFenced);
    native.bad_cas = false;
    advance(&mut journal, &mut native).expect("recover committed CAS without reexecute");
    advance(&mut journal, &mut native).expect("migrate");
    native.bad_child = true;
    assert!(matches!(
        advance(&mut journal, &mut native),
        Err(CellSplitOwnerErrorV1::InvalidObservation)
    ));
    assert_eq!(journal.checkpoint().phase, WriterHandoffPhaseV1::Migrated);
}

#[test]
fn cns_wrong_generation_does_not_publish_route_in_ledger() {
    let root = TempDir::new().expect("temp");
    let mut native = FilesystemNative::open(&root);
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    for _ in 0..7 { advance(&mut journal, &mut native).expect("before route"); }
    native.bad_route = true;
    assert!(matches!(
        advance(&mut journal, &mut native),
        Err(CellSplitOwnerErrorV1::InvalidObservation)
    ));
    assert_eq!(journal.checkpoint().phase, WriterHandoffPhaseV1::NewWriterFenced);
    native.bad_route = false;
    advance(&mut journal, &mut native).expect("native route observed, recover without replay");
    assert_eq!(native.execute_count, 8);
}

#[test]
fn incomplete_native_cas_intent_remains_indeterminate_without_retry() {
    let root = TempDir::new().expect("temp");
    let mut native = FilesystemNative::open(&root);
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    for _ in 0..3 {
        advance(&mut journal, &mut native).expect("before native CAS");
    }
    persist_create_only(&native.root.join("cas-artifact"), b"artifact")
        .expect("simulate crash after CAS write and before native ACK");
    let count = native.execute_count;
    assert!(matches!(
        advance(&mut journal, &mut native),
        Err(CellSplitOwnerErrorV1::Indeterminate)
    ));
    assert_eq!(native.execute_count, count);
    assert_eq!(journal.checkpoint().phase, WriterHandoffPhaseV1::OldWriterFenced);
}
