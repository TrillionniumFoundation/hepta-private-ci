use super::*;
use codex_hepta_types::FixedQ32;
use pretty_assertions::assert_eq;

use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::MetricContractV1;
use crate::freeze_cross_fold_plan;

#[derive(Clone)]
struct CacheStore {
    record: FinalHoldoutCasRecordV1,
    cache: Option<FinalHoldoutJournalV1>,
}

impl FinalHoldoutCasStoreV1 for CacheStore {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        if binding != self.record.binding {
            return Err(FinalHoldoutCasStoreError::Rejected);
        }
        Ok(Some(self.record.clone()))
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        if binding != self.record.binding || expected != Some(self.record.state_digest) {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        if self.cache.is_some() {
            self.cache = Some(
                FinalHoldoutJournalV1::from_snapshot(next.journal.clone())
                    .unwrap_or_else(|error| panic!("fixture CAS canonical replay: {error}")),
            );
        }
        self.record = next.clone();
        Ok(())
    }

    fn canonical_journal_cache(&self, binding: Digest32) -> Option<FinalHoldoutJournalV1> {
        if binding == self.record.binding {
            self.cache.clone()
        } else {
            None
        }
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid fixture ID: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fence(generation: u64) -> HoldoutWriterFenceV1 {
    HoldoutWriterFenceV1 {
        owner_id: id("cache-owner"),
        generation,
        lease_digest: digest(&format!("lease:{generation}")),
    }
}

fn plan(name: &str) -> CrossFoldPlanReceiptV1 {
    let final_window = id(&format!("final:{name}"));
    let folds = ["a", "b"]
        .into_iter()
        .map(|label| CrossFoldPartitionV1 {
            fold_id: id(label),
            training_principals: vec![id(&format!("train-principal:{label}"))],
            training_episodes: vec![id(&format!("train-episode:{label}"))],
            training_windows: vec![id(&format!("train-window:{label}"))],
            holdout_principals: vec![id(&format!("hold-principal:{label}"))],
            holdout_episodes: vec![id(&format!("hold-episode:{label}"))],
            holdout_windows: vec![if label == "b" {
                final_window.clone()
            } else {
                id(&format!("hold-window:{name}:{label}"))
            }],
            model_digest: digest(&format!("model:{name}:{label}")),
            predictions_digest: digest(&format!("predictions:{name}:{label}")),
        })
        .collect();
    freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id(name),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        estimand_digest: digest("estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("utility"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds,
        final_holdout_window_id: final_window,
        final_holdout_digest: digest(&format!("holdout:{name}")),
    })
    .unwrap_or_else(|error| panic!("freeze fixture plan: {error}"))
}

fn record(journal: &FinalHoldoutJournalV1) -> FinalHoldoutCasRecordV1 {
    FinalHoldoutCasRecordV1::new(digest("binding"), fence(1), journal.snapshot())
        .unwrap_or_else(|error| panic!("canonical fixture record: {error}"))
}

#[test]
fn cached_same_fence_and_takeover_recovery_match_strict_replay_exactly() {
    let mut journal = FinalHoldoutJournalV1::new();
    for name in ["a", "c", "b", "d"] {
        journal
            .consume(journal.head_digest(), &plan(name))
            .unwrap_or_else(|error| panic!("consume fixture plan: {error}"));
    }
    let original = record(&journal);
    for generation in [1, 2] {
        let cached = FencedFinalHoldoutOwnerV1::recover(
            CacheStore {
                record: original.clone(),
                cache: Some(journal.clone()),
            },
            original.binding,
            fence(generation),
        )
        .unwrap_or_else(|error| panic!("recover cached owner: {error}"));
        let strict = FencedFinalHoldoutOwnerV1::recover(
            CacheStore {
                record: original.clone(),
                cache: None,
            },
            original.binding,
            fence(generation),
        )
        .unwrap_or_else(|error| panic!("recover strict owner: {error}"));
        assert_eq!(cached.into_store().record, strict.into_store().record);
    }
}

#[test]
fn cached_journal_uses_the_recovered_owners_admission_limit() {
    let mut journal = FinalHoldoutJournalV1::with_record_limit(1)
        .unwrap_or_else(|error| panic!("restricted fixture capacity: {error}"));
    journal
        .consume(journal.head_digest(), &plan("first"))
        .unwrap_or_else(|error| panic!("consume first plan: {error}"));
    let original = record(&journal);
    let mut cached = FencedFinalHoldoutOwnerV1::recover(
        CacheStore {
            record: original.clone(),
            cache: Some(journal),
        },
        original.binding,
        fence(2),
    )
    .unwrap_or_else(|error| panic!("recover restricted cache: {error}"));
    let mut strict = FencedFinalHoldoutOwnerV1::recover(
        CacheStore {
            record: original.clone(),
            cache: None,
        },
        original.binding,
        fence(2),
    )
    .unwrap_or_else(|error| panic!("recover strict owner: {error}"));
    let next = plan("second");
    assert_eq!(cached.consume(&next), strict.consume(&next));
    assert_eq!(cached.into_store().record, strict.into_store().record);
}

#[test]
fn cache_full_snapshot_check_rejects_tamper_that_metadata_digest_cannot_detect() {
    let mut journal = FinalHoldoutJournalV1::new();
    journal
        .consume(journal.head_digest(), &plan("first"))
        .unwrap_or_else(|error| panic!("consume fixture: {error}"));
    let mut malformed = record(&journal);
    malformed.journal.records[0].sequence = 2;
    malformed
        .validate(malformed.binding)
        .unwrap_or_else(|error| panic!("head/count metadata remain valid: {error}"));
    let store = CacheStore {
        record: malformed.clone(),
        cache: Some(journal),
    };
    assert_eq!(
        FencedFinalHoldoutOwnerV1::recover(store, malformed.binding, fence(2)).err(),
        Some(FencedHoldoutError::Corrupt)
    );
}

#[test]
fn sealed_receipt_from_another_prefix_is_rejected_with_or_without_a_cache() {
    let mut canonical = FinalHoldoutJournalV1::new();
    let mut alternate = FinalHoldoutJournalV1::new();
    for (journal, first) in [(&mut canonical, "a"), (&mut alternate, "c")] {
        for name in [first, "b"] {
            journal
                .consume(journal.head_digest(), &plan(name))
                .unwrap_or_else(|error| panic!("consume splicing fixture: {error}"));
        }
    }
    let mut snapshot = canonical.snapshot();
    let last = &mut snapshot.records[1];
    last.use_receipt = alternate.records()[1].use_receipt.clone();
    // Preserve genuine private receipt seals and recompute every public hash.
    // Strict replay must still bind this receipt to the actual earlier registry.
    last.record_digest = Digest32::of_parts(&[
        b"hepta.intelligence-eval.final-holdout-journal.v1",
        &last.sequence.to_be_bytes(),
        last.predecessor_head_digest.as_array(),
        last.plan.plan_digest.as_array(),
        last.use_receipt.use_digest.as_array(),
    ]);
    snapshot.head_digest = last.record_digest;
    let malformed = FinalHoldoutCasRecordV1::new(digest("binding"), fence(1), snapshot)
        .unwrap_or_else(|error| panic!("recompute metadata over spliced history: {error}"));
    for cache in [None, Some(canonical)] {
        let store = CacheStore {
            record: malformed.clone(),
            cache,
        };
        assert_eq!(
            FencedFinalHoldoutOwnerV1::recover(store, malformed.binding, fence(2)).err(),
            Some(FencedHoldoutError::Corrupt)
        );
    }
}
