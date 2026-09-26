//! Independent full-scan oracle for the objective-indexed warm freeze path.
//! Keep this scan-based implementation independent of the new lookup methods.
use super::*;

fn derive_dataset_full_scan(
    ledger: &LearningLedger,
    plan: &DatasetFreezePlanV2,
) -> Result<DerivedDataset, ProductionLedgerError> {
    let head = ledger
        .records()
        .last()
        .ok_or(ProductionLedgerError::Binding("empty ledger"))?;
    let mut episodes = BTreeSet::new();
    for record in ledger.active_records_iter() {
        if let LedgerEvent::AuthenticatedDecisionV2(decision) = &record.event
            && decision.objective_digest == plan.objective_digest
        {
            episodes.insert(decision.episode_id.clone());
        }
    }
    if episodes.is_empty() {
        return Err(ProductionLedgerError::AuthenticatedDecisionRequired);
    }

    let mut source_record_digests = Vec::new();
    let mut correction_digests = Vec::new();
    let mut revocation_digests = Vec::new();
    let mut outcome_watermark = 0_u64;
    let mut pending_outcomes = 0_u32;
    let mut censored_outcomes = 0_u32;
    let mut outcome_episodes = BTreeSet::new();

    for record in ledger.active_records_iter() {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) if episodes.contains(&value.episode_id) => {
                source_record_digests.push(record.event_digest);
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) if episodes.contains(&value.episode_id) => {
                source_record_digests.push(record.event_digest);
                outcome_episodes.insert(value.episode_id.clone());
                outcome_watermark = outcome_watermark.max(value.latest_observable_at);
                match value.terminality {
                    AuthenticatedOutcomeTerminality::Pending => {
                        pending_outcomes = pending_outcomes
                            .checked_add(1)
                            .ok_or(ProductionLedgerError::Binding("pending count"))?;
                    }
                    AuthenticatedOutcomeTerminality::Censored => {
                        censored_outcomes = censored_outcomes
                            .checked_add(1)
                            .ok_or(ProductionLedgerError::Binding("censored count"))?;
                    }
                    AuthenticatedOutcomeTerminality::Terminal => {}
                }
            }
            LedgerEvent::CreditBatchV2(value) if episodes.contains(&value.episode_id) => {
                source_record_digests.push(record.event_digest);
            }
            _ => {}
        }
    }

    let missing_outcomes = episodes
        .len()
        .checked_sub(outcome_episodes.len())
        .ok_or(ProductionLedgerError::Binding("outcome accounting"))?;
    let missing_outcomes = u32::try_from(missing_outcomes)
        .map_err(|_| ProductionLedgerError::Binding("pending count"))?;
    pending_outcomes = pending_outcomes
        .checked_add(missing_outcomes)
        .ok_or(ProductionLedgerError::Binding("pending count"))?;

    for record in ledger.records() {
        match &record.event {
            LedgerEvent::AuthenticatedOutcomeV2(value)
                if episodes.contains(&value.episode_id)
                    && value.correction_predecessor.is_some() =>
            {
                correction_digests.push(record.event_digest);
            }
            LedgerEvent::Revocation(_) | LedgerEvent::UnlearningLineageV1(_) => {
                revocation_digests.push(record.event_digest);
            }
            _ => {}
        }
    }
    if outcome_watermark == 0 {
        return Err(ProductionLedgerError::OutcomeWatermarkRequired);
    }
    source_record_digests.sort_unstable();

    let eligible_frontier = head.sequence.get();
    Ok(DerivedDataset {
        ledger_head_digest: head.chain_digest,
        eligible_frontier,
        outcome_watermark,
        correction_cut_digest: digest_cut(
            b"hepta.learning-ledger.correction-cut.v2",
            &correction_digests,
        ),
        revocation_cut_digest: digest_cut(
            b"hepta.learning-ledger.revocation-cut.v2",
            &revocation_digests,
        ),
        source_record_digests,
        pending_outcomes,
        censored_outcomes,
    })
}

fn assert_full_scan_parity(ledger: &LearningLedger, plan: &DatasetFreezePlanV2) {
    let indexed = derive_dataset_from_core(ledger, plan).unwrap();
    let scanned = derive_dataset_full_scan(ledger, plan).unwrap();
    assert_eq!(indexed.signing_payload(plan), scanned.signing_payload(plan));
    let indexed_active = ledger
        .active_records_for_objective(&plan.objective_digest)
        .map(|record| record.event_digest)
        .collect::<Vec<_>>();
    let episodes = ledger
        .records()
        .iter()
        .filter_map(|record| match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value)
                if value.objective_digest == plan.objective_digest =>
            {
                Some(value.episode_id.clone())
            }
            _ => None,
        })
        .collect::<BTreeSet<_>>();
    let scanned_active = ledger
        .active_records_iter()
        .filter(|record| match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => episodes.contains(&value.episode_id),
            LedgerEvent::AuthenticatedOutcomeV2(value) => episodes.contains(&value.episode_id),
            LedgerEvent::CreditBatchV2(value) => episodes.contains(&value.episode_id),
            _ => false,
        })
        .map(|record| record.event_digest)
        .collect::<Vec<_>>();
    assert_eq!(indexed_active, scanned_active);
    let indexed_revocations = ledger.dataset_revocations().collect::<Vec<_>>();
    let scanned_revocations = ledger
        .records()
        .iter()
        .filter(|record| {
            matches!(
                record.event,
                LedgerEvent::Revocation(_) | LedgerEvent::UnlearningLineageV1(_)
            )
        })
        .collect::<Vec<_>>();
    assert_eq!(indexed_revocations, scanned_revocations);
}

