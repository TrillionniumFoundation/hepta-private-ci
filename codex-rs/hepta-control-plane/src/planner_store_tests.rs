use std::collections::BTreeMap;
use std::error::Error;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::PlannerStoreError;
use super::PlannerStoreOptionsV1;
use super::PlannerStoreV1;
use super::TestFault;
use crate::FeasiblePlanReceiptV1;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlannerCheckpointAnchorV1;
use crate::PlannerCheckpointV1;
use crate::PlannerDecisionEnvelopeV1;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SignedPlannerCheckpointV1;
use crate::SnapshotRequestV1;

// This anchor is deliberately a unit fixture, not a production owner service.
#[derive(Clone)]
struct FixtureAnchor(Arc<Mutex<Option<SignedPlannerCheckpointV1>>>);

fn test_key() -> SigningKey { SigningKey::from_bytes(&[17; 32]) }
fn digest(bytes: &[u8]) -> Digest32 { Digest32::of_bytes(bytes) }

impl PlannerCheckpointAnchorV1 for FixtureAnchor {
    fn load(&mut self, _: Digest32) -> Result<Option<SignedPlannerCheckpointV1>, String> {
        Ok(self.0.lock().map_err(|_| "fixture poisoned")?.clone())
    }

    fn compare_exchange(
        &mut self,
        expected: Option<PlannerCheckpointV1>,
        next: PlannerCheckpointV1,
    ) -> Result<SignedPlannerCheckpointV1, String> {
        let mut current = self.0.lock().map_err(|_| "fixture poisoned")?;
        if let Some(existing) = current.as_ref() {
            if existing.checkpoint == next { return Ok(existing.clone()); }
        }
        if current.as_ref().map(|value| value.checkpoint) != expected {
            return Err("fixture CAS conflict".to_string());
        }
        let signed = SignedPlannerCheckpointV1 {
            checkpoint: next,
            signature: test_key().sign(&next.signing_bytes()).to_bytes(),
        };
        *current = Some(signed.clone());
        Ok(signed)
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    anchor: FixtureAnchor,
}

impl Fixture {
    fn new() -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            directory: tempfile::tempdir()?,
            anchor: FixtureAnchor(Arc::new(Mutex::new(None))),
        })
    }
    fn root(&self) -> PathBuf { self.directory.path().join("store") }
    fn open(&self) -> Result<PlannerStoreV1, PlannerStoreError> {
        self.open_options(PlannerStoreOptionsV1::default())
    }
    fn open_options(&self, options: PlannerStoreOptionsV1) -> Result<PlannerStoreV1, PlannerStoreError> {
        PlannerStoreV1::open(&self.root(), digest(b"store"), test_key().verifying_key(), Box::new(self.anchor.clone()), options)
    }
}

fn decision(seed: &[u8]) -> Result<(PlannerDecisionEnvelopeV1, FeasiblePlanReceiptV1), Box<dyn Error>> {
    let owner = StableId::new("owner")?;
    let objective = digest(seed);
    let generation = Generation::new(1)?;
    let snapshot = crate::collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: objective, body_generation: generation,
            configuration_digest: objective, revocation_frontier_digest: objective,
            snapshot_policy_digest: objective, collected_at_micros: 100,
            maximum_owner_age_micros: 10, expires_at_micros: 200,
            required_owner_ids: vec![owner.clone()],
        },
        vec![OwnerSummaryV1 {
            owner_id: owner.clone(), revision: Revision::new(1)?, objective_digest: objective,
            body_generation: generation, configuration_digest: objective,
            observed_at_micros: 100, expires_at_micros: 200, readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: objective, support_digest: objective,
        }],
    )?;
    let abstain = StableId::new("abstain")?;
    let axis = StableId::new("bytes")?;
    let prepared = crate::prepare_plan(&snapshot, PlanningRequestV1 {
        plan_id: StableId::new("decision")?, now_micros: 100, deadline_micros: 190,
        evaluation_policy_digest: objective, resource_profile_digest: objective,
        candidates: vec![PlanCandidateV1 {
            candidate_id: abstain.clone(), operation_id: abstain.clone(), plan_digest: objective,
            required_owner_ids: vec![owner], final_payload_digests: vec![],
            resource_costs: vec![PlannerAxisValueV1 { axis: axis.clone(), value: FixedQ32::ZERO }],
        }],
        resource_reservations: vec![ResourceReservationV1 { axis, endowment: FixedQ32::ZERO, essential_floor: FixedQ32::ZERO }],
    })?;
    let evaluation = crate::bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: objective, body_generation: generation, evaluation_policy_digest: objective,
        evaluation_digest: objective, evaluated_candidate_ids: vec![abstain.clone()],
        rejected_candidate_ids: vec![], pareto_candidate_ids: vec![abstain.clone()],
        advisory_candidate_id: Some(abstain), uncertainty_digest: objective,
        disposition: PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain,
    })?;
    let receipt = crate::finalize_plan(&snapshot, &prepared, &evaluation, 100)?;
    let envelope = PlannerDecisionEnvelopeV1::from_sealed_plan(&snapshot, &prepared, &evaluation, &receipt, 100)?;
    Ok((envelope, receipt))
}

