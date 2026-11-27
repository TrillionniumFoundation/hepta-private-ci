//! Verify every original member and the complete signed retention set.
use std::collections::BTreeSet;

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellRuntimeSnapshotV2;
use codex_hepta_types::Digest32;
use serde_json::Value;

use super::super::contract::Context;
use super::Error;
use super::Receipt;
use super::codec::Body;
use super::member;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_owner_evidence;

pub(super) struct Checked {
    pub candidate: Digest32,
    pub material: Digest32,
    pub qualified: bool,
}

pub(super) fn material(
    context: &Context,
    expected: &Receipt,
    bytes: &[u8],
    current: u64,
) -> Result<Checked, Error> {
    let generator = context.authenticate(current)?;
    let body = Body::decode(bytes)?;
    let snapshot = decode_original_owner_snapshot_v1(&body.snapshot)?;
    let (payload, signed) = learning_owner_evidence::decode(&body.evaluation)?;
    if payload != learning_iteration_receipt_signing_bytes_v1(expected.receipt())? {
        return Err(Error::Binding(
            "exact original Evaluation payload in material",
        ));
    }
    let actual = super::super::wire::authenticate_completed(context, snapshot, signed, current)?;
    if &actual != expected
        || body.context != super::wire::binding(context, expected, current)?
        || body.members.len() != context.registration.retention().len() + 1
    {
        return Err(Error::Binding(
            "original material full T/E signatures and complete panel",
        ));
    }
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(context.training.clone())?;
    let candidate = coordinator
        .candidate()
        .ok_or(Error::Binding("actual original Candidate"))?;
    let training_receipt = context
        .training
        .receipts
        .last()
        .ok_or(Error::Binding("actual Training"))?;
    let training_digest = Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(
        training_receipt,
    )?);
    let mut panel = b"hepta.agentd.original-cell-evaluation-panel-current.v1\0".to_vec();
    for digest in [
        context.registration.evaluation_profile(),
        context.training.head_digest,
        context.scope.binding(),
    ] {
        panel.extend_from_slice(digest.as_array());
    }
    panel.extend_from_slice(&(body.members.len() as u64).to_be_bytes());
    let mut runs = BTreeSet::new();
    let mut namespaces = BTreeSet::new();
    let mut checked_members = Vec::with_capacity(body.members.len());
    let mut model_material = None;
    let mut all_policies_bound = true;
    for (index, (raw, task)) in body
        .members
        .iter()
        .zip(
            std::iter::once(context.registration.primary()).chain(context.registration.retention()),
        )
        .enumerate()
    {
        let checked = member::verify(raw, context, task, &generator, current)?;
        let cohort = member::cohort(raw, &checked, context, task, &generator, current)?;
        all_policies_bound &= cohort.policy_bound;
        if !namespaces.insert(raw.execution_namespace)
            || !namespaces.insert(raw.qualification_namespace)
        {
            return Err(Error::Binding("distinct original panel member namespaces"));
        }
        // Parse only public evidence data and original snapshot preimages.
        // No Cell journal, plan, runner, temporal receipt or qualification
        // seal is deserialized or recreated here.
        let record: Value = serde_json::from_slice(&raw.record)?;
        if record.get("cost_scope").and_then(Value::as_str)
            != Some("task_ledgers_before_final_holdout")
            || digest(&record["learning_evaluation_profile"])?
                != context.registration.evaluation_profile()
            || digest(&record["comparison"]["candidate"]["training_receipt_digest"])?
                != training_digest
            || record["comparison"]["candidate"]["participant_id"].as_str()
                != Some(candidate.artifact_id.as_str())
            || record["comparison"]["fixed_expert"]["participant_id"].as_str()
                != Some(
                    context
                        .training
                        .request
                        .selected_bundle
                        .artifact_id
                        .as_str(),
                )
        {
            return Err(Error::Binding(
                "full original comparison and Training evidence",
            ));
        }
        let manifests: [CellBackendManifestV2; 2] = [
            serde_json::from_value(record["candidate"]["manifest"].clone())?,
            serde_json::from_value(record["fixed_expert"]["manifest"].clone())?,
        ];
        let cuts = [
            digest(&record["candidate"]["journal_cut"])?,
            digest(&record["fixed_expert"]["journal_cut"])?,
        ];
        let snapshots: [CellRuntimeSnapshotV2; 2] = serde_json::from_slice(&raw.snapshots)?;
        if serde_json::to_vec(&snapshots)? != raw.snapshots {
            return Err(Error::Binding("canonical complete original Cell snapshots"));
        }
        for (((manifest, bundle), arm), snapshot) in manifests
            .iter()
            .zip([candidate, &context.training.request.selected_bundle])
            .zip(["candidate", "fixed_expert"])
            .zip(&snapshots)
        {
            crate::cell_composed_q24::validate_manifest(bundle, manifest)
                .map_err(|_| Error::Binding("complete original Q24 generation manifest"))?;
            // This is the existing signed arm commitment, with its original
            // domain and full mutable state. There is no new scope assertion.
            if snapshot
                .digest()
                .map_err(crate::OriginalCellEvaluationPanelErrorV1::from)?
                != digest(&record[arm]["snapshot_digest"])?.into_array()
                || snapshot.manifest_digest
                    != manifest
                        .digest()
                        .map_err(crate::OriginalCellEvaluationPanelErrorV1::from)?
                || snapshot.state.len() > manifest.max_state_bytes as usize
                || snapshot.prefix.len() > manifest.max_prefix_bytes as usize
            {
                return Err(Error::Binding(
                    "same signed original Cell snapshot preimage",
                ));
            }
            if digest(&record[arm]["cost"]["identity"]["task_digest"])? != task.task_digest {
                return Err(Error::Binding(
                    "same registered actual B task for both arms",
                ));
            }
        }
        if cuts[0].is_zero() || cuts[1].is_zero() || cuts[0] == cuts[1] {
            return Err(Error::Binding(
                "distinct original evaluated Cell journal cuts",
            ));
        }
        let member_runs: BTreeSet<_> = snapshots
            .iter()
            .map(|snapshot| snapshot.scope.run_id.as_str())
            .collect();
        for run in member_runs {
            if run == context.training.request.source_run_id.as_str()
                || !runs.insert(run.to_owned())
            {
                return Err(Error::Binding("independent actual B and retention runs"));
            }
        }
        for value in [
            raw.binding,
            cohort.binding,
            cuts[0],
            cuts[1],
            checked.execution,
            checked.publication,
            checked.qualification,
            checked.authentication,
        ] {
            panel.extend_from_slice(value.as_array());
        }
        if index == 0 {
            model_material = Some(
                crate::cell_q24_model_material::original_model_material_digest(
                    training_receipt.evidence_digest,
                    &manifests[0],
                    &manifests[1],
                    cuts[0],
                    cuts[1],
                    checked.plan,
                    checked.qualification,
                )
                .map_err(|_| Error::Binding("original Model material encoding"))?,
            );
        } else if !checked.retention.is_empty() {
            return Err(Error::Binding(
                "original retention leaf cannot substitute another panel",
            ));
        }
        checked_members.push(checked);
    }
    let primary = &checked_members[0];
    let mut retention = checked_members
        .iter()
        .skip(1)
        .map(|member| member.qualification)
        .collect::<Vec<_>>();
    retention.sort_unstable();
    if retention.is_empty()
        || retention.windows(2).any(|pair| pair[0] == pair[1])
        || primary.retention != retention
        || Digest32::of_bytes(&panel) != body.panel
        || primary.qualification != expected.receipt().evidence_digest
        || primary.evaluator_issued_at != expected.receipt().observed_unix_seconds
    {
        return Err(Error::Binding(
            "original E binds the entire actual signed retention panel",
        ));
    }
    // The original Evaluation signature records the primary Product verdict.
    // Admission additionally requires every authenticated retention verdict;
    // a known Ineligible result remains observable and is never a retention pass.
    let qualified = all_policies_bound && checked_members.iter().all(|member| member.qualified);
    let disposition = if primary.qualified {
        LearningEvaluationDispositionV1::Qualified
    } else {
        LearningEvaluationDispositionV1::NoUpdate
    };
    let candidate = candidate
        .digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    if expected.receipt().observation
        != (LearningIterationObservationV1::Evaluation {
            candidate_bundle: candidate,
            evaluation_profile: context.registration.evaluation_profile(),
            disposition,
        })
    {
        return Err(Error::Binding(
            "same original Runner decision and Evaluation result",
        ));
    }
    Ok(Checked {
        candidate,
        material: model_material.ok_or(Error::CommitUncertain)?,
        qualified,
    })
}

fn digest(value: &Value) -> Result<Digest32, Error> {
    let bytes: [u8; 32] = serde_json::from_value(value.clone())?;
    Ok(Digest32::from_array(bytes))
}