#[test]
fn indexed_freeze_matches_independent_scan_after_growth_correction_revocation_and_replay() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let request = decision();
    let signed = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let head = writer
        .append_decision(Digest32::ZERO, request, &signed, 50)
        .unwrap()
        .chain_digest;
    let observed = outcome("index-base-outcome", "index-base-value", None, 100);
    let signed = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    writer.append_outcome(head, observed, &signed, 50).unwrap();
    let snapshot = writer.snapshot().unwrap();
    let LedgerEvent::AuthenticatedDecisionV2(original_decision) =
        snapshot.records()[0].event.clone()
    else {
        panic!("authenticated decision")
    };
    let LedgerEvent::AuthenticatedOutcomeV2(original_outcome) = snapshot.records()[1].event.clone()
    else {
        panic!("authenticated outcome")
    };
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("index-parity"),
        objective_digest: original_decision.objective_digest,
        inclusion_policy_digest: digest("index-parity-policy"),
    };
    let mut ledger = LearningLedger::from_snapshot(snapshot.clone()).unwrap();
    let mut expected_objective_rows = 2;
    let mut unrelated_source = None;
    for n in 0..384 {
        let mut decision = original_decision.clone();
        decision.record_id = id(&format!("index-decision-{n}"));
        decision.episode_id = id(&format!("index-episode-{n}"));
        let selected = n % 97 == 0;
        if !selected {
            decision.objective_digest = digest("unrelated-objective");
        }
        let mut observed = original_outcome.clone();
        observed.record_id = id(&format!("index-outcome-{n}"));
        observed.outcome_id = id(&format!("index-value-{n}"));
        observed.episode_id = decision.episode_id.clone();
        ledger
            .append(LedgerEvent::AuthenticatedDecisionV2(decision.clone()))
            .unwrap();
        ledger
            .append(LedgerEvent::AuthenticatedOutcomeV2(observed.clone()))
            .unwrap();
        if n == 2 {
            unrelated_source = ledger.records().last().cloned();
        }
        if selected {
            expected_objective_rows += 2;
        }
        if n % 7 == 0 {
            observed.correction_predecessor = Some(observed.outcome_id.clone());
            observed.record_id = id(&format!("index-correction-{n}"));
            observed.outcome_id = id(&format!("index-corrected-value-{n}"));
            observed.value = Some(FixedQ32::from_raw(120));
            ledger
                .append(LedgerEvent::AuthenticatedOutcomeV2(observed.clone()))
                .unwrap();
            if selected {
                expected_objective_rows += 1;
            }
        }
        if n % 11 == 0 {
            ledger
                .append(LedgerEvent::Revocation(crate::Revocation {
                    record_id: id(&format!("index-revocation-{n}")),
                    target_record_id: observed.record_id,
                    authority_id: id("privacy-owner"),
                    reason_digest: digest("index-withdrawal"),
                }))
                .unwrap();
        }
        if n % 23 == 0 {
            ledger
                .append(LedgerEvent::Revocation(crate::Revocation {
                    record_id: id(&format!("index-decision-revocation-{n}")),
                    target_record_id: decision.record_id,
                    authority_id: id("privacy-owner"),
                    reason_digest: digest("index-decision-withdrawal"),
                }))
                .unwrap();
        }
        assert_eq!(
            ledger.records_for_objective(&plan.objective_digest).count(),
            expected_objective_rows
        );
        if n % 32 == 0 {
            assert_full_scan_parity(&ledger, &plan);
        }
    }
    let source = unrelated_source.unwrap();
    ledger
        .append(LedgerEvent::UnlearningLineageV1(
            crate::UnlearningLineageEventV1 {
                record_id: id("index-unlearning-record"),
                lineage_id: id("index-unlearning-lineage"),
                source_record_id: source.event.record_id().clone(),
                source_event_digest: source.event_digest,
                dataset_snapshot_id: id("index-unrelated-dataset"),
                dataset_digest: digest("index-unrelated-dataset"),
                artifact_id: id("index-unrelated-artifact"),
                authority_id: id("privacy-owner"),
                reason_digest: digest("index-unlearning-reason"),
                authentication_digest: digest("index-unlearning-authentication"),
            },
        ))
        .unwrap();
    assert_full_scan_parity(&ledger, &plan);
    let before = ledger.snapshot();
    ledger.append(snapshot.records()[0].event.clone()).unwrap();
    assert_eq!(ledger.snapshot(), before);
    assert_eq!(
        ledger.records_for_objective(&plan.objective_digest).count(),
        expected_objective_rows
    );
    let recovered = LearningLedger::from_snapshot(before).unwrap();
    assert_full_scan_parity(&recovered, &plan);
    assert_eq!(
        derive_dataset_from_core(&ledger, &plan)
            .unwrap()
            .signing_payload(&plan),
        derive_dataset_from_core(&recovered, &plan)
            .unwrap()
            .signing_payload(&plan)
    );
}
