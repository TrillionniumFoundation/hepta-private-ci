use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::JOURNAL_NAME;
use super::PlannerJournalStoreV1;
use super::PlannerStoreErrorV1;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::canonical_resource_profile_digest;
use crate::collect_snapshot;
use crate::finalize_plan;
use crate::prepare_plan;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

struct TestRoot {
    path: PathBuf,
}

impl TestRoot {
    fn new(name: &str) -> Self {
        use std::os::unix::fs::DirBuilderExt;

        let path = std::env::temp_dir().join(format!(
            "hepta-control-runtime-{name}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&path);
        let mut builder = std::fs::DirBuilder::new();
        builder.mode(0o700);
        builder.create(&path).expect("create private test root");
        Self { path }
    }

    fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for TestRoot {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn fixture() -> (
    crate::GlobalStateSnapshotV1,
    PreparedPlanInputV1,
    crate::FeasiblePlanReceiptV1,
) {
    let generation = Generation::new(1).expect("generation");
    let snapshot = collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 20,
            expires_at_micros: 500,
            required_owner_ids: vec![id("owner")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("owner"),
            revision: Revision::new(1).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            observed_at_micros: 95,
            expires_at_micros: 500,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("source"),
            support_digest: digest("support"),
        }],
    )
    .expect("snapshot");
    let reservations = vec![ResourceReservationV1 {
        axis: id("compute"),
        endowment: q32(2),
        essential_floor: FixedQ32::ZERO,
    }];
    let prepared = prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("plan"),
            now_micros: 100,
            deadline_micros: 400,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: canonical_resource_profile_digest(&reservations)
                .expect("resource profile"),
            candidates: ["abstain", "work"]
                .into_iter()
                .map(|name| PlanCandidateV1 {
                    candidate_id: id(name),
                    operation_id: id(&format!("operation-{name}")),
                    plan_digest: digest(&format!("plan:{name}")),
                    required_owner_ids: vec![id("owner")],
                    final_payload_digests: if name == "work" {
                        vec![digest("payload")]
                    } else {
                        vec![]
                    },
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: if name == "work" {
                            q32(1)
                        } else {
                            FixedQ32::ZERO
                        },
                    }],
                })
                .collect(),
            resource_reservations: reservations,
        },
    )
    .expect("prepared");
    let evaluation = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest(),
        body_generation: prepared.body_generation(),
        evaluation_policy_digest: prepared.evaluation_policy_digest(),
        evaluation_digest: digest("evaluation"),
        evaluated_candidate_ids: prepared
            .feasible_candidates()
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect(),
        rejected_candidate_ids: vec![],
        pareto_candidate_ids: vec![id("work")],
        advisory_candidate_id: Some(id("work")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    })
    .expect("evaluation");
    let receipt = finalize_plan(&snapshot, &prepared, &evaluation, 110).expect("receipt");
    (snapshot, prepared, receipt)
}

#[test]
fn durable_store_round_trips_and_rejects_older_backup_against_trusted_head() {
    let temp = TestRoot::new("rollback");
    let (snapshot, _prepared, receipt) = fixture();
    let backup;
    let trusted_after_revoke;
    {
        let mut store = PlannerJournalStoreV1::open(temp.path()).expect("open store");
        store.record_snapshot(&snapshot).expect("snapshot");
        store.record_decision(&receipt).expect("decision");
        store
            .select_plan(digest("select"), &receipt)
            .expect("selection");
        backup = std::fs::read(store.journal_path()).expect("backup");
        store
            .revoke(digest("revoke"), receipt.receipt_digest())
            .expect("revoke");
        trusted_after_revoke = store.trusted_head().expect("trusted head");
    }

    std::fs::write(temp.path().join(JOURNAL_NAME), backup).expect("restore older backup");
    assert!(matches!(
        PlannerJournalStoreV1::open_with_minimum_head(temp.path(), Some(trusted_after_revoke)),
        Err(PlannerStoreErrorV1::RollbackDetected)
    ));
}

#[test]
fn bare_v0_journal_is_migrated_atomically_to_store_envelope() {
    use std::os::unix::fs::OpenOptionsExt;

    let temp = TestRoot::new("migration");
    let mut journal = PlannerJournalV1::new();
    journal
        .append(
            PlannerJournalKindV1::Snapshot,
            digest("snapshot-id"),
            digest("snapshot"),
        )
        .expect("append");
    let path = temp.path().join(JOURNAL_NAME);
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .expect("legacy journal");
    file.write_all(&journal.export_bytes())
        .expect("legacy bytes");
    file.sync_all().expect("legacy sync");
    drop(file);

    let store = PlannerJournalStoreV1::open(temp.path()).expect("migrate");
    assert_eq!(store.journal().entries(), journal.entries());
    let bytes = std::fs::read(path).expect("migrated bytes");
    assert!(bytes.starts_with(b"HCPSTR01"));
}

#[test]
fn live_writer_lock_excludes_a_second_store() {
    let temp = TestRoot::new("writer-lock");
    let _first = PlannerJournalStoreV1::open(temp.path()).expect("first writer");
    assert!(matches!(
        PlannerJournalStoreV1::open(temp.path()),
        Err(PlannerStoreErrorV1::Busy)
    ));
}
