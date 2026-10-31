//! Real completed v6 outcomes through the existing final-holdout CAS owner.
//! This local posthoc replay grants no qualification or promotion authority.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;
use std::cell::Cell;
use std::cell::RefCell;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::rc::Rc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[path = "support/generation_paired_fixture.rs"]
mod support;
use support::BASELINE;
use support::CANDIDATE;
use support::Fixture;
use support::digest;
use support::id;

#[derive(Clone)]
struct SharedStore(Rc<RefCell<LockedFileFinalHoldoutCasStoreV1>>);
impl FinalHoldoutCasStoreV1 for SharedStore {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        self.0.borrow_mut().load(binding)
    }
    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        self.0
            .borrow_mut()
            .compare_and_swap(binding, expected, next)
    }
}

struct Provider {
    plan: FrozenPairedPlanV1,
    data: PairedDataV1,
    witness: SignedLearningEvidenceV1,
    store: SharedStore,
    binding: Digest32,
    releases: Rc<Cell<u64>>,
}
impl PairedFinalHoldoutProviderV1 for Provider {
    fn identities(&mut self) -> Result<(Digest32, Digest32), ProductProviderErrorV1> {
        Ok((
            self.plan.spec().holdout_digest,
            self.plan.spec().outcome_bundle_digest,
        ))
    }
    fn release_after_consumption(
        &mut self,
        receipt: &PairedHoldoutJournalReceiptV1,
    ) -> Result<(PairedDataV1, SignedLearningEvidenceV1), ProductProviderErrorV1> {
        receipt
            .validate(&self.plan)
            .map_err(|_| ProductProviderErrorV1::Rejected)?;
        let committed = self
            .store
            .load(self.binding)
            .map_err(|_| ProductProviderErrorV1::Rejected)?
            .ok_or(ProductProviderErrorV1::Rejected)?;
        if !committed
            .journal
            .records
            .iter()
            .any(|r| r.record_digest == receipt.record_digest)
        {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.releases.set(self.releases.get() + 1);
        Ok((self.data.clone(), self.witness.clone()))
    }
}

struct FileSink(PathBuf);
impl PairedEvaluationEvidenceSinkV1 for FileSink {
    fn persist_paired(
        &mut self,
        decision: &SignedPairedEvaluationV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        // Commit the stable signed evaluation, excluding the transport-only
        // first-use/retry marker. Readback is compared to a recovered typed
        // owner derivation; a Debug representation is never a trusted decoder.
        let bytes = format!(
            "hepta.local-paired-signed-witness.v1\n{:?}\n{:?}\n{}\n{}\n{}\n{:?}\n{:?}\n{:?}\n{}\n{}\n",
            decision.evaluation.holdout.plan, decision.evaluation.statistics,
            decision.evaluation.holdout.record_digest, decision.evaluation.outcome_bundle_digest,
            decision.evaluation.execution_digest, decision.generator_plan,
            decision.observer_outcomes, decision.evaluator_receipt,
            decision.trust_digest, decision.authentication_digest,
        ).into_bytes();
        match OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&self.0)
        {
            Ok(mut file) => {
                file.write_all(&bytes)
                    .and_then(|()| file.sync_all())
                    .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
                File::open(
                    self.0
                        .parent()
                        .ok_or(ProductEvidenceSinkErrorV1::Rejected)?,
                )
                .and_then(|file| file.sync_all())
                .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                if std::fs::read(&self.0).map_err(|_| ProductEvidenceSinkErrorV1::Rejected)?
                    != bytes
                {
                    return Err(ProductEvidenceSinkErrorV1::Rejected);
                }
            }
            Err(_) => return Err(ProductEvidenceSinkErrorV1::Rejected),
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

const ROLES: [LearningEvidenceRoleV1; 3] = [
    LearningEvidenceRoleV1::Generator,
    LearningEvidenceRoleV1::Observer,
    LearningEvidenceRoleV1::Evaluator,
];
fn verifier(objective: Digest32, scope: Digest32, now: u64) -> Result<LearningEvidenceVerifierV1> {
    let signers = ROLES
        .iter()
        .enumerate()
        .map(|(index, role)| {
            let key = SigningKey::from_bytes(&[201 + index as u8; 32])
                .verifying_key()
                .to_bytes();
            Ok(TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(&format!("local-paired-fixture-role-{index}"))?,
                    credential_chain_digest: digest(&format!("local-fixture-only:{scope}:{index}")),
                    signing_key_digest: Digest32::of_bytes(&key),
                    scope_digest: scope,
                    authority_epoch: 1,
                    authenticated_at: now,
                    expires_at: now + 3600,
                },
                controller_id: id(&format!("local-paired-fixture-controller-{index}"))?,
                verifying_key: key,
                roles: vec![*role],
                revoked_at: None,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 1,
        signers,
    })?)
}
fn sign(
    verifier: &LearningEvidenceVerifierV1,
    index: usize,
    payload: &[u8],
    now: u64,
) -> Result<SignedLearningEvidenceV1, SignedEvidenceError> {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("paired-fixture-evidence-{index}"))
            .map_err(|_| SignedEvidenceError::ContextMismatch)?,
        principal_id: id(&format!("local-paired-fixture-role-{index}"))
            .map_err(|_| SignedEvidenceError::ContextMismatch)?,
        role: ROLES[index],
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: 1,
        issued_at: now,
        expires_at: now + 3600,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[201 + index as u8; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    Ok(evidence)
}
fn interval(value: &Option<PairedBoundedIntervalV1>) -> Value {
    value.as_ref().map_or(Value::Null, |x| json!({
        "mean_floor_q32": x.mean_floor.raw(), "mean_ceiling_q32": x.mean_ceiling.raw(),
        "lower_q32": x.lower.raw(), "upper_q32": x.upper.raw(), "radius_q32": x.conservative_radius.raw(),
        "mean_floor": x.mean_floor.raw() as f64 / 4294967296.0, "mean_ceiling": x.mean_ceiling.raw() as f64 / 4294967296.0,
        "lower": x.lower.raw() as f64 / 4294967296.0, "upper": x.upper.raw() as f64 / 4294967296.0,
    }))
}

#[test]
#[ignore = "requires independently pinned completed-run rows and exported engineering fixture"]
fn real_paired_generation_outcomes_consume_then_release_derive_sign_persist_and_recover()
-> Result<()> {
    let path = PathBuf::from(
        std::env::var_os("HEPTA_PAIRED_OWNER_FIXTURE").context("prepare paired_fixture.py")?,
    );
    let expected: Digest32 = std::env::var("HEPTA_PAIRED_OWNER_FIXTURE_SHA256")?.parse()?;
    let expected_rows: Digest32 = std::env::var("HEPTA_PAIRED_SOURCE_ROWS_SHA256")?.parse()?;
    let fixture = Fixture::load(&path, expected, expected_rows)?;
    assert!(Fixture::load(&path, expected, digest("changed original row pin")).is_err());
    let importer = Digest32::of_bytes(&std::fs::read(std::env::current_exe()?)?);
    let directory = tempfile::Builder::new()
        .prefix("paired-owner-evidence-")
        .tempdir_in(path.parent().context("fixture parent")?)?
        .keep();
    let journal_path = directory.join("holdout.bin");
    let binding = digest(&format!("hepta.v6.local-paired-owner.v1:{expected}"));
    let fence = |generation| -> Result<HoldoutWriterFenceV1> {
        Ok(HoldoutWriterFenceV1 {
            owner_id: id("local-paired-fixture-owner")?,
            generation,
            lease_digest: digest(&format!("fixture-lease:{binding}:{generation}")),
        })
    };
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&journal_path)?;
    let store = SharedStore(Rc::new(RefCell::new(
        LockedFileFinalHoldoutCasStoreV1::create(file, binding)?,
    )));
    let owner = FencedFinalHoldoutOwnerV1::initialize(store.clone(), binding, fence(1)?)?;
    let manifest = fixture.data.manifest.clone();
    let (cohort, contexts, versions) = manifest.digests()?;
    let objective = digest(&format!(
        "hepta.v6.paired.objective.v1:{}:text,image",
        fixture.metric
    ));
    let plan = freeze_paired_plan_v1(PairedPlanSpecV1 {
        plan_id: id(&format!("posthoc-paired:{expected}"))?,
        candidate_id: id(CANDIDATE)?,
        baseline_id: id(BASELINE)?,
        holdout_window_id: id(&format!("completed-future:{cohort}"))?,
        objective_digest: objective,
        dataset_digest: fixture.protocol["dataset_manifest"]["manifest_sha256"]
            .as_str()
            .context("dataset")?
            .parse()?,
        holdout_digest: cohort,
        context_manifest_digest: contexts,
        version_manifest_digest: versions,
        source_bundle_digest: digest(&format!(
            "hepta.v6.paired.replay-source.v1:{expected}:{importer}:{}",
            fixture.protocol_digest
        )),
        outcome_bundle_digest: fixture.data.canonical_digest()?,
        metric_digest: fixture.metric,
        audit_observer_digest: fixture.audit,
        reward_observer_digest: fixture.reward,
        estimand_digest: digest(
            "posthoc-v1:fixed-seeds-within-source-case;candidate-minus-baseline;loss-and-factual-error;family64-alpha50000;no-tail-or-seed-population-coverage",
        ),
        source_cases: manifest.cases.len() as u32,
        seeds: manifest.versions.len() as u32,
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 64,
        required_modalities: 3,
        minimum_loss_improvement: FixedQ32::ZERO,
        maximum_fact_error_increase: FixedQ32::ZERO,
    })?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let trust = verifier(objective, binding, now)?;
    let generator = sign(
        &trust,
        /*index*/ 0,
        &paired_plan_signing_payload_v1(&plan)?,
        now,
    )?;
    let witness = sign(
        &trust,
        /*index*/ 1,
        &paired_observation_signing_payload_v1(&plan)?,
        now,
    )?;
    let releases = Rc::new(Cell::new(0));
    let mut provider = Provider {
        plan: plan.clone(),
        data: fixture.data.clone(),
        witness,
        store: store.clone(),
        binding,
        releases: releases.clone(),
    };
    let mut sink = FileSink(directory.join("signed-owner-decision.txt"));
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let done = runner.evaluate_paired_profile(
        &plan,
        &manifest,
        &mut provider,
        &generator,
        &trust,
        |receipt| {
            sign(
                &trust,
                /*index*/ 2,
                &paired_evaluation_signing_payload_v1(receipt)
                    .map_err(|_| SignedEvidenceError::PayloadMismatch)?,
                now,
            )
        },
        &mut sink,
        now,
    )?;
    done.validate(&trust, now)?;
    ensure!(
        !done.decision.evaluation.authority.grants_any()
            && !done.decision.evaluation.grants_qualification_or_promotion()
    );
    ensure!(releases.get() == 1 && runner.holdout_anchor().record_count == 1);
    ensure!(Digest32::of_bytes(&std::fs::read(&sink.0)?) == done.publication_digest);
    let anchor = runner.holdout_anchor();
    // Tampering with a real observed value cannot publish a different result.
    let original_loss = provider.data.observations[0].joint_loss;
    provider.data.observations[0].joint_loss = FixedQ32::from_raw(original_loss.raw() ^ 1);
    assert!(
        runner
            .evaluate_paired_profile(
                &plan,
                &manifest,
                &mut provider,
                &generator,
                &trust,
                |_| panic!("altered data must fail before evaluator"),
                &mut sink,
                now
            )
            .is_err()
    );
    ensure!(runner.holdout_anchor() == anchor);
    provider.data.observations[0].joint_loss = original_loss;
    let original_data = provider.data.clone();
    let original_witness = provider.witness.clone();
    drop(provider);
    drop(runner);
    drop(store);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&journal_path)?;
    let restored = LockedFileFinalHoldoutCasStoreV1::recover(file, binding, Some(anchor))?;
    let store = SharedStore(Rc::new(RefCell::new(restored)));
    let owner = FencedFinalHoldoutOwnerV1::recover(store.clone(), binding, fence(2)?)?;
    let mut provider = Provider {
        plan: plan.clone(),
        data: original_data,
        witness: original_witness,
        store,
        binding,
        releases: releases.clone(),
    };
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let retried = runner.evaluate_paired_profile(
        &plan,
        &manifest,
        &mut provider,
        &generator,
        &trust,
        |receipt| {
            sign(
                &trust,
                /*index*/ 2,
                &paired_evaluation_signing_payload_v1(receipt)
                    .map_err(|_| SignedEvidenceError::PayloadMismatch)?,
                now,
            )
        },
        &mut sink,
        now,
    )?;
    retried.validate(&trust, now)?;
    ensure!(
        retried.decision.evaluation.execution_digest == done.decision.evaluation.execution_digest
    );
    ensure!(
        retried.publication_digest == done.publication_digest
            && runner.holdout_anchor().record_count == 1
    );
    fixture.verify_sources()?;
    let stats = &done.decision.evaluation.statistics;
    let report = json!({
        "schema": "hepta.ndu-v6.paired-owner-execution.v1", "authority": "deny_all",
        "fixture_sha256": expected.to_string(), "original_rows_sha256": expected_rows.to_string(),
        "original_protocol_sha256": fixture.protocol_digest.to_string(), "input_recipe_sha256": fixture.input_recipe_digest.to_string(),
        "importer_binary_sha256": importer.to_string(), "plan_sha256": plan.plan_digest().to_string(),
        "cohort_sha256": cohort.to_string(), "context_manifest_sha256": contexts.to_string(), "version_manifest_sha256": versions.to_string(),
        "outcome_bundle_sha256": plan.spec().outcome_bundle_digest.to_string(), "publication_sha256": done.publication_digest.to_string(),
        "execution_sha256": done.decision.evaluation.execution_digest.to_string(),
        "source_cases": stats.source_cases, "fixed_seeds": stats.fixed_seeds, "actual_rows": fixture.data.observations.len(),
        "baseline": BASELINE, "candidate": CANDIDATE, "baseline_complete": stats.baseline_complete,
        "candidate_complete": stats.candidate_complete, "required_modalities": ["text", "image"],
        "loss_difference": interval(&stats.loss_difference), "factual_error_difference": interval(&stats.factual_error_difference),
        "observed_thresholds_pass": stats.observed_thresholds_pass, "family_alpha_ppm": 50000, "simultaneous_comparisons": 64,
        "interval_scope": "Engineering profile, different from original registered family32. Conditional on independent source pairs and frozen models; no seed-population/tail coverage or new confirmatory inference.",
        "previously_observed_engineering_only": true, "new_scientific_samples": 0,
        "external_observer_authenticated": false, "local_fixture_signer_roles": 3,
        "observation_witness": "Posthoc witness of original combined row receipt and Audit-B bytes; no original separate signed observation and no re-scoring",
        "durable_consumption_before_release": true, "unique_consumption_records": runner.holdout_anchor().record_count,
        "data_release_calls_including_rejected_tamper_and_idempotent_recovery": releases.get(),
        "altered_real_outcome_rejected_before_evaluator": true, "same_result_after_journal_recovery": true,
        "persisted_bytes_revalidated_against_recovered_owner_derivation": true, "all_pinned_source_files_rechecked": true,
        "qualification_or_promotion": false,
    });
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(directory.join("evidence.json"))?;
    file.write_all(serde_json::to_string_pretty(&report)?.as_bytes())?;
    file.sync_all()?;
    File::open(&directory)?.sync_all()?;
    println!("PAIRED_OWNER_EVIDENCE={}", directory.display());
    Ok(())
}
