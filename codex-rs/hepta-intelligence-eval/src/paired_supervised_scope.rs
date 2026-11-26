//! Full graph membership and required non-accuracy evidence dimensions.
use crate::EvaluationDirectionV1;
use crate::PairedMetricKindV1;
use crate::PairedSupervisedErrorV1;
use crate::PairedSupervisedPlanInputsV1;
use codex_hepta_types::Digest32;
use std::collections::BTreeSet;

pub(crate) fn validate_evidence_metrics(
    inputs: &PairedSupervisedPlanInputsV1,
) -> Result<(), PairedSupervisedErrorV1> {
    let required = &inputs.policy.required_evidence_metrics;
    let ids = [
        &required.execution_cost,
        &required.retention,
        &required.unlearning,
    ];
    if ids.into_iter().collect::<BTreeSet<_>>().len() != 3 {
        return Err(PairedSupervisedErrorV1::Binding(
            "paired distinct evidence dimensions",
        ));
    }
    for id in ids {
        let metric = inputs
            .metrics
            .iter()
            .find(|metric| &metric.contract.metric_id == id)
            .ok_or(PairedSupervisedErrorV1::Binding(
                "paired required evidence dimension",
            ))?;
        let semantics_match = if id == &required.execution_cost {
            matches!(
                metric.kind,
                PairedMetricKindV1::ExecutionLatencyMillis { .. }
            ) && metric.contract.direction == EvaluationDirectionV1::Minimize
        } else {
            matches!(metric.kind, PairedMetricKindV1::ObservedBounded { .. })
        };
        if !semantics_match {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired evidence observation semantics",
            ));
        }
    }
    Ok(())
}

pub(crate) fn validate_membership(
    inputs: &PairedSupervisedPlanInputsV1,
) -> Result<Digest32, PairedSupervisedErrorV1> {
    let all: BTreeSet<_> = inputs.source.record_digests().collect();
    let unscored: BTreeSet<_> = inputs.unscored_source_records.iter().copied().collect();
    if unscored.len() != inputs.unscored_source_records.len() {
        return Err(PairedSupervisedErrorV1::Binding(
            "paired duplicate bridge membership",
        ));
    }
    let mut used = BTreeSet::new();
    let mut ordered_folds: Vec<_> = inputs.folds.iter().collect();
    ordered_folds.sort_by_key(|fold| &fold.fold_id);
    let mut bytes = b"hepta.eval.paired-supervised.complete-source-membership.v1".to_vec();
    bytes.extend_from_slice(inputs.source.source_graph_digest().as_array());
    bytes.extend_from_slice(&(ordered_folds.len() as u64).to_be_bytes());
    for fold in ordered_folds {
        crate::push_id(&mut bytes, &fold.fold_id);
        for records in [&fold.training_records, &fold.holdout_records] {
            let sorted: BTreeSet<_> = records.iter().copied().collect();
            if sorted.len() != records.len() {
                return Err(PairedSupervisedErrorV1::Binding(
                    "paired duplicate fold membership",
                ));
            }
            bytes.extend_from_slice(&(sorted.len() as u64).to_be_bytes());
            for record in sorted {
                if !all.contains(&record) || unscored.contains(&record) {
                    return Err(PairedSupervisedErrorV1::Binding(
                        "paired source role overlap/unknown",
                    ));
                }
                used.insert(record);
                bytes.extend_from_slice(record.as_array());
            }
        }
    }
    bytes.extend_from_slice(&(unscored.len() as u64).to_be_bytes());
    for record in unscored {
        if !all.contains(&record) {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired unknown bridge membership",
            ));
        }
        used.insert(record);
        bytes.extend_from_slice(record.as_array());
    }
    if used != all {
        return Err(PairedSupervisedErrorV1::Binding(
            "paired incomplete graph membership",
        ));
    }
    Ok(Digest32::of_bytes(&bytes))
}
