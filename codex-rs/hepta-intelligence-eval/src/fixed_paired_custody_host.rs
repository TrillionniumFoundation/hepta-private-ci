//! The original Root custody service's registered, after-CAS numeric producer.
//! Missing actual retention/withdrawal evidence remains incomplete, never Passed.
use crate::fixed_holdout_custody::Witness;
use crate::fixed_holdout_custody::create_private;
use crate::fixed_holdout_custody::private_directory;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::paired_custody_generator::Inputs;
use crate::paired_custody_numeric::Model;
use crate::paired_custody_numeric::{self};
use crate::paired_review_transport::Registration;
use crate::paired_review_transport::{self};
use crate::paired_supervised_host_clock::PairedHostClockV1;
use crate::product_runner::ProductEvaluationRunnerV1;
use crate::protected_paired_provider::ProtectedPairedObservationProviderV1;
use crate::*;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    program_digest: String,
    generator: Source,
    trust_config: Source,
    cycle_approval: Option<Source>,
    root_verifying_key_hex: String,
    holdout_config: Source,
    private_directory: PathBuf,
    witness_path: PathBuf,
    work_directory: PathBuf,
    scorer: Source,
    candidate: Model,
    baseline: Model,
    retention: crate::paired_custody_retention::Config,
    withdrawal: crate::paired_custody_observations::Config,
    absolute_budget_ms: u64,
    operation_expires_at_ms: u64,
}

fn sign(
    trust: &ActivatedLearningTrustV1,
    key: &SigningKey,
    principal: &codex_hepta_learning_ledger::AuthenticatedPrincipalV1,
    id: StableId,
    payload: &[u8],
    now: u64,
) -> HostResult<SignedLearningEvidenceV1> {
    trust.revalidate_at(now)?;
    principal.validate(now)?;
    if Digest32::of_bytes(key.verifying_key().as_bytes()) != principal.signing_key_digest {
        return Err("original Root observer key does not match admitted role".into());
    }
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id,
        principal_id: principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: principal.authority_epoch,
        issued_at: now,
        expires_at: principal.expires_at.min(trust.expires_at()),
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    trust
        .verifier()
        .verify(LearningEvidenceRoleV1::Observer, &evidence, payload, now)?;
    Ok(evidence)
}

