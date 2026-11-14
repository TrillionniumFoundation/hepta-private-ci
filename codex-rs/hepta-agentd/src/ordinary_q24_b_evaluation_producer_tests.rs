//! The real independent Source callback. Its Generator signs label-free
//! policies before any final business observations; its separate Observer
//! signs the measured source afterwards. Evaluator authority stays in Root.
#![cfg(test)]

use std::fs::File;
use std::io;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::NeuronFeatureRequestV1;
use codex_hepta_neuron::NeuronFeatureTerminalStatusV1;
use codex_hepta_neuron::NeuronFeatureWorkerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::business;
use super::data::*;
use crate::OriginalBSourceSignedDataV1;
use crate::OriginalRootBCandidateDataV1;

pub(super) fn produce(
    value: &serde_json::Value,
    candidate: &OriginalRootBCandidateDataV1,
) -> io::Result<OriginalBSourceSignedDataV1> {
    let data: ProducerData = serde_json::from_value(value.clone()).map_err(io::Error::other)?;
    let end = candidate.original_end();
    let lineage = candidate
        .candidate_bundle()
        .training_lineage
        .as_ref()
        .ok_or_else(|| io::Error::other("actual candidate lineage missing"))?;
    let directory = std::fs::symlink_metadata(&data.business_directory)?;
    if data.schema != 1
        || candidate.initial().into_array() != data.initial
        || candidate.binding()
            != Digest32::of_parts(&[b"hepta.root.independent-b.custodian.v1\0", &data.initial])
        || candidate.scope().is_zero()
        || candidate.training_head().is_zero()
        || lineage.evaluation_profile.into_array() != data.protocol
        || lineage.source_bundle.into_array() != data.baseline_bundle
        || candidate
            .baseline_bundle()
            .digest()
            .map_err(io::Error::other)?
            .into_array()
            != data.baseline_bundle
        || data
            .training
            .iter()
            .any(|row| row.observed_at_seconds > data.training_watermark)
        || data.training_watermark > candidate.registered_at_seconds()
        || data.cohort.len() != ROWS
        || !directory.is_dir()
        || directory.uid() != 60002
        || directory.mode() & 0o7777 != 0o700
        || Instant::now() >= end
    {
        return Err(io::Error::other(
            "original independent producer binding differs",
        ));
    }
    for row in &data.training {
        business::require_earlier_row(&data.business_directory, data.case, row)?;
    }
    let baseline_action = actual_policy(&data, candidate, PolicyArm::Baseline)?;
    let candidate_action = actual_policy(&data, candidate, PolicyArm::Candidate)?;
    if baseline_action == candidate_action {
        return Err(io::Error::other(
            "actual models do not separate the preregistered policies",
        ));
    }
    let collected = business::wait_after(
        candidate
            .registered_at_seconds()
            .max(data.evaluation_start.saturating_sub(1)),
        end,
    )?;
    let mut entropy = vec![0; ROWS];
    File::open("/dev/urandom")?.read_exact(&mut entropy)?;
    // Each bit is an original fair binary behavior draw, fixed and signed
    // before outcomes. Neither Q24 output is treated as a probability.
    let heldout = data
        .cohort
        .iter()
        .zip(&entropy)
        .map(|(row, draw)| HeldoutRow {
            decision_id: row.decision.clone(),
            principal_lineage: row.principal.clone(),
            episode_lineage: row.episode.clone(),
            window_id: row.window.clone(),
            cluster_id: row.cluster.clone(),
            decision_at_seconds: collected,
            complete_candidates: true,
            chosen_action: ACTIONS[usize::from(draw & 1)].into(),
            actions: ACTIONS
                .into_iter()
                .map(|action| ActionData {
                    action_id: action.into(),
                    behavior_probability_q32: (ONE / 2) as u64,
                    candidate_probability_q32: if action == candidate_action {
                        ONE as u64
                    } else {
                        0
                    },
                    baseline_probability_q32: if action == baseline_action {
                        ONE as u64
                    } else {
                        0
                    },
                })
                .collect(),
            // These placeholders never leave the producer or enter evaluation.
            // The policy serializer deliberately excludes all three label fields.
            finalized_outcome_q32: 0,
            observed_at_seconds: 0,
            original_outcome_evidence: [0; 32],
        })
        .collect();
    let mut source = SourceData {
        schema: 1,
        purpose: "runtime.learning.independent-b-source.v1",
        objective: data.objective,
        unit_profile: data.unit_profile,
        candidate_bundle: candidate
            .candidate_bundle()
            .digest()
            .map_err(io::Error::other)?
            .into_array(),
        baseline_bundle: data.baseline_bundle,
        original_dataset: lineage.dataset.into_array(),
        registered_at_seconds: candidate.registered_at_seconds(),
        collected_after_seconds: collected,
        training: data.training.clone(),
        heldout,
        snapshot_ids: vec!["ordinary-independent-b-original-observations".into()],
        future_window_ids: vec![FINAL_WINDOW.into()],
    };
    let policy_at = business::now()?;
    let policy_payload = source.policy_payload()?;
    let policy_statement = sign(
        &data,
        LearningEvidenceRoleV1::Generator,
        &policy_payload,
        policy_at,
    )?;
    business::write_once(
        &data.business_directory.join("original-policy.statement"),
        &policy_statement,
    )?;
    business::wait_after(policy_at, end)?;
    for row in &mut source.heldout {
        let (outcome, observed, evidence) = business::observe(
            &data.business_directory,
            data.case,
            &row.decision_id,
            &row.chosen_action,
            end,
        )?;
        if observed <= policy_at || observed > data.outcome_watermark {
            return Err(io::Error::other(
                "actual outcome is outside its original window",
            ));
        }
        row.finalized_outcome_q32 = outcome;
        row.observed_at_seconds = observed;
        row.original_outcome_evidence = evidence;
    }
    if source.policy_payload()? != policy_payload {
        return Err(io::Error::other(
            "original policy changed while observing outcomes",
        ));
    }
    let source = serde_json::to_vec(&source).map_err(io::Error::other)?;
    if source.len() > 1_048_576 || Instant::now() >= end {
        return Err(io::Error::other(
            "original independent source bound or end exceeded",
        ));
    }
    business::write_once(
        &data.business_directory.join("original-source.data"),
        &source,
    )?;
    let observed_payload = [
        b"hepta.root.independent-b.observed-source.v1\0".as_slice(),
        Digest32::of_bytes(&source).as_array(),
    ]
    .concat();
    let observed_statement = sign(
        &data,
        LearningEvidenceRoleV1::Observer,
        &observed_payload,
        business::now()?,
    )?;
    business::write_once(
        &data.business_directory.join("original-observer.statement"),
        &observed_statement,
    )?;
    if Instant::now() >= end {
        return Err(io::Error::other("original independent source end elapsed"));
    }
    Ok(OriginalBSourceSignedDataV1 {
        source,
        observed_statement,
        policy_statement,
    })
}

