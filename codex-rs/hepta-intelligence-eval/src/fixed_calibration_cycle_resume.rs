//! Resume only the original independent evaluator after completed custody.
//! The original configuration, measurements, ledger and witness stay intact.
use super::*;
use crate::fixed_calibration_cycle_evaluator::read_publication;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::inspect_ledger;
use codex_hepta_learning_ledger::open_root_review_input;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResumeConfig {
    schema: String,
    program_digest: String,
    original_cycle_config: Source,
    completed_observer_output: Source,
    publication: Source,
    native_ledger: Source,
    readonly_ledger: Source,
    witness: Source,
}

#[derive(Clone, Copy)]
enum RecoveryMarker {
    Absent,
    Matching,
}
#[derive(Clone, Copy)]
enum EvaluatorOutput {
    Absent,
    Complete,
    Partial,
}
#[derive(Debug, Eq, PartialEq)]
enum ResumeAction {
    ExecuteIndependentEvaluation,
    AuthenticateOriginalResult,
}
fn resume_action(marker: RecoveryMarker, output: EvaluatorOutput) -> HostResult<ResumeAction> {
    match (marker, output) {
        (RecoveryMarker::Absent, EvaluatorOutput::Absent) => {
            Ok(ResumeAction::ExecuteIndependentEvaluation)
        }
        (RecoveryMarker::Absent, EvaluatorOutput::Complete)
        | (RecoveryMarker::Matching, EvaluatorOutput::Complete) => {
            Ok(ResumeAction::AuthenticateOriginalResult)
        }
        (RecoveryMarker::Matching, EvaluatorOutput::Absent)
        | (RecoveryMarker::Absent, EvaluatorOutput::Partial)
        | (RecoveryMarker::Matching, EvaluatorOutput::Partial) => Err(
            "begun or partial independent evaluation retained; no automatic re-execution".into(),
        ),
    }
}

fn require_resume_history(
    begin: &Value,
    observer: &Value,
    config_digest: Digest32,
    request_digest: Digest32,
    native_ledger: &[u8],
    old_ledger: &[u8],
    now: u64,
) -> HostResult<u64> {
    let started = begin["started_at_ms"]
        .as_u64()
        .ok_or("original cycle start")?;
    if begin["schema"] != "hepta.fixed-calibration-cycle.begin.v1"
        || begin["config_digest"] != config_digest.to_string()
        || begin["qualified"] != false
        || begin["holdout_consumed"] != false
        || started > now
        || old_ledger.is_empty()
        || !native_ledger.starts_with(old_ledger)
        || begin["previous_ledger_digest"] != Digest32::of_bytes(old_ledger).to_string()
        || observer["request_digest"] != request_digest.to_string()
        || observer["qualified"] != false
        || observer["authority_grants_any"] != false
        || observer["holdout_consumed"] != false
        || observer["production_activation"] != false
    {
        return Err(
            "resume must retain original begun configuration and acknowledged prefix".into(),
        );
    }
    Ok(started)
}