#[test]
fn complete_decision_body_and_selection_survive_reopen() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let (body, _) = decision(b"one")?;
    let mut store = fixture.open()?;
    store.record_decision(digest(b"record"), &body)?;
    store.select_plan(digest(b"select"), body.receipt_digest())?;
    drop(store);
    let mut reopened = fixture.open()?;
    assert_eq!(reopened.selected_plan_digest()?, Some(body.receipt_digest()));
    assert_eq!(reopened.records()[0].body(), body.canonical_bytes());
    assert!(reopened.checkpoint().verify(&test_key().verifying_key()));
    Ok(())
}

#[test]
fn single_writer_lock_is_not_a_stale_pid_file() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let first = fixture.open()?;
    assert!(matches!(fixture.open(), Err(PlannerStoreError::Locked)));
    drop(first);
    let _reopened = fixture.open()?;
    Ok(())
}

#[test]
fn idempotency_requires_equal_complete_semantics() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let (first, _) = decision(b"one")?;
    let (second, _) = decision(b"two")?;
    let mut store = fixture.open()?;
    store.record_decision(digest(b"record"), &first)?;
    assert!(store.record_decision(digest(b"record"), &first)?.idempotent);
    assert!(matches!(store.record_decision(digest(b"record"), &second), Err(PlannerStoreError::IdentityConflict)));
    assert_eq!(store.records().len(), 1);
    Ok(())
}

#[test]
fn revocation_survives_segment_compaction() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let (body, _) = decision(b"one")?;
    let mut store = fixture.open()?;
    store.record_decision(digest(b"record"), &body)?;
    store.select_plan(digest(b"select"), body.receipt_digest())?;
    store.revoke_plan(digest(b"revoke"), body.receipt_digest())?;
    store.compact()?;
    drop(store);
    let mut store = fixture.open()?;
    assert_eq!(store.selected_plan_digest()?, None);
    assert!(matches!(store.select_plan(digest(b"reselect"), body.receipt_digest()), Err(PlannerStoreError::InvalidTransition)));
    assert_eq!(store.records()[0].body(), body.canonical_bytes());
    Ok(())
}

#[test]
fn partial_and_unanchored_complete_frames_are_not_published() -> Result<(), Box<dyn Error>> {
    for fault in [TestFault::PartialAppend, TestFault::AfterFileSync] {
        let fixture = Fixture::new()?;
        let (body, _) = decision(b"one")?;
        let mut store = fixture.open()?;
        store.fault = Some(fault);
        assert!(matches!(store.record_decision(digest(b"record"), &body), Err(PlannerStoreError::InjectedFailure)));
        assert!(matches!(store.selected_plan_digest(), Err(PlannerStoreError::Poisoned)));
        drop(store);
        let mut store = fixture.open()?;
        assert!(store.records().is_empty());
        assert!(store.recovered_tail_digest().is_some());
        assert_eq!(store.selected_plan_digest()?, None);
        store.record_decision(digest(b"record"), &body)?;
    }
    Ok(())
}

#[test]
fn lost_ack_after_anchor_recovers_idempotently() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let (body, _) = decision(b"one")?;
    let mut store = fixture.open()?;
    store.fault = Some(TestFault::AfterAnchor);
    assert!(matches!(store.record_decision(digest(b"record"), &body), Err(PlannerStoreError::InjectedFailure)));
    drop(store);
    let mut store = fixture.open()?;
    assert_eq!(store.records().len(), 1);
    assert!(store.record_decision(digest(b"record"), &body)?.idempotent);
    Ok(())
}

#[test]
fn complete_frame_corruption_is_not_tail_recovery() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let (body, _) = decision(b"one")?;
    let mut store = fixture.open()?;
    store.record_decision(digest(b"record"), &body)?;
    drop(store);
    let path = fixture.root().join("active.hcp");
    let mut bytes = fs::read(&path)?;
    let index = bytes.len() - 40;
    bytes[index] ^= 1;
    fs::write(&path, &bytes)?;
    assert!(matches!(fixture.open(), Err(PlannerStoreError::Corrupt)));
    assert_eq!(fs::read(path)?, bytes);
    Ok(())
}