fn sign(
    data: &ProducerData,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    issued_at: u64,
) -> io::Result<Vec<u8>> {
    let (activation, generator, observer) = data.trust.activate_pinned_genesis(issued_at)?;
    let (signer, secret, evidence_name): (&TrustedLearningSignerV1, _, _) = match role {
        LearningEvidenceRoleV1::Generator => (
            &generator,
            &data.generator_key,
            "original-b-behavior-policy",
        ),
        LearningEvidenceRoleV1::Observer => (
            &observer,
            &data.observer_key,
            "original-b-observed-business",
        ),
        _ => return Err(io::Error::other("source has no other signing role")),
    };
    let key = SigningKey::from_bytes(secret);
    if key.verifying_key().to_bytes() != signer.verifying_key
        || activation.verifier().objective_digest().into_array() != data.objective
        || generator.controller_id == observer.controller_id
    {
        return Err(io::Error::other(
            "fixed original independent source role differs",
        ));
    }
    let expires_at = data.expires_at_seconds.min(signer.principal.expires_at);
    if issued_at >= expires_at {
        return Err(io::Error::other("original source signature expired"));
    }
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(evidence_name).map_err(io::Error::other)?,
        principal_id: signer.principal.principal_id.clone(),
        role,
        trust_digest: activation.verifier().trust_digest(),
        scope_digest: activation.verifier().scope_digest(),
        objective_digest: activation.verifier().objective_digest(),
        authority_epoch: signer.principal.authority_epoch,
        issued_at,
        expires_at,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    activation
        .verifier()
        .verify(role, &signed, payload, issued_at)
        .map_err(io::Error::other)?;
    crate::learning_owner_evidence::encode(payload, &signed).map_err(io::Error::other)
}