pub fn run_fixed_paired_custody(path: &Path) -> HostResult<()> {
    crate::fixed_product_host::root_boundary()?;
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    let program = crate::verify_registered_operational_program_v3(
        &std::env::current_exe()?,
        config.program_digest.parse()?,
    )?;
    if config.schema
        != format!(
            "hepta.fixed-paired-custody-execution-config.v{}",
            config.withdrawal.version()
        )
        || config.program_digest.parse::<Digest32>()? != program
        || !(1..=120_000).contains(&config.absolute_budget_ms)
    {
        return Err("fixed custody program or absolute operation budget".into());
    }
    private_directory(&config.work_directory)?;
    private_directory(&config.private_directory)?;
    let remaining = config
        .operation_expires_at_ms
        .checked_sub(crate::fixed_calibration_host::now_ms()?)
        .filter(|remaining| *remaining > 0)
        .ok_or("original O operation expired")?;
    let deadline = Instant::now()
        .checked_add(Duration::from_millis(
            config.absolute_budget_ms.min(remaining),
        ))
        .ok_or("absolute O budget")?;
    let raw: Value = serde_json::from_slice(&config.generator.read(128 * 1024 * 1024)?)?;
    let trust_wire: ReviewTrustWireV1 = serde_json::from_value(raw["trust"].clone())?;
    if trust_wire.root_verifying_key_hex != config.root_verifying_key_hex {
        return Err("original independently pinned Root trust key".into());
    }
    let (root, distribution) = trust_wire.native()?;
    let observer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| {
            s.principal.principal_id.as_str() == "fixed-custody-observer"
                && s.roles == [LearningEvidenceRoleV1::Observer]
        })
        .ok_or("original O role absent")?
        .clone();
    let trust_bytes = config.trust_config.read(16 * 1024)?;
    let trust_policy: Value = serde_json::from_slice(&trust_bytes)?;
    let approval = config
        .cycle_approval
        .as_ref()
        .map(|source| source.read(32 * 1024))
        .transpose()?;
    verify_original_observer_controller(program, &trust_bytes, approval.as_deref(), &observer)?;
    let key_path = PathBuf::from(
        trust_policy["observer_key_path"]
            .as_str()
            .ok_or("original O key path")?,
    );
    let signing = crate::fixed_calibration_host::key(&key_path, 0)?;
    let trust = activate_learning_trust(
        &root,
        distribution,
        None,
        crate::fixed_calibration_host::now_ms()?,
    )?;
    let inputs = Inputs::read(
        &config.generator,
        &trust,
        crate::fixed_calibration_host::now_ms()?,
    )?;
    if inputs.plan.policy.output_alphabet
        != [
            StableId::new("class-0-support")?,
            StableId::new("class-1-contradict")?,
        ]
    {
        return Err("original binary scorer class order must match the frozen alphabet".into());
    }
    if config.candidate.manifest.digest.parse::<Digest32>()?
        != inputs.plan.runtime.candidate_artifact_digest
        || config.baseline.manifest.digest.parse::<Digest32>()?
            != inputs.plan.runtime.deployed_baseline_digest
        || config.scorer.digest.parse::<Digest32>()? != inputs.plan.runtime.candidate_runtime_digest
        || config.scorer.digest.parse::<Digest32>()? != inputs.plan.runtime.baseline_runtime_digest
    {
        return Err("actual pinned comparator/scorer differs from original G registration".into());
    }
    config.scorer.read(128 * 1024 * 1024)?;
    config.candidate.verify()?;
    config.baseline.verify()?;
    // Read only original protected metadata before CAS, not private gold.
    let witness: Witness =
        serde_json::from_slice(&read_root_review_input(&config.witness_path, 16 * 1024)?)?;
    let holdout_policy: Value = serde_json::from_slice(&config.holdout_config.read(16 * 1024)?)?;
    if witness.config_digest != config.holdout_config.digest
        || holdout_policy["private_directory"]
            != config.private_directory.to_string_lossy().as_ref()
        || holdout_policy["witness_path"] != config.witness_path.to_string_lossy().as_ref()
        || witness.private_gold_digest.parse::<Digest32>()?
            != inputs.plan.frozen.final_holdout_digest
    {
        return Err("original holdout custody/config/manifest".into());
    }
    let registration_path = config.work_directory.join("registration.bin");
    let original: Registration = if registration_path.exists() {
        paired_review_transport::decode(&read_root_review_input(&registration_path, 16 * 1024)?)?
    } else {
        let at = u64::try_from(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_micros(),
        )?;
        let frozen = inputs.plan.frozen_plan();
        let binding = ProductRegistrationBindingV1 {
            registration_digest: Digest32::of_bytes(
                &[config_bytes.as_slice(), frozen.plan_digest.as_array()].concat(),
            ),
            source_graph_digest: inputs.plan.source_graph_digest(),
            deployed_baseline_digest: inputs.plan.runtime.deployed_baseline_digest,
            objective_digest: frozen.objective_digest,
            dataset_digest: frozen.dataset_digest,
            plan_digest: frozen.plan_digest,
            final_holdout_digest: frozen.final_holdout_digest,
            registered_at_unix_micros: at,
        };
        let evidence = sign(
            &trust,
            &signing,
            &observer.principal,
            StableId::new(format!("paired-o.register.{}", frozen.plan_digest))?,
            &paired_registration_signing_payload_v1(&inputs.plan, &binding)?,
            crate::fixed_calibration_host::now_ms()?,
        )?;
        let original = Registration {
            binding,
            generator: inputs.generator.clone(),
            observer: evidence,
        };
        create_private(
            &registration_path,
            &paired_review_transport::encode(&original)?,
        )?;
        original
    };
    let registration = AuthenticatedPairedRegistrationV1::verify(
        &inputs.plan,
        original.binding,
        &original.generator,
        &original.observer,
        trust.verifier(),
        crate::fixed_calibration_host::now_ms()?,
    )?;
    inputs.verify_registration(&registration)?;
    // Missing old-task facts or independent current delivery-denial facts
    // stop before opening/consuming this operation's original holdout CAS.
    crate::paired_custody_retention::preflight(
        &config.retention,
        &inputs,
        &trust,
        crate::fixed_calibration_host::now_ms()?,
    )?;
    let withdrawal_binding = config
        .withdrawal
        .bind(&config.retention.assignment_contract, &inputs.source)?;
    let preflight_dir = config.work_directory.join("withdrawal-preflight");
    create_operation_directory(&preflight_dir)?;
    let withdrawal_before = withdrawal_binding.inspect(&preflight_dir, deadline)?;
    let withdrawal_preflight_receipt = withdrawal_before.receipt;
    if let Err(error) = crate::paired_custody_withdrawal::require_independent_clusters(&inputs.plan)
    {
        println!(
            "{}",
            serde_json::json!({"schema":"hepta.fixed-paired-custody-preflight-insufficient.v1",
            "plan_digest":inputs.plan.frozen.plan_digest.to_string(),
            "original_current_inspection_receipt_digest":withdrawal_preflight_receipt.to_string(),
            "holdout_consumed":false,"qualified":false,"production_activation":false})
        );
        return Err(error);
    }
    if read_root_review_input(path, 32 * 1024)? != config_bytes
        || config.trust_config.read(16 * 1024)? != trust_bytes
        || config
            .cycle_approval
            .as_ref()
            .map(|source| source.read(32 * 1024))
            .transpose()?
            != approval
        || Instant::now() >= deadline
        || crate::fixed_calibration_host::now_ms()? >= config.operation_expires_at_ms
    {
        return Err("original custody source changed or original absolute budget expired".into());
    }
    let cas_path = config.private_directory.join("holdout-cas.bin");
    let binding = witness.binding.parse()?;
    let minimum = FinalHoldoutCasAnchorV1 {
        fence_generation: witness.fence_generation,
        record_count: witness.record_count,
        state_digest: witness.state_digest.parse()?,
    };
    let mut store = LockedFileFinalHoldoutCasStoreV1::recover(
        crate::fixed_holdout_custody::open_retained_private_file(&cas_path)?,
        binding,
        Some(minimum),
    )?;
    let state = store
        .load(binding)?
        .ok_or("original holdout state absent")?;
    let owner = FencedFinalHoldoutOwnerV1::recover(store, binding, state.fence)?;
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let guarded = runner.holdout.protected_observer_provider(
        &cas_path,
        &config.witness_path,
        &config.work_directory.join("observer-cut.json"),
        &registration,
    )?;
    let mut provider = Producer {
        guarded,
        config: &config,
        inputs: &inputs,
        registration: &registration,
        trust: &trust,
        signing: &signing,
        deadline,
        withdrawal_binding,
        withdrawal_before,
    };
    let execution = runner.evaluate_paired_with_clock(
        &registration,
        &mut provider,
        &trust,
        &mut PairedHostClockV1::system(),
    )?;
    let publication =
        encode_paired_review_publication_v1(&inputs.source, &execution, &inputs.trust_wire)?;
    create_private(&config.work_directory.join("execution.json"), &publication)?;
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.fixed-paired-custody-executed.v1","execution_digest":execution.execution_digest().to_string(),
        "publication_digest":Digest32::of_bytes(&publication).to_string(),"holdout_consumed":true,"qualified":false,
        "independent_review_required":true,"authority_grants_any":false,"production_activation":false})
    );
    Ok(())
}