#[test]
fn old_backup_cannot_resurrect_revoked_selection() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let (body, _) = decision(b"one")?;
    let mut store = fixture.open()?;
    store.record_decision(digest(b"record"), &body)?;
    store.select_plan(digest(b"select"), body.receipt_digest())?;
    let backup = store.backup_to(&fixture.directory.path().join("backups"))?;
    store.revoke_plan(digest(b"revoke"), body.receipt_digest())?;
    let target = fixture.directory.path().join("restored");
    assert!(matches!(PlannerStoreV1::restore_to_empty(&target, &backup, digest(b"store"), test_key().verifying_key(), Box::new(fixture.anchor.clone()), PlannerStoreOptionsV1::default()), Err(PlannerStoreError::Rollback)));
    assert!(!target.exists());
    Ok(())
}

#[test]
fn current_backup_round_trips_without_copying_anchor_key() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let (body, _) = decision(b"one")?;
    let mut store = fixture.open()?;
    store.record_decision(digest(b"record"), &body)?;
    store.select_plan(digest(b"select"), body.receipt_digest())?;
    let backup = store.backup_to(&fixture.directory.path().join("backups"))?;
    drop(store);
    let mut restored = PlannerStoreV1::restore_to_empty(&fixture.directory.path().join("restored"), &backup, digest(b"store"), test_key().verifying_key(), Box::new(fixture.anchor.clone()), PlannerStoreOptionsV1::default())?;
    assert_eq!(restored.selected_plan_digest()?, Some(body.receipt_digest()));
    Ok(())
}

#[test]
fn unrecorded_selection_and_quota_exhaustion_fail_closed() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let mut store = fixture.open_options(PlannerStoreOptionsV1 { maximum_records: 1, ..PlannerStoreOptionsV1::default() })?;
    assert!(matches!(store.select_plan(digest(b"select"), digest(b"unknown")), Err(PlannerStoreError::InvalidTransition)));
    let (body, _) = decision(b"one")?;
    store.record_decision(digest(b"record"), &body)?;
    assert!(matches!(store.select_plan(digest(b"select"), body.receipt_digest()), Err(PlannerStoreError::LimitExceeded)));
    assert_eq!(store.checkpoint().checkpoint.sequence, 1);
    Ok(())
}

#[test]
fn migration_requires_complete_bodies_and_preserves_original_source() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let (body, receipt) = decision(b"one")?;
    let mut reference = PlannerJournalV1::new();
    reference.record_decision(&receipt)?;
    reference.select_plan(digest(b"select"), &receipt)?;
    let mut store = fixture.open()?;
    assert!(matches!(store.migrate_reference_journal(&reference, &BTreeMap::new()), Err(PlannerStoreError::MissingDecisionBody)));
    assert!(store.records().is_empty());
    let bodies = BTreeMap::from([(body.receipt_digest(), body)]);
    store.migrate_reference_journal(&reference, &bodies)?;
    assert_eq!(store.records()[0].body(), reference.export_bytes());
    assert_eq!(store.selected_plan_digest()?, reference.selected_plan_digest());
    drop(store);
    assert_eq!(fixture.open()?.selected_plan_digest()?, reference.selected_plan_digest());
    Ok(())
}

#[test]
fn migration_rejects_semantically_invalid_legacy_append() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let mut reference = PlannerJournalV1::new();
    reference.append(PlannerJournalKindV1::SelectedPlan, digest(b"select"), digest(b"absent"))?;
    let mut store = fixture.open()?;
    assert!(matches!(store.migrate_reference_journal(&reference, &BTreeMap::new()), Err(PlannerStoreError::InvalidTransition)));
    assert!(store.records().is_empty());
    Ok(())
}

#[test]
fn every_partial_frame_position_stops_at_last_complete_boundary() -> Result<(), Box<dyn Error>> {
    let (body, _) = decision(b"one")?;
    let header = super::codec::Header::genesis(digest(b"store"));
    let entry = super::codec::make_entry(header.store_id, 1, super::RecordKind::Decision, digest(b"record"), body.receipt_digest(), header.base_head, body.canonical_bytes().to_vec())?;
    let frame = super::codec::encode_entry(header.store_id, &entry)?;
    for position in 0..frame.len() {
        let mut bytes = header.encode();
        bytes.extend_from_slice(&frame[..position]);
        let decoded = super::codec::decode_segment(&bytes)?;
        assert!(decoded.entries.is_empty());
        assert_eq!(decoded.complete_bytes, super::codec::HEADER_BYTES);
    }
    Ok(())
}