enum PolicyArm {
    Baseline,
    Candidate,
}

fn actual_policy(
    data: &ProducerData,
    candidate: &OriginalRootBCandidateDataV1,
    arm: PolicyArm,
) -> io::Result<&'static str> {
    let directory = tempfile::tempdir_in(&data.business_directory)?;
    let original = [
        &data.baseline.base,
        &data.baseline.encoder,
        &data.baseline.heads,
    ];
    for (name, bytes) in ["base", "encoder", "heads"].into_iter().zip(original) {
        business::write_once(&directory.path().join(name), bytes)?;
    }
    let baseline = crate::LoadedCellQ24ModelV1::open_files(crate::CellQ24ModelFilesV1 {
        base: File::open(directory.path().join("base"))?,
        organ_adapter: None,
        cell_adapter: None,
        encoder: File::open(directory.path().join("encoder"))?,
        heads: File::open(directory.path().join("heads"))?,
    })
    .map_err(io::Error::other)?;
    let (model, bundle) = match arm {
        PolicyArm::Candidate => (
            baseline
                .read_single_head_candidate_data(
                    candidate.baseline_bundle(),
                    candidate.candidate_bundle(),
                    crate::CellQ24PrivateHeadV1::Drive { index: 0 },
                    candidate.candidate_heads(),
                )
                .map_err(io::Error::other)?,
            candidate.candidate_bundle(),
        ),
        PolicyArm::Baseline => (baseline, candidate.baseline_bundle()),
    };
    let definition =
        super::super::super::material::definition(&model, bundle).map_err(io::Error::other)?;
    let weights_digest = model.effective_weights_digest();
    let width = model.input_width();
    if data.input.len() != 10 + 8 * width
        || &data.input[..8] != b"HQ24I001"
        || u16::from_le_bytes([data.input[8], data.input[9]]) as usize != width
    {
        return Err(io::Error::other("original benchmark vector differs"));
    }
    let input = data.input[10..]
        .chunks_exact(8)
        .map(|chunk| {
            <[u8; 8]>::try_from(chunk)
                .map(i64::from_le_bytes)
                .map_err(io::Error::other)
        })
        .collect::<io::Result<Vec<_>>>()?;
    let worker = crate::CellQ24FeatureWorkerV1::new(Arc::new(model), bundle, &definition)
        .map_err(io::Error::other)?;
    let observed = worker
        .execute(&NeuronFeatureRequestV1 {
            request_id: StableId::new("ordinary-independent-b-native-policy")
                .map_err(io::Error::other)?,
            generation: bundle.generation,
            model_id: bundle.artifact_id.clone(),
            encoder_digest: bundle.components.encoder,
            head_digest: bundle.components.heads,
            weights_digest,
            input_digest: Digest32::of_bytes(&data.input),
            feature_vector_q24: input,
            expected_output_width: definition.runtime.state_width,
        })
        .map_err(io::Error::other)?;
    if observed.status != NeuronFeatureTerminalStatusV1::Succeeded {
        return Err(io::Error::other("actual native policy did not succeed"));
    }
    let drive = observed
        .drive_q24
        .first()
        .ok_or_else(|| io::Error::other("actual policy output missing"))?;
    // A preregistered deterministic action threshold, not a conversion of a
    // model score into a probability, reward or qualification result.
    Ok(if *drive >= 3 * (1_i64 << 23) {
        "persist"
    } else {
        "skip"
    })
}
