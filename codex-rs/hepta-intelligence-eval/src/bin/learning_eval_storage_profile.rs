use std::env;
use std::error::Error;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanReceiptV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::HoldoutUseDispositionV1;
use codex_hepta_intelligence_eval::HoldoutWriterFenceV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptPhaseV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptTransitionV1;
use codex_hepta_intelligence_eval::freeze_cross_fold_plan;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug)]
struct Args {
    attempts: u64,
    fences: u64,
    output: Option<PathBuf>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = parse_args()?;
    if args.attempts == 0 || args.fences == 0 {
        return Err("--attempts and --fences must be positive".into());
    }
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let root = env::temp_dir().join(format!(
        "hepta-learning-eval-profile-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&root)?;
    let result = run_profile(&root, &args);
    let cleanup = fs::remove_dir_all(&root);
    let report = result?;
    cleanup?;
    if let Some(output) = args.output {
        if let Some(parent) = output.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&output, &report)?;
    }
    print!("{report}");
    Ok(())
}

fn run_profile(root: &std::path::Path, args: &Args) -> Result<String, Box<dyn Error>> {
    let attempt_path = root.join("attempt.journal");
    let attempt_binding = digest("profile-attempt-binding");
    let mut attempt = LockedFileProductEvaluationAttemptJournalV1::create(
        create_empty(&attempt_path)?,
        attempt_binding,
    )?;
    let attempt_write_start = Instant::now();
    for index in 0..args.attempts {
        let attempt_id = id(&format!("profile-attempt:{index}"))?;
        let plan = digest(&format!("profile-plan:{index}"));
        let holdout = digest(&format!("profile-holdout:{index}"));
        let execution = digest(&format!("profile-execution:{index}"));
        let artifacts = digest(&format!("profile-qualification-artifacts:{index}"));
        let request = digest(&format!("profile-publication-request:{index}"));
        let publication = digest(&format!("profile-publication:{index}"));

        attempt.append(ProductEvaluationAttemptTransitionV1::intent(
            attempt_id.clone(),
            plan,
            attempt_binding,
            digest(&format!("profile-owner-state:{index}")),
        ))?;
        attempt.append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
            attempt_id.clone(),
            plan,
            holdout,
        ))?;
        attempt.append(ProductEvaluationAttemptTransitionV1::comparison_sealed(
            attempt_id.clone(),
            plan,
            holdout,
            execution,
        ))?;
        attempt.append(ProductEvaluationAttemptTransitionV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::QualificationArtifactsPersisted,
            holdout_record_digest: holdout,
            terminal_digest: artifacts,
        })?;
        for phase in [
            ProductEvaluationAttemptPhaseV1::QualificationDecided,
            ProductEvaluationAttemptPhaseV1::PublicationPending,
        ] {
            attempt.append(ProductEvaluationAttemptTransitionV1 {
                attempt_id: attempt_id.clone(),
                plan_digest: plan,
                phase,
                holdout_record_digest: holdout,
                terminal_digest: request,
            })?;
        }
        attempt.append(ProductEvaluationAttemptTransitionV1 {
            attempt_id,
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::Published,
            holdout_record_digest: holdout,
            terminal_digest: publication,
        })?;
    }
    if !attempt.pending(None, 1)?.is_empty() {
        return Err("completed profile retained unresolved attempts".into());
    }
    let attempt_write_micros = attempt_write_start.elapsed().as_micros();
    let attempt_bytes = attempt.byte_len();
    let attempt_events = attempt.event_count();
    drop(attempt);
    let attempt_recovery_start = Instant::now();
    let mut recovered_attempt = LockedFileProductEvaluationAttemptJournalV1::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&attempt_path)?,
        attempt_binding,
    )?;
    let attempt_recovery_micros = attempt_recovery_start.elapsed().as_micros();
    if recovered_attempt.event_count() != attempt_events
        || recovered_attempt.byte_len() != attempt_bytes
        || !recovered_attempt.pending(None, 1)?.is_empty()
    {
        return Err("attempt journal recovery profile mismatch".into());
    }
    drop(recovered_attempt);

    let holdout_path = root.join("holdout.cas");
    let compacted_path = root.join("holdout.compacted.cas");
    let holdout_binding = digest("profile-holdout-binding");
    let store =
        LockedFileFinalHoldoutCasStoreV1::create(create_empty(&holdout_path)?, holdout_binding)?;
    let first_fence = fence(1)?;
    let mut owner = FencedFinalHoldoutOwnerV1::initialize(store, holdout_binding, first_fence)?;
    let holdout_write_start = Instant::now();
    // Keep the existing fence budget and consume one distinct, frozen source
    // fixture per generation so takeover, reopen and compaction retain records.
    for generation in 1..=args.fences {
        if generation > 1 {
            owner = FencedFinalHoldoutOwnerV1::recover(
                owner.into_store(),
                holdout_binding,
                fence(generation)?,
            )?;
        }
        let plan = frozen_holdout_plan(generation)?;
        let receipt = owner.consume(&plan)?;
        if receipt.disposition != HoldoutUseDispositionV1::Recorded {
            return Err("profile failed to record a distinct final-holdout plan".into());
        }
    }
    let holdout_write_micros = holdout_write_start.elapsed().as_micros();
    let anchor = owner.anchor();
    let mut store = owner.into_store();
    let before = store.capacity();
    if before.record_count != args.fences || anchor.record_count != args.fences {
        return Err("holdout profile lost consumed plans".into());
    }
    let expected_state = store
        .load(holdout_binding)?
        .ok_or("missing holdout state")?;
    drop(store);
    let source_recovery_start = Instant::now();
    let mut store = LockedFileFinalHoldoutCasStoreV1::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&holdout_path)?,
        holdout_binding,
        Some(anchor),
    )?;
    let source_recovery_micros = source_recovery_start.elapsed().as_micros();
    if store.load(holdout_binding)?.as_ref() != Some(&expected_state) {
        return Err("source holdout reopen changed consumed history".into());
    }
    let compaction_start = Instant::now();
    let (compacted, compaction) = store.compact_into(create_empty(&compacted_path)?)?;
    let compaction_micros = compaction_start.elapsed().as_micros();
    compaction.validate_integrity()?;
    let after = compacted.capacity();
    if compacted.anchor() != Some(anchor) || compaction.state_digest != anchor.state_digest {
        return Err("holdout compaction changed the authoritative anchor".into());
    }
    drop(compacted);
    let holdout_recovery_start = Instant::now();
    let mut recovered_holdout = LockedFileFinalHoldoutCasStoreV1::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&compacted_path)?,
        holdout_binding,
        Some(anchor),
    )?;
    let holdout_recovery_micros = holdout_recovery_start.elapsed().as_micros();
    if recovered_holdout.anchor() != Some(anchor)
        || recovered_holdout.load(holdout_binding)?.as_ref() != Some(&expected_state)
    {
        return Err("compacted holdout recovery changed the authoritative history".into());
    }
    let recovered_bytes = recovered_holdout.byte_len();
    let mut owner = FencedFinalHoldoutOwnerV1::recover(
        recovered_holdout,
        holdout_binding,
        fence(args.fences)?,
    )?;
    let retry = owner.consume(&frozen_holdout_plan(args.fences)?)?;
    let store = owner.into_store();
    if retry.disposition != HoldoutUseDispositionV1::IdempotentReplay
        || store.anchor() != Some(anchor)
        || store.byte_len() != recovered_bytes
    {
        return Err("reopened final-holdout retry changed persisted history".into());
    }

    let body = format!(
        concat!(
            "{{\n",
            "  \"schema\": \"hepta.learning-eval.storage-profile.v1\",\n",
            "  \"attempts\": {{\n",
            "    \"attemptCount\": {},\n",
            "    \"eventCount\": {},\n",
            "    \"bytes\": {},\n",
            "    \"writeMicros\": {},\n",
            "    \"recoveryMicros\": {}\n",
            "  }},\n",
            "  \"holdout\": {{\n",
            "    \"fenceTransitions\": {},\n",
            "    \"planRecords\": {},\n",
            "    \"beforeBytes\": {},\n",
            "    \"afterBytes\": {},\n",
            "    \"bytesLimit\": {},\n",
            "    \"recordLimit\": {},\n",
            "    \"writeMicros\": {},\n",
            "    \"sourceRecoveryMicros\": {},\n",
            "    \"compactionMicros\": {},\n",
            "    \"recoveryMicros\": {},\n",
            "    \"retryPreserved\": true,\n",
            "    \"anchorPreserved\": true\n",
            "  }}\n",
            "}}"
        ),
        args.attempts,
        attempt_events,
        attempt_bytes,
        attempt_write_micros,
        attempt_recovery_micros,
        args.fences,
        before.record_count,
        before.bytes_used,
        after.bytes_used,
        before.bytes_limit,
        before.record_limit,
        holdout_write_micros,
        source_recovery_micros,
        compaction_micros,
        holdout_recovery_micros,
    );
    let profile_digest = Digest32::of_bytes(body.as_bytes()).to_string();
    let report = format!(
        "{}\n",
        body.replacen(
            "\n}",
            &format!(",\n  \"profileDigest\": \"{profile_digest}\"\n}}"),
            1,
        )
    );
    Ok(report)
}

