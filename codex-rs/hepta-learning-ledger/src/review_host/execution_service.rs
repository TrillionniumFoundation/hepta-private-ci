//! Fixed program execution with retained status; no shell or arbitrary-sign service.
use super::files::Access;
use super::files::ReviewResult;
use super::files::create_private;
use super::files::read_root;
use super::files::root_file;
use super::generator_wire::program_digest;
use super::independent_trust::IndependentTrust;
use codex_hepta_types::Digest32;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;

pub(super) fn generate(
    trust: &IndependentTrust,
    contract: &Path,
    output: &Path,
) -> ReviewResult<()> {
    let status_path = output.with_extension("status.json");
    if output.exists() || status_path.exists() {
        let status: serde_json::Value =
            serde_json::from_slice(&read_root(&status_path, 4096, Access::Private)?)?;
        if status["succeeded"] != true
            || status["output_digest"]
                != Digest32::of_bytes(&read_root(output, 4 * 1024 * 1024, Access::Private)?)
                    .to_string()
            || status["generator_program_digest"] != trust.generator_program.to_string()
            || status["contract_digest"]
                != Digest32::of_bytes(&read_root(contract, 32 * 1024, Access::Immutable)?)
                    .to_string()
        {
            return Err("incomplete or changed retained generator execution".into());
        }
        return Ok(());
    }
    let output_file = create_private(output, &[])?;
    let error_path = output.with_extension("stderr.log");
    let error_file = create_private(&error_path, &[])?;
    // systemd first bounds the service; the only initial capabilities permit
    // fixed setpriv to drop UID/groups and then every capability before exec.
    let unit = format!(
        "hepta-native-generator-{}-{}",
        &trust.config_digest.to_string()[..16],
        std::process::id()
    );
    let status = Command::new("/usr/bin/systemd-run")
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .args(["--quiet", "--wait", "--pipe", "--collect"])
        .arg(format!("--unit={unit}"))
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
        .arg(format!("--reuid={}", trust.config.generator_uid))
        .arg(format!("--regid={}", trust.config.generator_uid))
        .args([
            "--clear-groups",
            "--inh-caps=-all",
            "--bounding-set=-all",
            "--ambient-caps=-all",
            "--no-new-privs",
        ])
        .arg(&trust.config.generator_program_path)
        .arg("--request")
        .arg(contract)
        .stdin(Stdio::null())
        .stdout(Stdio::from(output_file))
        .stderr(Stdio::from(error_file))
        .status()?;
    if !status.success() {
        return Err(format!("fixed native generator failed: {status}").into());
    }
    if program_digest(&trust.config.generator_program_path)? != trust.generator_program
        || program_digest(&trust.config.scorer_path)?
            != trust.config.scorer_digest.parse::<Digest32>()?
    {
        return Err("generator/scorer changed during bounded execution".into());
    }
    super::files::mutable_file(output)?.sync_all()?;
    let output_digest = Digest32::of_bytes(&read_root(output, 4 * 1024 * 1024, Access::Private)?);
    create_private(
        &status_path,
        &serde_json::to_vec(
            &serde_json::json!({"succeeded":true,"output_digest":output_digest.to_string(),"generator_program_digest":trust.generator_program.to_string(),"contract_digest":Digest32::of_bytes(&read_root(contract,32*1024,Access::Immutable)?).to_string(),"no_new_privileges":true,"groups_and_capabilities":"all_dropped_before_generator_exec","memory_max_bytes":268435456,"tasks_max":16,"cpu_quota_percent":100}),
        )?,
    )?;
    Ok(())
}
pub(super) fn score(
    trust: &IndependentTrust,
    manifest: &Path,
    manifest_digest: Digest32,
    inputs: &Path,
    output: &Path,
) -> ReviewResult<()> {
    let status_path = output.with_extension("status.json");
    if output.exists() || status_path.exists() {
        let status: serde_json::Value =
            serde_json::from_slice(&read_root(&status_path, 4096, Access::Private)?)?;
        if status["succeeded"] != true
            || status["output_digest"]
                != Digest32::of_bytes(&read_root(output, 4 * 1024 * 1024, Access::Private)?)
                    .to_string()
            || status["manifest_digest"] != manifest_digest.to_string()
            || status["scorer_digest"] != trust.config.scorer_digest
        {
            return Err("incomplete or changed retained evaluator execution".into());
        }
        return Ok(());
    }
    let file = create_private(output, &[])?;
    let error_file = create_private(&output.with_extension("stderr.log"), &[])?;
    let status = Command::new(&trust.config.scorer_path)
        .env_clear()
        .args([
            manifest.as_os_str(),
            std::ffi::OsStr::new(&manifest_digest.to_string()),
        ])
        .stdin(Stdio::from(root_file(inputs, Access::Immutable)?))
        .stdout(Stdio::from(file))
        .stderr(Stdio::from(error_file))
        .status()?;
    if !status.success()
        || program_digest(&trust.config.scorer_path)?
            != trust.config.scorer_digest.parse::<Digest32>()?
    {
        return Err("fixed evaluator offline execution failed or scorer changed".into());
    }
    super::files::mutable_file(output)?.sync_all()?;
    create_private(
        &status_path,
        &serde_json::to_vec(
            &serde_json::json!({"succeeded":true,"output_digest":Digest32::of_bytes(&read_root(output,4*1024*1024,Access::Private)?).to_string(),"manifest_digest":manifest_digest.to_string(),"scorer_digest":trust.config.scorer_digest}),
        )?,
    )?;
    Ok(())
}
