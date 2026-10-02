//! Complete the original custody execution with the independently produced E
//! signature and the existing FULL file sink. No model or gold is opened here.
use crate::fixed_holdout_custody::Witness;
use crate::fixed_holdout_custody::create_private;
use crate::fixed_holdout_custody::private_directory;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::paired_review_transport::MAX_REVIEW_PUBLICATION_BYTES;
use crate::paired_review_transport::Publication;
use crate::paired_supervised_host_clock::PairedHostClockV1;
use crate::product_runner::ProductEvaluationRunnerV1;
use crate::*;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    program_digest: String,
    root_verifying_key_hex: String,
    execution: Source,
    evaluator_result: Source,
    private_directory: PathBuf,
    witness_path: PathBuf,
    evidence_path: PathBuf,
    ack_path: PathBuf,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Review {
    schema: String,
    policy_config_digest: String,
    publication_digest: String,
    execution_digest: String,
    profile_digest: String,
    decision_digest: String,
    disposition: String,
    failed_metrics: Vec<String>,
    evaluator_signed_evidence: ReviewEvidenceWireV1,
    evaluator_uid: u32,
    evaluator_gid: u32,
    evaluator_cgroup: String,
    original_custody_verification_required: bool,
    qualified: bool,
    authority_grants_any: bool,
    production_activation: bool,
}