/// Resume an explicitly pinned original calibration cycle without rerunning
/// Generator/Observer or creating new task identities. Existing evaluator bytes
/// are authenticated and reconciled; partial or ambiguous output is retained.
pub fn resume_fixed_calibration_evaluation(path: &Path) -> HostResult<()> {
    root_boundary()?;
    let resume_bytes = read_root_review_input(path, 32 * 1024)?;
    let resume: ResumeConfig = serde_json::from_slice(&resume_bytes)?;
    if resume.schema != "hepta.fixed-calibration-evaluation-resume.v1"
        || Digest32::of_bytes(&read_root_review_input(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
        )?) != resume.program_digest.parse::<Digest32>()?
    {
        return Err("resume program/config pin".into());
    }
    let config_bytes = source(&resume.original_cycle_config, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-calibration-cycle-config.v1" {
        return Err("original fixed cycle configuration required".into());
    }
    let original: Value =
        serde_json::from_slice(&source(&config.original_custody_request, 32 * 1024)?)?;
    let current_bytes = source(&config.current_custody_request, 32 * 1024)?;
    let current: Value = serde_json::from_slice(&current_bytes)?;
    let old_eval: Value =
        serde_json::from_slice(&source(&config.original_evaluator_config, 32 * 1024)?)?;
    let eval_bytes = source(&config.current_evaluator_config, 32 * 1024)?;
    let new_eval: Value = serde_json::from_slice(&eval_bytes)?;
    let custody_program = Digest32::of_bytes(&source(&config.custody_program, 128 * 1024 * 1024)?);
    let evaluator_program =
        Digest32::of_bytes(&source(&config.evaluator_program, 128 * 1024 * 1024)?);
    let (publication_directory, uid, gid) = validate_requests(
        &original,
        &current,
        &old_eval,
        &new_eval,
        custody_program,
        evaluator_program,
    )?;
    let approval_bytes = source(&config.current_program_approval, 16 * 1024)?;
    let approval: Value = serde_json::from_slice(&approval_bytes)?;
    let now = now_ms()?;
    if field_path(&current, "cycle_program_approval_path")? != config.current_program_approval.path
        || new_eval["current_program_approval_digest"]
            != Digest32::of_bytes(&approval_bytes).to_string()
        || approval["observer_program_digest"] != custody_program.to_string()
        || field_path(&approval, "reviewer_program_path")? != config.evaluator_program.path
        || approval["reviewer_program_digest"] != evaluator_program.to_string()
        || approval["reviewer_uid"] != uid
        || approval["reviewer_gid"] != gid
        || approval["effective_at_ms"]
            .as_u64()
            .is_none_or(|value| value > now)
        || approval["expires_at_ms"]
            .as_u64()
            .is_none_or(|value| now >= value)
    {
        return Err("original program approval is changed, not effective or expired".into());
    }
    let trust: Value = serde_json::from_slice(&read_root_review_input(
        &field_path(&current, "trust_config_path")?,
        16 * 1024,
    )?)?;
    let admitted = field_path(&trust["independent_reviewer"], "publication_directory")?;
    if publication_directory == admitted || !publication_directory.starts_with(&admitted) {
        return Err("resumed publication outside original custody root".into());
    }
    let phase = &config.phase_directory;
    private_parent(&phase.join("begin.json"))?;
    if phase.join("completion.json").exists() {
        return Err("original cycle already completed; inspect its original completion".into());
    }
    for (pinned, actual) in [
        (
            &resume.completed_observer_output,
            phase.join("custody.stdout.json"),
        ),
        (
            &resume.publication,
            field_path(&new_eval, "publication_path")?,
        ),
        (
            &resume.native_ledger,
            field_path(&current, "ledger_directory")?.join("causal-ledger.bin"),
        ),
        (
            &resume.readonly_ledger,
            field_path(&new_eval, "ledger_path")?,
        ),
        (
            &resume.witness,
            field_path(&current, "witness_directory")?.join("acknowledged-frontier.bin"),
        ),
    ] {
        if pinned.path != actual {
            return Err("resume artifact path differs from the original owners".into());
        }
    }
    let begin_bytes = read_root_review_input(&phase.join("begin.json"), 16 * 1024)?;
    let begin: Value = serde_json::from_slice(&begin_bytes)?;
    let observer: Value =
        serde_json::from_slice(&source(&resume.completed_observer_output, 4 * 1024 * 1024)?)?;
    let ledger_bytes = source(&resume.native_ledger, 8 * 1024 * 1024)?;
    let readonly_bytes = source(&resume.readonly_ledger, 8 * 1024 * 1024)?;
    let old_ledger =
        read_root_review_input(&field_path(&old_eval, "ledger_path")?, 8 * 1024 * 1024)?;
    let started = require_resume_history(
        &begin,
        &observer,
        Digest32::of_bytes(&config_bytes),
        Digest32::of_bytes(&current_bytes),
        &ledger_bytes,
        &old_ledger,
        now,
    )?;
    let (publication, cycle) = read_publication(&source(&resume.publication, 4 * 1024 * 1024)?)?;
    let cycle = cycle.ok_or("original V2 calibration cycle publication required")?;
    let old_publication: Value = serde_json::from_slice(&read_root_review_input(
        &field_path(&old_eval, "publication_path")?,
        4 * 1024 * 1024,
    )?)?;
    let old_cut = &old_publication["cut"];
    let expected = original_input_ids(&read_root_review_input(
        &field_path(&current, "native_inputs_path")?,
        4 * 1024 * 1024,
    )?)?;
    let previous_sequence = old_cut["acknowledged_sequence"]
        .as_u64()
        .ok_or("original cut anchor")?;
    let expected_sequence = previous_sequence
        .checked_add(
            u64::try_from(expected.len())?
                .checked_mul(4)
                .ok_or("cycle count overflow")?,
        )
        .ok_or("cycle sequence overflow")?;
    let cut = &publication.cut;
    if readonly_bytes != ledger_bytes
        || Digest32::of_bytes(&ledger_bytes) != cut.ledger_file_digest.parse::<Digest32>()?
        || old_cut["ledger_file_digest"] != Digest32::of_bytes(&old_ledger).to_string()
        || cycle.first_sequence
            != previous_sequence
                .checked_add(1)
                .ok_or("cycle first sequence")?
        || cycle.previous_acknowledged_head.to_string() != old_cut["acknowledged_head"]
        || cycle.run_snapshot_digests.len() != expected.len()
        || cycle.current_program_approval_digest != Digest32::of_bytes(&approval_bytes)
        || cut.acknowledged_sequence != expected_sequence
        || observer["acknowledged_sequence"] != cut.acknowledged_sequence
        || observer["acknowledged_head"] != cut.acknowledged_head
        || observer["ledger_head_before"] != cycle.previous_acknowledged_head.to_string()
    {
        return Err("resume cut, full original history or exact cycle measurements changed".into());
    }
    source(&resume.witness, 8 * 1024 * 1024)?;
    // The original witness's native sole-owner lock prevents a legitimate new
    // custody writer during this inspection and evaluation. A torn witness is
    // rejected through the readonly FD, never truncated or recreated here.
    let witness = LedgerWitnessStore::recover(
        open_root_review_input(&resume.witness.path)?,
        cut.ledger_binding_digest.parse()?,
    )?;
    let anchor = LedgerAnchor {
        sequence: cut.acknowledged_sequence,
        chain_digest: cut.acknowledged_head.parse()?,
    };
    if witness.frontier()?.anchor != anchor {
        return Err("original witness does not acknowledge the exact resumed ledger".into());
    }
    inspect_ledger(
        open_root_review_input(&resume.native_ledger.path)?,
        cut.ledger_binding_digest.parse()?,
        4096,
        anchor,
    )?;
    let work = field_path(&current, "work_directory")?;
    for name in ["candidate-evaluator.jsonl", "baseline-evaluator.jsonl"] {
        require_fresh_native_stream(
            &read_root_review_input(&work.join(name), 4 * 1024 * 1024)?,
            &expected,
            started,
            now_ms()?,
        )?;
    }
    let original_context = Digest32::of_bytes(&serde_json::to_vec(&serde_json::json!({
        "original_config_digest":Digest32::of_bytes(&config_bytes).to_string(),
        "original_begin_digest":Digest32::of_bytes(&begin_bytes).to_string(),
        "observer":resume.completed_observer_output.digest,"publication":resume.publication.digest,
        "native_ledger":resume.native_ledger.digest,"readonly_ledger":resume.readonly_ledger.digest,
        "witness":resume.witness.digest
    }))?);
    let marker_path = phase.join("evaluation-resume.begin.json");
    let recovery_already_begun = marker_path.exists();
    if recovery_already_begun {
        let marker: Value =
            serde_json::from_slice(&read_root_review_input(&marker_path, 16 * 1024)?)?;
        if marker["schema"] != "hepta.fixed-calibration-evaluation-resume.begin.v1"
            || marker["original_context_digest"] != original_context.to_string()
            || marker["generator_reexecuted"] != false
            || marker["observer_reexecuted"] != false
            || marker["qualified"] != false
            || marker["holdout_consumed"] != false
        {
            return Err("existing recovery marker differs from original pinned cycle".into());
        }
    } else {
        write_new(
            &marker_path,
            &serde_json::to_vec(&serde_json::json!({
                "schema":"hepta.fixed-calibration-evaluation-resume.begin.v1",
                "resume_config_digest":Digest32::of_bytes(&resume_bytes).to_string(),
                "original_context_digest":original_context.to_string(),
                "started_at_ms":now_ms()?,"generator_reexecuted":false,"observer_reexecuted":false,
                "qualified":false,"holdout_consumed":false
            }))?,
        )?;
    }
    let marker = if recovery_already_begun {
        RecoveryMarker::Matching
    } else {
        RecoveryMarker::Absent
    };
    let output = match (
        phase.join("evaluator.stdout.json").exists(),
        phase.join("evaluator.stderr.log").exists(),
    ) {
        (false, false) => EvaluatorOutput::Absent,
        (true, true) => EvaluatorOutput::Complete,
        (true, false) | (false, true) => EvaluatorOutput::Partial,
    };
    let independent = match resume_action(marker, output)? {
        ResumeAction::ExecuteIndependentEvaluation => execute_independent_evaluation(
            &config,
            uid,
            gid,
            evaluator_program,
            &eval_bytes,
            Digest32::of_bytes(&config_bytes),
        )?,
        ResumeAction::AuthenticateOriginalResult => {
            read_independent_evaluation(&config, evaluator_program, &eval_bytes)?
        }
    };
    for (artifact, maximum) in [
        (&resume.original_cycle_config, 32 * 1024),
        (&resume.completed_observer_output, 4 * 1024 * 1024),
        (&resume.publication, 4 * 1024 * 1024),
        (&resume.native_ledger, 8 * 1024 * 1024),
        (&resume.readonly_ledger, 8 * 1024 * 1024),
        (&resume.witness, 8 * 1024 * 1024),
        (&config.current_program_approval, 16 * 1024),
        (&config.evaluator_program, 128 * 1024 * 1024),
        (&config.custody_program, 128 * 1024 * 1024),
    ] {
        source(artifact, maximum)?;
    }
    let final_independent = read_independent_evaluation(&config, evaluator_program, &eval_bytes)?;
    if final_independent.bytes != independent.bytes {
        return Err("original evaluator result changed during reconciliation".into());
    }
    if now_ms()?
        >= approval["expires_at_ms"]
            .as_u64()
            .ok_or("approval expiry")?
    {
        return Err("original program approval expired before completion; keep evidence".into());
    }
    write_new(
        &phase.join("completion.json"),
        &serde_json::to_vec(&serde_json::json!({
            "schema":"hepta.fixed-calibration-cycle.completed.v1",
            "config_digest":Digest32::of_bytes(&config_bytes).to_string(),
            "resume_config_digest":Digest32::of_bytes(&resume_bytes).to_string(),
            "original_inputs":current,"native_started_at_ms":started,"completed_at_ms":now_ms()?,
            "independent_result_digest":Digest32::of_bytes(&final_independent.bytes).to_string(),
            "independent_evaluation":final_independent.evaluation,"scope":"calibration-only",
            "qualified":false,"holdout_consumed":false,"production_activation":false,
            "authority_grants_any":false,"generator_reexecuted":false,"observer_reexecuted":false
        }))?,
    )?;
    drop(witness);
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.fixed-calibration-cycle.status.v1","completed":true,
        "completion_path":phase.join("completion.json"),"qualified":false,"holdout_consumed":false,"production_activation":false})
    );
    Ok(())
}

#[cfg(test)]
#[path = "fixed_calibration_cycle_resume_tests.rs"]
mod tests;
