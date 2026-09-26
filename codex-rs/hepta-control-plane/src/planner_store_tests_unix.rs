use std::collections::BTreeSet;
use std::fmt::Debug;
use std::fs;
use std::fs::File;
use std::io;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[cfg(unix)]
use std::os::unix::fs::symlink;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::FsPlannerPersistenceV1;
use super::LOCK_FILE;
use super::PlannerBodyKindV1;
use super::PlannerPersistenceV1;
use super::PlannerStoreError;
use super::PlannerStoreV1;
use super::STORE_FILE;
use super::TEMP_FILE;
use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlannerJournalV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::collect_snapshot;
use crate::finalize_plan;
use crate::prepare_plan;

static NONCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FaultStage {
    Write,
    FileSync,
    Rename,
    DirectorySync,
}

struct FaultPersistence {
    stage: FaultStage,
    real: FsPlannerPersistenceV1,
}

impl PlannerPersistenceV1 for FaultPersistence {
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        if self.stage == FaultStage::Write {
            return Err(io::Error::other("injected planner temp-write failure"));
        }
        self.real.write_temp(path, bytes)
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        if self.stage == FaultStage::FileSync {
            return Err(io::Error::other("injected planner file-sync failure"));
        }
        self.real.sync_temp(path)
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        if self.stage == FaultStage::Rename {
            return Err(io::Error::other("injected planner rename failure"));
        }
        self.real.rename(from, to)
    }

    fn sync_parent(&self, root: &Path) -> io::Result<()> {
        if self.stage == FaultStage::DirectorySync {
            return Err(io::Error::other(
                "injected planner parent-directory-sync failure",
            ));
        }
        self.real.sync_parent(root)
    }
}

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

struct TempRoot(PathBuf);

impl TempRoot {
    fn new(label: &str) -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-planner-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("create temp planner root");
        Self(path)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn snapshot_and_receipt() -> (GlobalStateSnapshotV1, FeasiblePlanReceiptV1) {
    let snapshot = must(collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: must(Generation::new(7)),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 1_000,
            maximum_owner_age_micros: 100,
            expires_at_micros: 2_000,
            required_owner_ids: vec![id("planner")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("planner"),
            revision: must(Revision::new(3)),
            objective_digest: digest("objective"),
            body_generation: must(Generation::new(7)),
            configuration_digest: digest("configuration"),
            observed_at_micros: 950,
            expires_at_micros: 1_800,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }],
    ));
    let prepared = must(prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("plan"),
            now_micros: 1_000,
            deadline_micros: 1_700,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("resource-profile"),
            candidates: vec![
                PlanCandidateV1 {
                    candidate_id: id("abstain"),
                    operation_id: id("abstain"),
                    plan_digest: digest("abstain-plan"),
                    required_owner_ids: vec![id("planner")],
                    final_payload_digests: Vec::new(),
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: FixedQ32::ZERO,
                    }],
                },
                PlanCandidateV1 {
                    candidate_id: id("work"),
                    operation_id: id("operation-work"),
                    plan_digest: digest("work-plan"),
                    required_owner_ids: vec![id("planner")],
                    final_payload_digests: vec![digest("payload")],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: q32(1),
                    }],
                },
            ],
            resource_reservations: vec![ResourceReservationV1 {
                axis: id("compute"),
                endowment: q32(10),
                essential_floor: FixedQ32::ZERO,
            }],
        },
    ));
    let evaluation = must(bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest(),
        body_generation: prepared.body_generation(),
        evaluation_policy_digest: prepared.evaluation_policy_digest(),
        evaluation_digest: digest("ndu-evaluation"),
        evaluated_candidate_ids: prepared
            .feasible_candidates()
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect(),
        rejected_candidate_ids: Vec::new(),
        pareto_candidate_ids: vec![id("work")],
        advisory_candidate_id: Some(id("work")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    }));
    let receipt = must(finalize_plan(&snapshot, &prepared, &evaluation, 1_100));
    (snapshot, receipt)
}

#[test]
fn durable_store_round_trips_full_bodies_selection_and_revocation() {
    let root = TempRoot::new("roundtrip");
    let (snapshot, receipt) = snapshot_and_receipt();
    {
        let mut store = must(PlannerStoreV1::open(&root.0));
        must(store.record_snapshot(&snapshot, b"canonical-snapshot-envelope-v1"));
        must(store.record_decision(&receipt, b"canonical-decision-envelope-v1"));
        must(store.select_plan(digest("selection-operation"), &receipt));
        assert_eq!(must(store.selected_plan_digest()), Some(receipt.receipt_digest()));
        assert!(must(store.has_complete_body_coverage()));
        assert_eq!(
            must(store.body(receipt.receipt_digest()))
                .expect("decision body")
                .bytes(),
            b"canonical-decision-envelope-v1"
        );
    }

    {
        let mut store = must(PlannerStoreV1::open(&root.0));
        assert_eq!(must(store.selected_plan_digest()), Some(receipt.receipt_digest()));
        must(store.revoke(digest("revocation-operation"), receipt.receipt_digest()));
        assert_eq!(must(store.selected_plan_digest()), None);
    }

    let store = must(PlannerStoreV1::open(&root.0));
    assert_eq!(must(store.entries()).len(), 4);
    assert_eq!(must(store.selected_plan_digest()), None);
    assert!(must(store.has_complete_body_coverage()));
}