struct Producer<'a> {
    guarded: ProtectedPairedObservationProviderV1,
    config: &'a Config,
    inputs: &'a Inputs,
    registration: &'a AuthenticatedPairedRegistrationV1,
    trust: &'a ActivatedLearningTrustV1,
    signing: &'a SigningKey,
    deadline: Instant,
    withdrawal_binding: crate::paired_custody_observations::Bound,
    withdrawal_before: crate::paired_custody_observations::Batch,
}

fn create_operation_directory(path: &Path) -> HostResult<()> {
    std::fs::create_dir(path)?;
    std::fs::set_permissions(path, std::os::unix::fs::PermissionsExt::from_mode(0o700))?;
    std::fs::File::open(path.parent().ok_or("original operation parent")?)?.sync_all()?;
    Ok(())
}
impl PairedFinalHoldoutProviderV1 for Producer<'_> {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.guarded.manifest_digest()
    }
    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<SignedPairedObservationCutV1, ProductProviderErrorV1> {
        self.guarded.authorize_original_consumption(receipt)?;
        self.produce()
            .map_err(|_| ProductProviderErrorV1::Indeterminate)
    }
}
impl Producer<'_> {
    fn produce(&mut self) -> HostResult<SignedPairedObservationCutV1> {
        let mut clock = PairedHostClockV1::system();
        clock.sample_registered(self.trust, self.registration)?;
        // The first private gold read is below the held original consumed CAS.
        let gold = read_root_review_input(
            &self.config.private_directory.join("gold.json"),
            32 * 1024 * 1024,
        )?;
        if Digest32::of_bytes(&gold) != self.inputs.plan.frozen.final_holdout_digest {
            return Err("original private gold changed after consumption".into());
        }
        let gold: Value = serde_json::from_slice(&gold)?;
        if gold["schema"] != "hepta.source-pinned-private-gold.v1" {
            return Err("original gold schema".into());
        }
        let mut labels = BTreeMap::new();
        for row in gold["tasks"].as_array().ok_or("original gold tasks")? {
            let digest = Digest32::of_bytes(&serde_json::to_vec(&row["features"])?);
            let class = match row["gold"].as_str() {
                Some("SUPPORT") => 0,
                Some("CONTRADICT") => 1,
                _ => return Err("original binary gold policy".into()),
            };
            if labels.insert(digest, class).is_some() {
                return Err("duplicate original private task".into());
            }
        }
        if labels.len() != self.inputs.rows.len()
            || self.inputs.rows.keys().any(|id| !labels.contains_key(id))
        {
            return Err("all and only original gold tasks must match frozen feature graph".into());
        }
        let mut actual = Vec::new();
        // The native scorer's original wall timestamps have millisecond
        // precision. Wait for an actual later bucket, never invent microseconds.
        while clock
            .sample_registered(self.trust, self.registration)?
            .checked_mul(1000)
            .ok_or("actual precision")?
            <= self.registration.binding.registered_at_unix_micros
        {
            if Instant::now() >= self.deadline {
                return Err("original budget expired before numeric effect".into());
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        for index in 0..2 {
            let dir =
                self.config
                    .work_directory
                    .join(if index == 0 { "candidate" } else { "baseline" });
            if !dir.exists() {
                std::fs::create_dir(&dir)?;
                std::fs::set_permissions(
                    &dir,
                    std::os::unix::fs::PermissionsExt::from_mode(0o700),
                )?;
                std::fs::File::open(&self.config.work_directory)?.sync_all()?;
            }
            clock.sample_registered(self.trust, self.registration)?;
            let inputs = self
                .inputs
                .rows
                .values()
                .map(|pair| pair[index].clone())
                .collect::<Vec<_>>();
            actual.push(paired_custody_numeric::execute(
                &self.config.scorer,
                if index == 0 {
                    &self.config.candidate
                } else {
                    &self.config.baseline
                },
                &inputs,
                &dir,
                self.deadline,
            )?);
            clock.sample_registered(self.trust, self.registration)?;
        }
        let mut rows = Vec::new();
        let (retention, retention_receipt) = crate::paired_custody_retention::measure(
            &self.config.retention,
            &self.config.scorer,
            [&self.config.candidate, &self.config.baseline],
            &self.config.work_directory,
            self.inputs,
            self.trust,
            self.registration,
            self.deadline,
        )?;
        let withdrawal_dir = self.config.work_directory.join("withdrawal-final");
        create_operation_directory(&withdrawal_dir)?;
        let withdrawal = self
            .withdrawal_binding
            .inspect(&withdrawal_dir, self.deadline)?;
        let withdrawal_receipt = withdrawal.receipt;
        if !withdrawal.same_original_facts(&self.withdrawal_before) {
            return Err("original withdrawal history or current delivery frontier changed during paired measurement".into());
        }
        let denied = self.withdrawal_binding.values(&withdrawal)?;
        for (index, id) in self.inputs.rows.keys().enumerate() {
            let mut observations = Vec::new();
            for execution in &actual {
                let (bytes, native) = &execution.rows[index];
                let class = native.class();
                let outcome =
                    if let Some(label) = self.inputs.plan.policy.output_alphabet.get(class) {
                        PairedClassObservationV1::Label {
                            class_id: label.clone(),
                            correct: class == labels[id],
                        }
                    } else {
                        PairedClassObservationV1::Censored {
                            reason: StableId::new("outside-registered-output-alphabet")?,
                        }
                    };
                observations.push(PairedNativeObservationV1 {
                    request_id: StableId::new(native.request_id.clone())?,
                    input_digest: native.input_line_digest.parse()?,
                    original_native_observation_digest: Digest32::of_bytes(bytes),
                    started_at_unix_micros: native.executed_at_ms * 1000,
                    finished_at_unix_micros: native
                        .executed_at_ms
                        .checked_mul(1000)
                        .and_then(|v| v.checked_add(native.latency_micros))
                        .ok_or("actual native time")?,
                    original_elapsed_micros: Some(native.latency_micros),
                    outcome,
                });
            }
            let observed_metrics = self
                .inputs
                .plan
                .metrics
                .iter()
                .filter(|metric| matches!(metric.kind, PairedMetricKindV1::ObservedBounded { .. }))
                .map(|metric| {
                    let values = if metric.contract.metric_id
                        == self.inputs.plan.policy.required_evidence_metrics.retention
                    {
                        [Some(retention[id][0]), Some(retention[id][1])]
                    } else if metric.contract.metric_id
                        == self.inputs.plan.policy.required_evidence_metrics.unlearning
                    {
                        // Each task uses its preregistered actual observation.
                        // The native source graph merges shared causal events;
                        // this remains structural denial, not weight forgetting.
                        [Some(denied[id]), Some(denied[id])]
                    } else {
                        [None, None]
                    };
                    PairedObservedMetricV1 {
                        metric_id: metric.contract.metric_id.clone(),
                        candidate: values[0],
                        baseline: values[1],
                    }
                })
                .collect();
            rows.push(PairedTaskObservationV1 {
                source_record_digest: *id,
                candidate: observations.remove(0),
                baseline: observations.remove(0),
                observed_metrics,
            });
        }
        let cut = PairedObservationCutV1 {
            plan_digest: self.inputs.plan.frozen.plan_digest,
            source_graph_digest: self.inputs.plan.source_graph_digest(),
            runtime: self.inputs.plan.runtime.clone(),
            started_at_unix_micros: actual[0].started_ms * 1000,
            finished_at_unix_micros: clock
                .sample_registered(self.trust, self.registration)?
                .checked_mul(1000)
                .and_then(|v| v.checked_add(999))
                .ok_or("actual finish precision")?,
            rows,
            retention_receipt_digests: vec![retention_receipt],
            unlearning_receipt_digest: withdrawal_receipt,
        };
        let now = clock.sample_registered(self.trust, self.registration)?;
        let evidence = sign(
            self.trust,
            self.signing,
            &self.registration.observer,
            StableId::new(format!("paired-o.cut.{}", cut.plan_digest))?,
            &paired_observation_cut_signing_payload_v1(&cut)?,
            now,
        )?;
        let observations = SignedPairedObservationCutV1 {
            cut,
            observer_evidence: evidence,
        };
        let transport = encode_signed_paired_observation_transport_v1(&observations)?;
        create_private(
            &self.config.work_directory.join("observer-cut.json"),
            &transport,
        )?;
        // The original estimator/independent E may still reject the actual
        // accuracy, cost, retention, or causally dependent withdrawal sample.
        Ok(observations)
    }
}

/// Verify the original custody controller's exact program and protected policy
/// bytes. This factual check grants neither key access nor signing authority.
pub fn verify_original_observer_controller(
    program: Digest32,
    trust_bytes: &[u8],
    approval: Option<&[u8]>,
    observer: &codex_hepta_learning_ledger::TrustedLearningSignerV1,
) -> HostResult<()> {
    let trust_policy: Value = serde_json::from_slice(trust_bytes)?;
    let mut controller = Vec::from(program.as_array().as_slice());
    controller.extend_from_slice(Digest32::of_bytes(trust_bytes).as_array());
    if let Some(bytes) = approval {
        controller.extend_from_slice(Digest32::of_bytes(bytes).as_array());
    }
    controller.extend_from_slice(b"root-private-outcome-custody;no-arbitrary-outcome-or-sign-api");
    if trust_policy["schema"] != "hepta.fixed-custody-evaluator-trust.v1"
        || observer.controller_id.as_str()
            != format!(
                "fixed-custody-evaluator.{}",
                Digest32::of_bytes(&controller)
            )
    {
        return Err("actual O executable/source controller does not match admission".into());
    }
    Ok(())
}

#[path = "fixed_paired_custody_write_paths.rs"]
mod write_paths;
pub use write_paths::fixed_paired_execution_write_paths_v1;

pub(crate) fn validate_paired_parameter_execution_config(bytes: &[u8]) -> HostResult<()> {
    let config: Config = serde_json::from_slice(bytes)?;
    if config.schema
        != format!(
            "hepta.fixed-paired-custody-execution-config.v{}",
            config.withdrawal.version()
        )
        || !(1..=120_000).contains(&config.absolute_budget_ms)
        || config.operation_expires_at_ms == 0
    {
        return Err("original paired custody execution configuration".into());
    }
    Ok(())
}