pub fn finish_fixed_paired_custody(path: &Path) -> HostResult<()> {
    crate::fixed_product_host::root_boundary()?;
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-paired-custody-finish-config.v1"
        || Digest32::of_bytes(&read_root_review_input(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
        )?) != config.program_digest.parse::<Digest32>()?
        || config.evidence_path.parent() == config.ack_path.parent()
    {
        return Err("fixed custody finish program or independently retained ACK parent".into());
    }
    private_directory(&config.private_directory)?;
    private_directory(
        config
            .evidence_path
            .parent()
            .ok_or("original evidence parent")?,
    )?;
    private_directory(config.ack_path.parent().ok_or("original ACK parent")?)?;
    let original = config.execution.read(MAX_REVIEW_PUBLICATION_BYTES)?;
    let publication = Publication::read(&original)?;
    if publication.trust.root_verifying_key_hex != config.root_verifying_key_hex {
        return Err("pinned original Root trust key".into());
    }
    let (root, distribution) = publication.trust.native()?;
    let trust = activate_learning_trust(
        &root,
        distribution,
        None,
        crate::fixed_calibration_host::now_ms()?,
    )?;
    let execution = publication.recompute(&trust, crate::fixed_calibration_host::now_ms()?)?;
    let mut clock = PairedHostClockV1::system();
    clock.sample_registered(&trust, &execution.registration)?;
    let witness: Witness =
        serde_json::from_slice(&read_root_review_input(&config.witness_path, 16 * 1024)?)?;
    let binding = witness.binding.parse()?;
    let cas_path = config.private_directory.join("holdout-cas.bin");
    let mut store = LockedFileFinalHoldoutCasStoreV1::recover(
        crate::fixed_holdout_custody::open_retained_private_file(&cas_path)?,
        binding,
        Some(FinalHoldoutCasAnchorV1 {
            fence_generation: witness.fence_generation,
            record_count: witness.record_count,
            state_digest: witness.state_digest.parse()?,
        }),
    )?;
    let state = store
        .load(binding)?
        .ok_or("original consumed owner is absent")?;
    let owner = FencedFinalHoldoutOwnerV1::recover(store, binding, state.fence)?;
    let runner = ProductEvaluationRunnerV1::new(owner);
    let mut held = runner.holdout.protected_observer_provider(
        &cas_path,
        &config.witness_path,
        &config.execution.path,
        &execution.registration,
    )?;
    held.authorize_original_consumption(&execution.holdout)?;
    let review_bytes = config.evaluator_result.read(128 * 1024)?;
    let review: Review = serde_json::from_slice(&review_bytes)?;
    if review.schema != "hepta.fixed-paired-independent-review.v1"
        || review.policy_config_digest.parse::<Digest32>()?.is_zero()
        || review.publication_digest != config.execution.digest
        || review.execution_digest != execution.execution_digest.to_string()
        || review.profile_digest != execution.registration.plan.profile_digest().to_string()
        || review.decision_digest.parse::<Digest32>()?.is_zero()
        || ![
            "eligible_for_original_owner_review",
            "rejected",
            "insufficient_evidence",
        ]
        .contains(&review.disposition.as_str())
        || review.failed_metrics.len() > 128
        || review.evaluator_uid == 0
        || review.evaluator_gid == 0
        || !review
            .evaluator_cgroup
            .contains("hepta-fixed-calibration-eval-")
        || !review.original_custody_verification_required
        || review.qualified
        || review.authority_grants_any
        || review.production_activation
    {
        return Err("original E result is mismatched or claims unsupported authority".into());
    }
    let evidence = review.evaluator_signed_evidence.native()?;
    let (_, distribution) = publication.trust.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| {
            s.principal.principal_id == evidence.principal_id
                && s.principal.principal_id.as_str() == "fixed-no-custody-reviewer"
                && s.roles == [codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator]
        })
        .ok_or("original independent E role absent")?;
    let context = ProductQualificationContextV1 {
        generator: execution.registration.generator.clone(),
        evaluator: reviewer.principal.clone(),
        retention_receipt_digests: execution.observations.cut.retention_receipt_digests.clone(),
        unlearning_receipt_digest: execution.observations.cut.unlearning_receipt_digest,
    };
    trust.verifier().verify(
        codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator,
        &evidence,
        &paired_evaluation_signing_payload_v1(&execution, &context)?,
        clock.sample_registered(&trust, &execution.registration)?,
    )?;
    let expected = decide_independently_v2(
        runner.paired_qualification_bundle(&execution, &context)?,
        execution
            .registration
            .plan
            .metrics
            .iter()
            .map(|m| MetricRoleContractV2 {
                metric_id: m.contract.metric_id.clone(),
                role: m.role,
            })
            .collect(),
        clock.sample_registered(&trust, &execution.registration)?,
    )?;
    let disposition = match expected.disposition {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection => {
            "eligible_for_original_owner_review"
        }
        IndependentEvaluationDispositionV1::Ineligible => "rejected",
        IndependentEvaluationDispositionV1::InsufficientEvidence => "insufficient_evidence",
    };
    if expected.evidence_digest.to_string() != review.decision_digest
        || disposition != review.disposition
        || expected
            .failed_metrics
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            != review.failed_metrics
    {
        return Err(
            "original E descriptive decision differs from independently recomputed native decision"
                .into(),
        );
    }
    let signed_request = serde_json::to_vec(
        &serde_json::json!({"schema":"hepta.fixed-paired-original-signed-request.v1",
        "original_execution":serde_json::from_slice::<serde_json::Value>(&original)?,"original_independent_review":serde_json::from_slice::<serde_json::Value>(&review_bytes)?}),
    )?;
    if signed_request.len() > 16 * 1024 * 1024
        || read_root_review_input(path, 32 * 1024)? != config_bytes
        || config.execution.read(MAX_REVIEW_PUBLICATION_BYTES)? != original
        || config.evaluator_result.read(128 * 1024)? != review_bytes
    {
        return Err(
            "original finish source changed or complete signed request exceeds bound".into(),
        );
    }
    let recovery = if config.ack_path.exists() {
        let bytes = read_root_review_input(&config.ack_path, 65)?;
        if bytes.len() != 65 || bytes[64] != b'\n' {
            return Err("original ACK is corrupt".into());
        }
        ProductPublicationRecoveryV1::Acknowledged(std::str::from_utf8(&bytes[..64])?.parse()?)
    } else {
        ProductPublicationRecoveryV1::Unacknowledged
    };
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
        .open(&config.evidence_path)?;
    let meta = file.metadata()?;
    let named = std::fs::symlink_metadata(&config.evidence_path)?;
    if meta.uid() != 0
        || meta.mode() & 0o077 != 0
        || meta.nlink() != 1
        || !meta.is_file()
        || (meta.dev(), meta.ino(), meta.mode()) != (named.dev(), named.ino(), named.mode())
    {
        return Err("original evidence file is not private canonical Root custody".into());
    }
    let mut sink = LockedFileProductEvidenceSinkV1::open(
        file,
        execution.execution_digest(),
        &signed_request,
        recovery,
    )?;
    let qualification = runner.qualify_paired_with_clock(
        &execution,
        &context,
        &SignedEvaluationEvidenceV1 {
            generator_plan: execution.registration.generator_evidence.clone(),
            evaluator_bundle: evidence,
        },
        &trust,
        &mut sink,
        &mut clock,
    )?;
    qualification.validate_integrity()?;
    std::fs::File::open(config.evidence_path.parent().ok_or("evidence parent")?)?.sync_all()?;
    let ack = format!("{}\n", qualification.publication_digest).into_bytes();
    if config.ack_path.exists() {
        if read_root_review_input(&config.ack_path, 65)? != ack {
            return Err("original publication ACK conflicts".into());
        }
    } else {
        create_private(&config.ack_path, &ack)?;
    }
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.fixed-paired-original-custody-qualified.v1","execution_digest":qualification.paired_execution_digest.to_string(),
        "profile_digest":qualification.paired_profile_digest.to_string(),"decision_digest":qualification.decision.decision.evidence_digest.to_string(),
        "publication_digest":qualification.publication_digest.to_string(),"evidence_digest":qualification.evidence_digest.to_string(),
        "eligible_for_independent_selection":qualification.decision.decision.disposition==IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        "original_full_sink_acknowledged":true,"authority_grants_any":false,"production_activation":false})
    );
    Ok(())
}