#[test]
fn evidence_chain_and_external_checkpoint_survive_reopen() {
    let root = TempRoot::new("evidence");
    let (_, receipt) = snapshot_and_receipt();
    let request = digest("authority-request");
    let grant = digest("authority-grant");
    let terminal = digest("terminal-receipt");
    let anchor = digest("external-anchor");

    {
        let mut store = must(PlannerStoreV1::open(&root.0));
        must(store.record_decision(&receipt, b"decision"));
        must(store.record_evidence(
            PlannerBodyKindV1::AuthorityRequest,
            request,
            receipt.receipt_digest(),
            b"request",
        ));
        must(store.record_evidence(
            PlannerBodyKindV1::AuthorityGrant,
            grant,
            request,
            b"grant",
        ));
        must(store.record_evidence(
            PlannerBodyKindV1::TerminalReceipt,
            terminal,
            grant,
            b"terminal",
        ));
        let checkpoint = must(store.anchor_checkpoint(anchor));
        assert_eq!(checkpoint.external_anchor_digest(), anchor);
    }

    let store = must(PlannerStoreV1::open(&root.0));
    assert_eq!(
        must(store.checkpoint())
            .expect("checkpoint")
            .external_anchor_digest(),
        anchor
    );
    assert_eq!(
        must(store.body(terminal)).expect("terminal body").parent_digest(),
        Some(grant)
    );
}

#[test]
fn bounded_compaction_requires_archive_anchor_and_keeps_requested_chain() {
    let root = TempRoot::new("compaction");
    let (_, receipt) = snapshot_and_receipt();
    let request = digest("request");
    let grant = digest("grant");
    let terminal = digest("terminal");
    let reconciliation = digest("reconciliation");
    let discard = digest("discard");
    let mut store = must(PlannerStoreV1::open(&root.0));
    must(store.record_decision(&receipt, b"decision"));
    must(store.record_evidence(
        PlannerBodyKindV1::AuthorityRequest,
        request,
        receipt.receipt_digest(),
        b"request",
    ));
    must(store.record_evidence(
        PlannerBodyKindV1::AuthorityGrant,
        grant,
        request,
        b"grant",
    ));
    must(store.record_evidence(
        PlannerBodyKindV1::TerminalReceipt,
        terminal,
        grant,
        b"terminal",
    ));
    must(store.record_evidence(
        PlannerBodyKindV1::Reconciliation,
        reconciliation,
        terminal,
        b"reconciliation",
    ));
    must(store.record_evidence(
        PlannerBodyKindV1::Reconciliation,
        discard,
        receipt.receipt_digest(),
        b"discard",
    ));

    let retain = [request, grant, terminal, reconciliation]
        .into_iter()
        .collect::<BTreeSet<_>>();
    assert_eq!(
        must(store.compact_evidence(&retain, digest("archive-anchor"))),
        1
    );
    assert!(must(store.body(discard)).is_none());
    assert!(must(store.body(reconciliation)).is_some());
    assert_eq!(
        must(store.checkpoint())
            .expect("archive checkpoint")
            .external_anchor_digest(),
        digest("archive-anchor")
    );
}

#[test]
fn backup_restore_is_monotonic_and_validated() {
    let source_root = TempRoot::new("backup-source");
    let target_root = TempRoot::new("backup-target");
    let (snapshot, receipt) = snapshot_and_receipt();
    let backup = {
        let mut source = must(PlannerStoreV1::open(&source_root.0));
        must(source.record_snapshot(&snapshot, b"snapshot"));
        must(source.record_decision(&receipt, b"decision"));
        must(source.select_plan(digest("selection"), &receipt));
        must(source.backup_bytes())
    };

    let mut target = must(PlannerStoreV1::open(&target_root.0));
    must(target.restore_backup(&backup));
    assert_eq!(must(target.selected_plan_digest()), Some(receipt.receipt_digest()));

    let mut tampered = backup.clone();
    let last = tampered.len() - 1;
    tampered[last] ^= 1;
    assert_eq!(
        target
            .restore_backup(&tampered)
            .expect_err("tampered backup must reject"),
        PlannerStoreError::CorruptImageDigest
    );

    must(target.revoke(digest("revoke"), receipt.receipt_digest()));
    assert_eq!(
        target
            .restore_backup(&backup)
            .expect_err("older backup must not remove revocation"),
        PlannerStoreError::BackupRegression
    );
}

#[test]
fn legacy_digest_only_journal_is_migrated_but_reports_missing_bodies() {
    let root = TempRoot::new("legacy");
    let (_, receipt) = snapshot_and_receipt();
    let mut journal = PlannerJournalV1::new();
    must(journal.record_decision(&receipt));
    let mut file = File::create(root.0.join(STORE_FILE)).expect("legacy planner journal");
    file.write_all(&journal.export_bytes())
        .expect("write legacy journal");
    file.sync_all().expect("sync legacy journal");
    drop(file);

    let store = must(PlannerStoreV1::open(&root.0));
    assert!(!must(store.has_complete_body_coverage()));
    assert_eq!(must(store.entries()).len(), 1);
    assert!(must(store.backup_bytes()).starts_with(b"HCPSTR01"));
}

