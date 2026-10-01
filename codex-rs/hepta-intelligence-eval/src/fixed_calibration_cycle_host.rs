//! Execute fresh fixed calibration measurements; retain every previous cycle.
//! No registration, final-holdout access, arbitrary signing or activation API.
use crate::fixed_calibration_host::read_fixed_calibration_result;
use crate::fixed_product_host::private_parent;
use crate::fixed_product_host::root_boundary;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
type HostResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    path: PathBuf,
    digest: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    program_digest: String,
    original_custody_request: Source,
    current_custody_request: Source,
    original_evaluator_config: Source,
    current_evaluator_config: Source,
    custody_program: Source,
    evaluator_program: Source,
    current_program_approval: Source,
    phase_directory: PathBuf,
}
fn source(value: &Source, maximum: u64) -> HostResult<Vec<u8>> {
    let bytes = read_root_review_input(&value.path, maximum)?;
    if Digest32::of_bytes(&bytes) != value.digest.parse::<Digest32>()? {
        return Err("calibration cycle source pin changed".into());
    }
    Ok(bytes)
}
fn write_new(path: &Path, bytes: &[u8]) -> HostResult<File> {
    let parent = private_parent(path)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    parent.sync_all()?;
    Ok(file)
}
fn equal_except(original: &Value, current: &Value, allowed: &[&str]) -> HostResult<()> {
    let mut original = original.as_object().ok_or("original cycle object")?.clone();
    let mut current = current.as_object().ok_or("current cycle object")?.clone();
    for key in allowed {
        original.remove(*key);
        current.remove(*key);
    }
    if original != current {
        return Err(
            "cycle changed original model/source/key/policy or ledger/witness binding".into(),
        );
    }
    Ok(())
}
fn field_path(value: &Value, name: &str) -> HostResult<PathBuf> {
    Ok(PathBuf::from(
        value[name].as_str().ok_or("cycle path field")?,
    ))
}
fn validate_requests(
    original: &Value,
    current: &Value,
    old_eval: &Value,
    new_eval: &Value,
    custody_digest: Digest32,
    evaluator_digest: Digest32,
) -> HostResult<(PathBuf, u32, u32)> {
    if original["schema"] != "hepta.fixed-custody-calibration-request.v1"
        || original["operation"] != "review"
        || current["operation"] != "review"
        || current["schema"] != "hepta.fixed-custody-calibration-request.v2"
        || new_eval["schema"] != "hepta.fixed-calibration-evaluator-config.v2"
        || old_eval["schema"] != "hepta.fixed-calibration-evaluator-config.v1"
        || new_eval["program_digest"] != evaluator_digest.to_string()
        || new_eval["observer_program_digest"] != custody_digest.to_string()
    {
        return Err("fixed calibration cycle schemas/programs".into());
    }
    equal_except(
        original,
        current,
        &[
            "work_directory",
            "public_contract_path",
            "receipt_path",
            "publication_directory",
            "schema",
            "cycle_program_approval_path",
        ],
    )?;
    equal_except(
        old_eval,
        new_eval,
        &[
            "publication_path",
            "ledger_path",
            "observer_program_digest",
            "schema",
            "program_digest",
            "current_program_approval_digest",
        ],
    )?;
    for field in ["work_directory", "public_contract_path", "receipt_path"] {
        if field_path(original, field)? == field_path(current, field)? {
            return Err("cycle must preserve previous execution artifacts".into());
        }
    }
    let publication = field_path(current, "publication_directory")?;
    if field_path(new_eval, "publication_path")? != publication.join("signed-calibration-cut.json")
        || field_path(new_eval, "ledger_path")? != publication.join("ledger-readonly.bin")
        || new_eval["publication_path"] == old_eval["publication_path"]
        || new_eval["ledger_path"] == old_eval["ledger_path"]
    {
        return Err("cycle evaluator must read its new original custody cut".into());
    }
    let uid = u32::try_from(new_eval["uid"].as_u64().ok_or("evaluator UID")?)?;
    let gid = u32::try_from(new_eval["gid"].as_u64().ok_or("evaluator GID")?)?;
    if uid == 0 || gid == 0 {
        return Err("independent evaluator actual nonroot identity".into());
    }
    Ok((publication, uid, gid))
}

