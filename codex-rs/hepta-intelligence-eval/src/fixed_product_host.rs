//! Single-host preflight composition over the actual protected owners.
//!
//! It reuses the existing custody executable and independent evaluator result;
//! it has no signing key or gold-release API. Until a supported, authenticated
//! behavior cut and registered product plan exist, ProductEvaluationRunnerV1
//! must not consume the holdout. Paired classification is not an OPE cohort.
use crate::fixed_calibration_host::read_fixed_calibration_result;
use crate::fixed_product_source::frozen_source_graph;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

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
    objective_digest: String,
    source_batch: Source,
    custody_program: Source,
    custody_config: Source,
    evaluator_program: Source,
    evaluator_config: Source,
    evaluator_result: Source,
    report_path: PathBuf,
}
fn source(source: &Source, maximum: u64) -> HostResult<Vec<u8>> {
    let bytes = read_root_review_input(&source.path, maximum)?;
    if Digest32::of_bytes(&bytes) != source.digest.parse::<Digest32>()? {
        return Err("product source pin changed".into());
    }
    Ok(bytes)
}
pub(crate) fn root_boundary() -> HostResult<()> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    for field in ["Uid:", "Gid:"] {
        let values = status
            .lines()
            .find_map(|line| line.strip_prefix(field))
            .ok_or("Root identity")?;
        if values.split_whitespace().count() != 4 || values.split_whitespace().any(|s| s != "0") {
            return Err("product provider requires actual Root custody identity".into());
        }
    }
    for field in ["CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:"] {
        if status
            .lines()
            .find_map(|line| line.strip_prefix(field))
            .map(str::trim)
            != Some("0000000000000000")
        {
            return Err("product custody provider requires zero capabilities".into());
        }
    }
    if status
        .lines()
        .find_map(|line| line.strip_prefix("NoNewPrivs:"))
        .map(str::trim)
        != Some("1")
        || !std::fs::read_to_string("/proc/self/cgroup")?.contains("hepta-fixed-holdout-custody-")
    {
        return Err("product provider requires the existing bounded custody service".into());
    }
    Ok(())
}
pub(crate) fn private_parent(path: &Path) -> HostResult<File> {
    let parent = path.parent().ok_or("report parent")?;
    if !path.is_absolute()
        || path
            .components()
            .any(|c| matches!(c, Component::CurDir | Component::ParentDir))
    {
        return Err("canonical report location required".into());
    }
    for ancestor in parent.ancestors() {
        let meta = std::fs::symlink_metadata(ancestor)?;
        if !meta.is_dir() || meta.uid() != 0 || meta.mode() & 0o022 != 0 {
            return Err("unprotected report ancestor".into());
        }
    }
    if parent.metadata()?.mode() & 0o077 != 0 {
        return Err("original evaluation inputs require private Root custody".into());
    }
    Ok(File::open(parent)?)
}
fn publish(path: &Path, bytes: &[u8]) -> HostResult<Digest32> {
    if bytes.len() > 24 * 1024 * 1024 {
        return Err("bounded product preflight publication".into());
    }
    let parent = private_parent(path)?;
    match OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
    {
        Ok(mut file) => {
            file.write_all(bytes)?;
            file.sync_all()?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            if read_root_review_input(path, 24 * 1024 * 1024)? != bytes {
                return Err("immutable product preflight publication conflicts".into());
            }
            File::open(path)?.sync_all()?;
        }
        Err(error) => return Err(error.into()),
    }
    parent.sync_all()?;
    Ok(Digest32::of_bytes(bytes))
}
/// Root-only preflight. It deliberately has no arbitrary signed-result ingress,
/// no Selector key and no unregistered final-holdout consumption operation.
pub fn inspect_fixed_product_evaluation(path: &Path) -> HostResult<()> {
    root_boundary()?;
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-product-evaluation-preflight.config.v1"
        || Digest32::of_bytes(&read_root_review_input(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
        )?) != config.program_digest.parse::<Digest32>()?
    {
        return Err("protected product preflight policy/program".into());
    }
    let batch = source(&config.source_batch, 16 * 1024 * 1024)?;
    let objective = config.objective_digest.parse()?;
    let (graph, tasks, rows) = frozen_source_graph(&batch, objective)?;
    // The same original custody program checks its independently retained CAS
    // witness. No second writer, new fence, registration, or gold release exists.
    source(&config.custody_program, 128 * 1024 * 1024)?;
    let custody_config = source(&config.custody_config, 16 * 1024)?;
    let policy: Value = serde_json::from_slice(&custody_config)?;
    if policy["program_digest"] != config.custody_program.digest {
        return Err("original custody executable pin".into());
    }
    let directory = PathBuf::from(
        policy["private_directory"]
            .as_str()
            .ok_or("custody directory")?,
    );
    let cas_path = directory.join("holdout-cas.bin");
    let cas_before = read_root_review_input(&cas_path, 32 * 1024 * 1024)?;
    let output = std::process::Command::new(&config.custody_program.path)
        .arg("--inspect")
        .arg(&config.custody_config.path)
        .output()?;
    if !output.status.success()
        || output.stdout.len() > 16 * 1024
        || output.stderr.len() > 16 * 1024
    {
        return Err("original custody inspection unavailable or rejected".into());
    }
    let holdout: Value = serde_json::from_slice(&output.stdout)?;
    if holdout["schema"] != "hepta.fixed-source-holdout.prepared.v1"
        || holdout["config_digest"] != config.custody_config.digest
        || holdout["holdout_consumed"] != false
        || holdout["evaluation_plan_registered"] != false
        || holdout["qualified"] != false
        || holdout["record_count"] != 0
        || cas_before != read_root_review_input(&cas_path, 32 * 1024 * 1024)?
    {
        return Err("holdout is no longer an unchanged, unregistered source".into());
    }
    let evaluator_program =
        Digest32::of_bytes(&source(&config.evaluator_program, 128 * 1024 * 1024)?);
    let evaluator_policy = source(&config.evaluator_config, 32 * 1024)?;
    let evaluator_policy_value: Value = serde_json::from_slice(&evaluator_policy)?;
    if evaluator_policy_value["objective_digest"] != config.objective_digest {
        return Err("source/evaluation objective scope".into());
    }
    let result = source(&config.evaluator_result, 64 * 1024)?;
    let now = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?;
    let independent =
        read_fixed_calibration_result(&evaluator_policy, evaluator_program, &result, now)?;
    let report = serde_json::json!({"schema":"hepta.fixed-product-evaluation-preflight.v1",
        "state":"pending_supported_behavior_cut","product_runner_execution":"pending",
        "config_digest":Digest32::of_bytes(&config_bytes).to_string(),"objective_digest":config.objective_digest,
        "source_batch_digest":config.source_batch.digest,"source_graph_digest":graph.source_graph_digest().to_string(),
        "source_scope_digest":graph.scope_digest().to_string(),"complete_source_tasks":tasks,"calibration_rows":rows,
        "source_graph_scope":"frozen_calibration_batch_only; not the full training-plus-final product graph",
        "source_is_preregistered_execution_plan":false,"native_execution_timestamps_invented":false,
        "independent_calibration":independent,"original_holdout_owner":holdout,
        "holdout_cas_bytes_digest":Digest32::of_bytes(&cas_before).to_string(),
        "pending_prerequisites":["authentic_deployed_reference_execution_cut","supported_common_logged_behavior_cut",
            "signed_durably_registered_product_plan_before_final_execution","independent_exact_post_execution_qualification_evidence"],
        "full_information_benchmark_profile_supported":false,"classification_confidence_is_behavior_probability":false,
        "holdout_consumed":false,"qualified":false,"production_activation":false,"authority_grants_any":false,
        "original_masked_source_batch":serde_json::from_slice::<Value>(&batch)?});
    let bytes = serde_json::to_vec(&report)?;
    let publication = publish(&config.report_path, &bytes)?;
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.fixed-product-evaluation-preflight-publication.v1",
        "state":"pending_supported_behavior_cut","publication_digest":publication.to_string(),
        "source_graph_digest":graph.source_graph_digest().to_string(),"complete_source_tasks":tasks,"calibration_rows":rows,
        "holdout_consumed":false,"qualified":false,"authority_grants_any":false})
    );
    Ok(())
}