#[test]
fn conflicting_body_for_same_semantic_identity_is_rejected() {
    let root = TempRoot::new("body-conflict");
    let (_, receipt) = snapshot_and_receipt();
    let mut store = must(PlannerStoreV1::open(&root.0));
    must(store.record_decision(&receipt, b"decision-v1"));
    assert_eq!(
        store
            .record_decision(&receipt, b"decision-v2")
            .expect_err("same semantic identity cannot change bytes"),
        PlannerStoreError::BodyConflict
    );
}

#[test]
fn stale_uncommitted_temp_image_is_discarded_before_recovery() {
    let root = TempRoot::new("stale-temp");
    let mut temp = File::create(root.0.join(TEMP_FILE)).expect("create stale temp image");
    temp.write_all(b"uncommitted garbage")
        .expect("write stale temp image");
    temp.sync_all().expect("sync stale temp fixture");
    drop(temp);

    let store = must(PlannerStoreV1::open(&root.0));
    assert!(must(store.entries()).is_empty());
    assert!(!root.0.join(TEMP_FILE).exists());
}

#[test]
fn concurrent_writer_is_rejected_while_owner_lock_is_live() {
    let root = TempRoot::new("writer-lock");
    let owner = must(PlannerStoreV1::open(&root.0));
    assert_eq!(
        PlannerStoreV1::open(&root.0)
            .err()
            .expect("second writer must reject"),
        PlannerStoreError::Busy
    );
    drop(owner);
    must(PlannerStoreV1::open(&root.0));
}

#[test]
fn persistence_failpoints_reconcile_at_real_durability_boundaries() {
    for stage in [
        FaultStage::Write,
        FaultStage::FileSync,
        FaultStage::Rename,
        FaultStage::DirectorySync,
    ] {
        let root = TempRoot::new(match stage {
            FaultStage::Write => "fail-write",
            FaultStage::FileSync => "fail-file-sync",
            FaultStage::Rename => "fail-rename",
            FaultStage::DirectorySync => "fail-directory-sync",
        });
        {
            let store = must(PlannerStoreV1::open(&root.0));
            drop(store);
        }

        let persistence = Arc::new(FaultPersistence {
            stage,
            real: FsPlannerPersistenceV1,
        });
        let mut store = must(PlannerStoreV1::open_with_persistence(
            &root.0,
            persistence,
        ));
        let (_, receipt) = snapshot_and_receipt();
        let error = store
            .record_decision(&receipt, b"decision")
            .expect_err("injected persistence failure must surface");

        if stage == FaultStage::DirectorySync {
            assert_eq!(error, PlannerStoreError::Indeterminate);
            assert!(store.is_indeterminate());
            assert_eq!(
                store
                    .entries()
                    .expect_err("indeterminate handle must fail closed"),
                PlannerStoreError::Indeterminate
            );
        } else {
            assert_eq!(error, PlannerStoreError::Io(io::ErrorKind::Other));
            assert!(!store.is_indeterminate());
            assert!(must(store.entries()).is_empty());
        }

        drop(store);
        let reopened = must(PlannerStoreV1::open(&root.0));
        assert!(!reopened.is_indeterminate());
        if stage == FaultStage::DirectorySync {
            assert_eq!(must(reopened.entries()).len(), 1);
        } else {
            assert!(must(reopened.entries()).is_empty());
        }
    }
}

#[cfg(unix)]
#[test]
fn symlinked_root_lock_and_store_paths_fail_closed() {
    let target_root = TempRoot::new("symlink-target");
    let target_file = target_root.0.join("outside-file");
    File::create(&target_file).expect("create symlink target");

    let root_link = std::env::temp_dir().join(format!(
        "hepta-planner-root-link-{}-{}",
        std::process::id(),
        NONCE.fetch_add(1, Ordering::Relaxed)
    ));
    symlink(&target_root.0, &root_link).expect("create root symlink");
    assert_eq!(
        PlannerStoreV1::open(&root_link)
            .err()
            .expect("symlinked root must reject"),
        PlannerStoreError::Symlink
    );
    fs::remove_file(&root_link).expect("remove root symlink");

    let lock_root = TempRoot::new("symlink-lock");
    symlink(&target_file, lock_root.0.join(LOCK_FILE)).expect("create lock symlink");
    assert_eq!(
        PlannerStoreV1::open(&lock_root.0)
            .err()
            .expect("symlinked lock must reject"),
        PlannerStoreError::Symlink
    );

    let store_root = TempRoot::new("symlink-store");
    symlink(&target_file, store_root.0.join(STORE_FILE)).expect("create store symlink");
    assert_eq!(
        PlannerStoreV1::open(&store_root.0)
            .err()
            .expect("symlinked store must reject"),
        PlannerStoreError::Symlink
    );
}