/// Root-pinned immutable inputs drive original closed Gen/Observer programs and
/// the same independent UID's native evaluator. No previous result is re-signed.
pub fn run_fixed_calibration_cycle(path: &Path) -> HostResult<()> {
    root_boundary()?;
    let bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.fixed-calibration-cycle-config.v1"
        || Digest32::of_bytes(&read_root_review_input(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
        )?) != config.program_digest.parse::<Digest32>()?
    {
        return Err("cycle program/config pin".into());
    }
    let original: Value =
        serde_json::from_slice(&source(&config.original_custody_request, 32 * 1024)?)?;
    let current: Value =
        serde_json::from_slice(&source(&config.current_custody_request, 32 * 1024)?)?;
    let old_eval: Value =
        serde_json::from_slice(&source(&config.original_evaluator_config, 32 * 1024)?)?;
    let eval_bytes = source(&config.current_evaluator_config, 32 * 1024)?;
    let new_eval: Value = serde_json::from_slice(&eval_bytes)?;
    let custody_program = Digest32::of_bytes(&source(&config.custody_program, 128 * 1024 * 1024)?);
    let evaluator_program =
        Digest32::of_bytes(&source(&config.evaluator_program, 128 * 1024 * 1024)?);
    let (publication, uid, gid) = validate_requests(
        &original,
        &current,
        &old_eval,
        &new_eval,
        custody_program,
        evaluator_program,
    )?;
    let approval_bytes = source(&config.current_program_approval, 16 * 1024)?;
    let approval: Value = serde_json::from_slice(&approval_bytes)?;
    if new_eval["current_program_approval_digest"]
        != Digest32::of_bytes(&approval_bytes).to_string()
    {
        return Err("evaluator config does not freeze actual program approval bytes".into());
    }
    if field_path(&current, "cycle_program_approval_path")? != config.current_program_approval.path
        || approval["observer_program_digest"] != custody_program.to_string()
        || field_path(&approval, "reviewer_program_path")? != config.evaluator_program.path
        || approval["reviewer_program_digest"] != evaluator_program.to_string()
        || approval["reviewer_uid"] != uid
        || approval["reviewer_gid"] != gid
    {
        return Err("current actual observer/reviewer programs not the frozen approval".into());
    }
    let trust: Value = serde_json::from_slice(&read_root_review_input(
        &field_path(&current, "trust_config_path")?,
        16 * 1024,
    )?)?;
    let admitted = field_path(&trust["independent_reviewer"], "publication_directory")?;
    if publication == admitted || !publication.starts_with(&admitted) {
        return Err("cycle publication outside original admitted custody root".into());
    }
    private_parent(&config.phase_directory.join("begin.json"))?;
    let work = field_path(&current, "work_directory")?;
    // Creation/recovery is explicit. A begun or ambiguous cycle must be examined
    // through the original owners; this command never resets or retries it.
    for file in [
        "generator-decisions.json",
        "generator-decisions.status.json",
        "candidate-evaluator.jsonl",
        "baseline-evaluator.jsonl",
        "observer-issued.json",
    ] {
        if work.join(file).exists() {
            return Err(
                "calibration cycle already has execution artifacts; preserve original cycle".into(),
            );
        }
    }
    if field_path(&current, "public_contract_path")?.exists()
        || field_path(&current, "receipt_path")?.exists()
        || publication.join("signed-calibration-cut.json").exists()
        || publication.join("ledger-readonly.bin").exists()
        || config.phase_directory.join("begin.json").exists()
    {
        return Err("calibration cycle already or partially started; no automatic replay".into());
    }
    let before_ledger = read_root_review_input(
        &field_path(&current, "ledger_directory")?.join("causal-ledger.bin"),
        8 * 1024 * 1024,
    )?;
    let started = now_ms()?;
    write_new(
        &config.phase_directory.join("begin.json"),
        &serde_json::to_vec(&serde_json::json!({
            "schema":"hepta.fixed-calibration-cycle.begin.v1","config_digest":Digest32::of_bytes(&bytes).to_string(),
            "started_at_ms":started,"previous_ledger_digest":Digest32::of_bytes(&before_ledger).to_string(),
            "original_custody_request":config.original_custody_request.digest,
            "current_custody_request":config.current_custody_request.digest,"qualified":false,"holdout_consumed":false
        }))?,
    )?;
    let output = write_new(&config.phase_directory.join("custody.stdout.json"), &[])?;
    let errors = write_new(&config.phase_directory.join("custody.stderr.log"), &[])?;
    let status = Command::new(&config.custody_program.path)
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .arg("--request")
        .arg(&config.current_custody_request.path)
        .stdin(Stdio::null())
        .stdout(Stdio::from(output))
        .stderr(Stdio::from(errors))
        .status()?;
    if !status.success() {
        return Err(
            "actual calibration Gen/Observer execution failed; retain original cycle".into(),
        );
    }
    let inputs = read_root_review_input(
        &field_path(&current, "native_inputs_path")?,
        4 * 1024 * 1024,
    )?;
    let expected = original_input_ids(&inputs)?;
    let observed_now = now_ms()?;
    for name in ["candidate-evaluator.jsonl", "baseline-evaluator.jsonl"] {
        let raw = read_root_review_input(&work.join(name), 4 * 1024 * 1024)?;
        require_fresh_native_stream(&raw, &expected, started, observed_now)?;
    }
    let eval_output = write_new(&config.phase_directory.join("evaluator.stdout.json"), &[])?;
    let eval_errors = write_new(&config.phase_directory.join("evaluator.stderr.log"), &[])?;
    let status = Command::new("/usr/bin/systemd-run")
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .args(["--quiet", "--wait", "--pipe", "--collect"])
        .arg(format!(
            "--unit=hepta-fixed-calibration-eval-cycle-{}-{}",
            &Digest32::of_bytes(&bytes).to_string()[..16],
            std::process::id()
        ))
        .args([
            "--property=NoNewPrivileges=yes",
            "--property=CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_SETPCAP",
            "--property=AmbientCapabilities=",
            "--property=MemoryMax=268435456",
            "--property=TasksMax=16",
            "--property=CPUQuota=100%",
            "--property=ProtectSystem=strict",
            "--property=ProtectHome=read-only",
            "--property=RestrictNamespaces=yes",
            "--property=RuntimeMaxSec=120",
            "--property=LimitCORE=0",
        ])
        .arg("/usr/bin/setpriv")
        .arg(format!("--reuid={uid}"))
        .arg(format!("--regid={gid}"))
        .args([
            "--clear-groups",
            "--inh-caps=-all",
            "--bounding-set=-all",
            "--ambient-caps=-all",
            "--no-new-privs",
        ])
        .arg(&config.evaluator_program.path)
        .arg("--request")
        .arg(&config.current_evaluator_config.path)
        .stdin(Stdio::null())
        .stdout(Stdio::from(eval_output))
        .stderr(Stdio::from(eval_errors))
        .status()?;
    if !status.success() {
        return Err("actual independent evaluator failed; retain original cycle".into());
    }
    let result = read_root_review_input(
        &config.phase_directory.join("evaluator.stdout.json"),
        64 * 1024,
    )?;
    let evaluation =
        read_fixed_calibration_result(&eval_bytes, evaluator_program, &result, now_ms()?)?;
    if evaluation["current_authentication"] != true {
        return Err("cycle did not produce authenticated current independent evidence".into());
    }
    if Digest32::of_bytes(&source(&config.custody_program, 128 * 1024 * 1024)?) != custody_program
        || Digest32::of_bytes(&source(&config.evaluator_program, 128 * 1024 * 1024)?)
            != evaluator_program
    {
        return Err("cycle executable changed during execution".into());
    }
    write_new(
        &config.phase_directory.join("completion.json"),
        &serde_json::to_vec(&serde_json::json!({
            "schema":"hepta.fixed-calibration-cycle.completed.v1","config_digest":Digest32::of_bytes(&bytes).to_string(),
            "original_inputs":current,"native_started_at_ms":started,"completed_at_ms":now_ms()?,
            "independent_result_digest":Digest32::of_bytes(&result).to_string(),"independent_evaluation":evaluation,
            "scope":"calibration-only","qualified":false,"holdout_consumed":false,"production_activation":false,
            "authority_grants_any":false
        }))?,
    )?;
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.fixed-calibration-cycle.status.v1","completed":true,
        "completion_path":config.phase_directory.join("completion.json"),"qualified":false,"holdout_consumed":false,"production_activation":false})
    );
    Ok(())
}
fn now_ms() -> HostResult<u64> {
    Ok(u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?)
}