fn parse_args() -> Result<Args, Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let mut attempts = 1_024u64;
    let mut fences = 512u64;
    let mut output = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--attempts" => {
                attempts = args.next().ok_or("--attempts requires a value")?.parse()?;
            }
            "--fences" => {
                fences = args.next().ok_or("--fences requires a value")?.parse()?;
            }
            "--output" => {
                output = Some(PathBuf::from(
                    args.next().ok_or("--output requires a value")?,
                ));
            }
            _ => return Err(format!("unknown argument: {arg}").into()),
        }
    }
    Ok(Args {
        attempts,
        fences,
        output,
    })
}

fn create_empty(path: &std::path::Path) -> Result<File, std::io::Error> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
}

fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
    StableId::new(value).map_err(|error| format!("invalid profile id {value}: {error}").into())
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fence(generation: u64) -> Result<HoldoutWriterFenceV1, Box<dyn Error>> {
    Ok(HoldoutWriterFenceV1 {
        owner_id: id(&format!("profile-owner:{generation}"))?,
        generation,
        lease_digest: digest(&format!("profile-lease:{generation}")),
    })
}

// Synthetic preregistered plans exercise storage semantics, not measured efficacy.
fn frozen_holdout_plan(index: u64) -> Result<CrossFoldPlanReceiptV1, Box<dyn Error>> {
    let final_window = id(&format!("profile-final-window:{index}"))?;
    let folds = ["a", "b"]
        .into_iter()
        .map(|label| {
            Ok(CrossFoldPartitionV1 {
                fold_id: id(&format!("profile-fold:{label}"))?,
                training_principals: vec![id(&format!("profile-training-principal:{label}"))?],
                training_episodes: vec![id(&format!("profile-training-episode:{label}"))?],
                training_windows: vec![id(&format!("profile-training-window:{label}"))?],
                holdout_principals: vec![id(&format!("profile-held-principal:{label}"))?],
                holdout_episodes: vec![id(&format!("profile-held-episode:{label}"))?],
                holdout_windows: vec![if label == "b" {
                    final_window.clone()
                } else {
                    id(&format!("profile-holdout-window:{index}:{label}"))?
                }],
                model_digest: digest(&format!("profile-model:{index}:{label}")),
                predictions_digest: digest(&format!("profile-predictions:{index}:{label}")),
            })
        })
        .collect::<Result<Vec<_>, Box<dyn Error>>>()?;
    Ok(freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id(&format!("profile-holdout-plan:{index}"))?,
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("profile-candidate")?,
        baseline_id: id("profile-baseline")?,
        objective_digest: digest("profile-objective"),
        dataset_digest: digest("profile-dataset"),
        estimand_digest: digest("profile-estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("profile-utility")?,
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds,
        final_holdout_window_id: final_window,
        final_holdout_digest: digest(&format!("profile-final-holdout:{index}")),
    })?)
}
