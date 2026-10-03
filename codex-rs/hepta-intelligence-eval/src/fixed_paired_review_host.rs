//! The existing no-custody E role recomputes original paired observations.
//! No caller-supplied metric values, sign payload or private CAS is accepted.
use crate::fixed_calibration_host::boundary;
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::paired_review_transport::MAX_REVIEW_PUBLICATION_BYTES;
use crate::paired_review_transport::Publication;
use crate::paired_supervised_host_clock::PairedHostClockV1;
use crate::*;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use serde::Deserialize;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    uid: u32,
    gid: u32,
    program_digest: String,
    private_key_path: PathBuf,
    root_verifying_key_hex: String,
    publication_path: PathBuf,
    publication_digest: String,
    scope_digest: String,
    objective_digest: String,
    distribution_generation: u64,
    authority_epoch: u64,
    inaccessible_paths: Vec<PathBuf>,
    #[serde(default)]
    self_iteration_consumer: Option<IterationConsumer>,
    #[serde(default)]
    parameter_evaluation: Option<crate::fixed_parameter_review::ParameterReviewPort>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IterationConsumer {
    path: PathBuf,
    generator_uid: u32,
    canonical_envelope_digest: String,
}

/// Run the fixed independently admitted E program on an immutable original G/O
/// publication. Its output is a review, not a custody or publication receipt.
pub fn run_fixed_paired_review_evaluator(path: &Path) -> HostResult<()> {
    run_review(path, false)
}
/// Same admitted E and original measurement owner, with a full parameter output.
pub fn run_fixed_parameter_review_evaluator_v1(path: &Path) -> HostResult<()> {
    run_review(path, true)
}
fn run_review(path: &Path, parameter_mode: bool) -> HostResult<()> {
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    if parameter_mode != config.parameter_evaluation.is_some()
        || (parameter_mode && config.self_iteration_consumer.is_some())
    {
        return Err("fixed E parameter purpose/configuration mismatch".into());
    }
    if config.schema != "hepta.fixed-paired-review-config.v1"
        || config.uid == 0
        || config.gid == 0
        || config.inaccessible_paths.len() != 5
        || config.distribution_generation == 0
        || config.authority_epoch == 0
    {
        return Err("fixed paired reviewer policy".into());
    }
    let cgroup = boundary(config.uid, config.gid)?;
    let program = Digest32::of_bytes(&read_root_review_input(
        &std::env::current_exe()?,
        128 * 1024 * 1024,
    )?);
    if program != config.program_digest.parse::<Digest32>()? {
        return Err("fixed paired reviewer immutable program".into());
    }
    for inaccessible in &config.inaccessible_paths {
        match File::open(inaccessible) {
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => {
                return Err(
                    "paired E can access custody/another key, or denial is not physical".into(),
                );
            }
        }
    }
    let publication_bytes =
        read_root_review_input(&config.publication_path, MAX_REVIEW_PUBLICATION_BYTES)?;
    if Digest32::of_bytes(&publication_bytes) != config.publication_digest.parse::<Digest32>()? {
        return Err("original paired publication pin".into());
    }
    let publication = Publication::read(&publication_bytes)?;
    if publication.trust.root_verifying_key_hex != config.root_verifying_key_hex
        || publication.trust.scope_digest != config.scope_digest
        || publication.trust.objective_digest != config.objective_digest
        || publication.trust.generation != config.distribution_generation
        || publication.trust.authority_epoch != config.authority_epoch
    {
        return Err("original paired root scope/epoch/generation".into());
    }
    let (root, distribution) = publication.trust.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|signer| signer.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("original independent E admission missing")?
        .clone();
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        &reviewer,
        program,
        &root.verifying_key,
        config.uid,
        config.gid,
        None,
    )?;
    let trust = activate_learning_trust(&root, distribution, None, now_ms()?)?;
    let execution = publication.recompute(&trust, now_ms()?)?;
    let mut clock = PairedHostClockV1::system();
    clock.sample_registered(&trust, &execution.registration)?;
    let admission_now = clock.sample_registered(&trust, &execution.registration)?;
    let generator = trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &execution.registration.generator_evidence,
        execution.registration.plan.frozen.plan_digest.as_array(),
        admission_now,
    )?;
    let observer = trust.verifier().verify(
        LearningEvidenceRoleV1::Observer,
        &execution.observations.observer_evidence,
        &paired_observation_cut_signing_payload_v1(&execution.observations.cut)?,
        admission_now,
    )?;
    for actor in [&generator, &observer] {
        codex_hepta_learning_ledger::verify_independent_roles(
            actor.principal(),
            &reviewer.principal,
            admission_now,
        )?;
        if actor.controller_id() == &reviewer.controller_id {
            return Err("paired E shares an actual G/O controller".into());
        }
    }
    let signing = key(&config.private_key_path, config.uid)?;
    if Digest32::of_bytes(signing.verifying_key().as_bytes())
        != reviewer.principal.signing_key_digest
    {
        return Err("independent paired reviewer key/admission mismatch".into());
    }
    let context = ProductQualificationContextV1 {
        generator: execution.registration.generator.clone(),
        evaluator: reviewer.principal.clone(),
        retention_receipt_digests: execution.observations.cut.retention_receipt_digests.clone(),
        unlearning_receipt_digest: execution.observations.cut.unlearning_receipt_digest,
    };
    let bundle = crate::paired_supervised_qualification::paired_bundle(&execution, &context)?;
    let parameter = config
        .parameter_evaluation
        .map(crate::fixed_parameter_review::ParameterReview::open)
        .transpose()?;
    if let Some(parameter) = &parameter {
        parameter.revalidate(
            &bundle,
            &trust,
            clock.sample_registered(&trust, &execution.registration)?,
        )?;
    }
    let roles: Vec<_> = execution
        .registration
        .plan
        .metrics
        .iter()
        .map(|metric| MetricRoleContractV2 {
            metric_id: metric.contract.metric_id.clone(),
            role: metric.role,
        })
        .collect();
    let payload = paired_evaluation_signing_payload_v1(&execution, &context)?;
    let decision = decide_independently_v2(bundle.clone(), roles.clone(), now_ms()?)?;
    // Final source and clock checks precede the one signing effect. No caller
    // success field substitutes for the Root runner's original held-CAS check.
    if read_root_review_input(path, 32 * 1024)? != config_bytes
        || read_root_review_input(&config.publication_path, MAX_REVIEW_PUBLICATION_BYTES)?
            != publication_bytes
    {
        return Err("paired reviewer protected inputs changed before signing".into());
    }
    let now = clock.sample_registered(&trust, &execution.registration)?;
    execution.verify_current(trust.verifier(), now)?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!(
            "fixed.paired.review.{}",
            execution.execution_digest()
        ))?,
        principal_id: reviewer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: reviewer.principal.scope_digest,
        objective_digest: config.objective_digest.parse()?,
        authority_epoch: reviewer.principal.authority_epoch,
        issued_at: now,
        expires_at: now
            .checked_add(3_600_000)
            .ok_or("paired E expiry")?
            .min(reviewer.principal.expires_at)
            .min(trust.expires_at()),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    crate::signed_evaluation::authenticate(
        &bundle,
        &SignedEvaluationEvidenceV1 {
            generator_plan: execution.registration.generator_evidence.clone(),
            evaluator_bundle: evidence.clone(),
        },
        trust.verifier(),
        &payload,
        now,
    )?;
    let observer = trust.verifier().verify(
        LearningEvidenceRoleV1::Observer,
        &execution.observations.observer_evidence,
        &paired_observation_cut_signing_payload_v1(&execution.observations.cut)?,
        now,
    )?;
    let evaluator =
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Evaluator, &evidence, &payload, now)?;
    codex_hepta_learning_ledger::verify_signed_independent_roles_v1(&observer, &evaluator, now)?;
    let cycle_transport = if let Some(port) = &config.self_iteration_consumer {
        if port.generator_uid == config.uid {
            return Err("independent E cannot own the Generator publication port".into());
        }
        let consumer_bytes = read_self_iteration_role_input_v1(
            &port.path,
            port.generator_uid,
            MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES,
        )?;
        let consumer =
            decode_self_iteration_frozen_consumer_v1(&consumer_bytes, &bundle, &trust, now)?;
        if consumer.canonical_envelope_digest() != Some(port.canonical_envelope_digest.parse()?) {
            return Err("original independently installed canonical window changed".into());
        }
        codex_hepta_learning_ledger::verify_signed_independent_roles_v1(
            consumer.generator(),
            &evaluator,
            now,
        )?;
        let frozen = consumer.frozen_digest();
        let expires_at = consumer.expires_at();
        // The stable installed port carries the original G's exact signed
        // bytes. Root need not rewrite this policy after each model turn.
        let mut current = || -> HostResult<u64> {
            if read_root_review_input(path, 32 * 1024)? != config_bytes
                || read_root_review_input(&config.publication_path, MAX_REVIEW_PUBLICATION_BYTES)?
                    != publication_bytes
            {
                return Err("original paired cycle inputs changed before signing".into());
            }
            if read_self_iteration_role_input_v1(
                &port.path,
                port.generator_uid,
                MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES,
            )? != consumer_bytes
            {
                return Err("original G frozen consumer changed before signing".into());
            }
            let current_now = clock.sample_registered(&trust, &execution.registration)?;
            execution.verify_current(trust.verifier(), current_now)?;
            decode_self_iteration_frozen_consumer_v1(
                &consumer_bytes,
                &bundle,
                &trust,
                current_now,
            )?;
            Ok(current_now)
        };
        let mut bundle_evidence = evidence.clone();
        bundle_evidence.evidence_id = StableId::new(format!("fixed.paired.cycle.bundle.{frozen}"))?;
        bundle_evidence.payload_digest =
            Digest32::of_bytes(&evaluation_signing_payload_v2(&bundle, &roles)?);
        bundle_evidence.issued_at = current()?;
        bundle_evidence.expires_at = evidence.expires_at.min(expires_at);
        bundle_evidence.signature = signing.sign(&bundle_evidence.signing_bytes()).to_bytes();
        let signed = SignedEvaluationEvidenceV1 {
            generator_plan: execution.registration.generator_evidence.clone(),
            evaluator_bundle: bundle_evidence,
        };
        let admission = admit_signed_eligibility_v2(
            bundle.clone(),
            roles.clone(),
            &signed,
            trust.verifier(),
            frozen,
            current()?,
        )?;
        let mut use_attestation = evidence.clone();
        use_attestation.evidence_id = StableId::new(format!("fixed.paired.cycle.use.{frozen}"))?;
        use_attestation.payload_digest =
            Digest32::of_bytes(&self_iteration_evaluation_use_payload_v1(
                frozen,
                admission.decision.authentication_digest,
            ));
        use_attestation.issued_at = current()?;
        use_attestation.expires_at = evidence.expires_at.min(expires_at);
        use_attestation.signature = signing.sign(&use_attestation.signing_bytes()).to_bytes();
        let encoded_at = current()?;
        Some(
            encode_self_iteration_evaluation_transport_v1(
                frozen,
                bundle.clone(),
                roles.clone(),
                signed,
                use_attestation,
                &trust,
                encoded_at,
            )?
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>(),
        )
    } else {
        None
    };
    let parameter_material = if let Some(parameter) = &parameter {
        if read_root_review_input(path, 32 * 1024)? != config_bytes
            || read_root_review_input(&config.publication_path, MAX_REVIEW_PUBLICATION_BYTES)?
                != publication_bytes
        {
            return Err("original parameter E sources changed before signing".into());
        }
        let now = clock.sample_registered(&trust, &execution.registration)?;
        execution.verify_current(trust.verifier(), now)?;
        parameter.revalidate(&bundle, &trust, now)?;
        let mut exact = evidence.clone();
        exact.evidence_id = StableId::new(format!(
            "fixed.parameter.review.{}",
            execution.execution_digest()
        ))?;
        exact.payload_digest = Digest32::of_bytes(&evaluation_signing_payload_v2(&bundle, &roles)?);
        exact.issued_at = now;
        exact.expires_at = exact.expires_at.min(parameter.expiry());
        exact.signature = signing.sign(&exact.signing_bytes()).to_bytes();
        Some(parameter.encode(
            &bundle,
            &roles,
            &SignedEvaluationEvidenceV1 {
                generator_plan: execution.registration.generator_evidence.clone(),
                evaluator_bundle: exact,
            },
            &trust,
            clock.sample_registered(&trust, &execution.registration)?,
        )?)
    } else {
        None
    };
    let mut report = serde_json::json!({
        "schema":"hepta.fixed-paired-independent-review.v1",
        "policy_config_digest":Digest32::of_bytes(&config_bytes).to_string(),
        "publication_digest":Digest32::of_bytes(&publication_bytes).to_string(),
        "execution_digest":execution.execution_digest().to_string(),
        "profile_digest":execution.registration.plan.profile_digest().to_string(),
        "decision_digest":decision.evidence_digest.to_string(),
        "disposition":match decision.disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection=>"eligible_for_original_owner_review",
            IndependentEvaluationDispositionV1::Ineligible=>"rejected",
            IndependentEvaluationDispositionV1::InsufficientEvidence=>"insufficient_evidence",
        },
        "failed_metrics":decision.failed_metrics.iter().map(ToString::to_string).collect::<Vec<_>>(),
        "evaluator_signed_evidence":ReviewEvidenceWireV1::from_native(&evidence),
        "evaluator_uid":config.uid,"evaluator_gid":config.gid,"evaluator_cgroup":cgroup,
        "original_custody_verification_required":true,"qualified":false,
        "authority_grants_any":false,"production_activation":false,
    });
    if let Some(transport) = cycle_transport {
        report["self_iteration_evaluation_transport_hex"] = serde_json::Value::String(transport);
    }
    if let Some(material) = parameter_material {
        report["parameter_evaluation_material_hex"] =
            serde_json::Value::String(crate::fixed_parameter_no_change::hex(&material));
    }
    println!("{report}");
    Ok(())
}