#[cfg(test)]
#[path = "fixed_calibration_cycle_tests.rs"]
mod tests;
fn original_input_ids(bytes: &[u8]) -> HostResult<Vec<String>> {
    if bytes.is_empty() || !bytes.ends_with(b"\n") {
        return Err("complete original native input stream".into());
    }
    let ids = bytes
        .split(|b| *b == b'\n')
        .filter(|line| !line.is_empty())
        .map(|line| {
            let value: Value = serde_json::from_slice(line)?;
            Ok(value["request_id"]
                .as_str()
                .filter(|s| !s.is_empty())
                .ok_or("original request ID")?
                .to_owned())
        })
        .collect::<HostResult<Vec<_>>>()?;
    if ids.is_empty()
        || ids.len() > 2048
        || ids.iter().collect::<std::collections::BTreeSet<_>>().len() != ids.len()
    {
        return Err("bounded unique complete original request IDs".into());
    }
    Ok(ids)
}
fn require_fresh_native_stream(
    bytes: &[u8],
    expected: &[String],
    started: u64,
    now: u64,
) -> HostResult<()> {
    if bytes.is_empty() || !bytes.ends_with(b"\n") || started > now {
        return Err("complete actual native observations".into());
    }
    let rows = bytes
        .split(|b| *b == b'\n')
        .filter(|line| !line.is_empty())
        .collect::<Vec<_>>();
    if rows.len() != expected.len() {
        return Err("whole original source task stream required".into());
    }
    for (line, id) in rows.into_iter().zip(expected) {
        let observation: Value = serde_json::from_slice(line)?;
        if observation["schema"] != "hepta.cpu-neuron.offline-observation.v1"
            || observation["executed_at_ms"]
                .as_u64()
                .is_none_or(|event| event < started || event > now)
            || observation["request_id"] != *id
            || observation["terminal_observed"] != true
            || observation["succeeded"] != true
            || observation["authority_grants_any"] != false
            || observation.get("authority").is_some()
            || observation["qualified"] != false
        {
            return Err(
                "actual fresh ordered terminal offline observations required; no qualification"
                    .into(),
            );
        }
    }
    Ok(())
}
