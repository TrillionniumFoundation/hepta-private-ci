//! Finite independent-role process launch over the original Root effect slot.
//! The caller must durably consume its original purpose intent before calling.
//! This owner never allocates a journal, retries an unknown launch, reads a seed
//! or decides whether actual role output is valid. Each role validates itself.
use codex_hepta_agent_components::intelligence_eval::ParameterRoleSourceV3;
use codex_hepta_agent_components::intelligence_eval::verify_registered_operational_program_v3;
use codex_hepta_types::Digest32;
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;

type HostResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ParameterRoleExecutionPurposeV1 {
    GeneratorProfile,
    GeneratorPairedRegistration,
    ObserverAdmission,
    ObserverPairedAdmission,
    ObserverPairedExecution,
    ObserverPairedFinish,
    ObserverCanary,
    EvaluatorNoChange,
    EvaluatorPairedReview,
    EvaluatorParameterReview,
    EvaluatorPreparation,
    EvaluatorPreRegistration,
    SelectorPreRegistration,
    SelectorCycleStage,
}
impl ParameterRoleExecutionPurposeV1 {
    fn contract(self) -> (&'static str, &'static str, bool, bool) {
        match self {
            Self::GeneratorProfile => (
                "hepta-native-generator-",
                "--parameter-profile",
                false,
                false,
            ),
            Self::GeneratorPairedRegistration => (
                "hepta-native-generator-",
                "--paired-preregister",
                false,
                false,
            ),
            Self::ObserverAdmission => (
                "hepta-fixed-holdout-custody-",
                "--parameter-admission",
                true,
                false,
            ),
            Self::ObserverPairedAdmission => (
                "hepta-fixed-holdout-custody-",
                "--paired-admit",
                true,
                false,
            ),
            Self::ObserverPairedExecution => (
                "hepta-fixed-holdout-custody-",
                "--paired-execute",
                true,
                false,
            ),
            Self::ObserverPairedFinish => (
                "hepta-fixed-holdout-custody-",
                "--paired-finish",
                true,
                false,
            ),
            Self::ObserverCanary => (
                "hepta-fixed-holdout-custody-",
                "--canary-observation",
                true,
                true,
            ),
            Self::EvaluatorNoChange => (
                "hepta-fixed-calibration-eval-",
                "--parameter-no-change",
                false,
                false,
            ),
            Self::EvaluatorPairedReview => (
                "hepta-fixed-calibration-eval-",
                "--paired-review",
                false,
                false,
            ),
            Self::EvaluatorParameterReview => (
                "hepta-fixed-calibration-eval-",
                "--parameter-review",
                false,
                false,
            ),
            Self::EvaluatorPreparation => (
                "hepta-fixed-calibration-eval-",
                "--parameter-preparation",
                false,
                false,
            ),
            Self::EvaluatorPreRegistration => (
                "hepta-fixed-calibration-eval-",
                "--parameter-pre-registration",
                false,
                false,
            ),
            Self::SelectorPreRegistration => (
                "hepta-fixed-selector-",
                "select-parameter-pre-registration",
                true,
                true,
            ),
            Self::SelectorCycleStage => (
                "hepta-fixed-selector-",
                "select-self-iteration-stage",
                true,
                true,
            ),
        }
    }
}

/// Actual independently enrolled program and immutable purpose configuration.
/// The Root service supplies only public pins and key paths inside the config;
/// signing seeds and evaluation data remain in the original role's custody.
pub struct ParameterRoleExecutionV1 {
    pub purpose: ParameterRoleExecutionPurposeV1,
    pub program: ParameterRoleSourceV3,
    pub configuration: ParameterRoleSourceV3,
    pub uid: u32,
    pub gid: u32,
    pub original_effect_digest: Digest32,
    pub inaccessible_paths: Vec<std::path::PathBuf>,
}

/// Await the actual bounded service terminal without a dispatch timeout. A
/// failed launch/result is still an actual effect-slot fact, never no-effect
/// authority. Output FDs are the Root service's existing write-once slot files.
pub fn execute_parameter_role_v1(
    request: &ParameterRoleExecutionV1,
    output: File,
    error: File,
) -> HostResult<ExitStatus> {
    require_root_caller()?;
    let (prefix, argument, root_role, pinned_argument) = request.purpose.contract();
    if request.original_effect_digest.is_zero()
        || root_role != (request.uid == 0 && request.gid == 0)
        || (!root_role && (request.uid == 0 || request.gid == 0))
    {
        return Err("finite role purpose/actual UID/GID/effect identity".into());
    }
    let program_pin: Digest32 = request.program.digest.parse()?;
    verify_registered_operational_program_v3(&request.program.path, program_pin)?;
    let configuration = request.configuration.read(64 * 1024)?;
    let output_guard = output.try_clone()?;
    let error_guard = error.try_clone()?;
    for file in [&output_guard, &error_guard] {
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.gid() != 0
            || metadata.mode() & 0o077 != 0
            || metadata.nlink() != 1
            || metadata.len() != 0
        {
            return Err("original Root purpose output slot must be fresh and exclusive".into());
        }
    }
    if output_guard.metadata()?.dev() == error_guard.metadata()?.dev()
        && output_guard.metadata()?.ino() == error_guard.metadata()?.ino()
    {
        return Err("original distinct role stdout/stderr slots".into());
    }
    let unit = format!(
        "{prefix}{}-{}",
        request.original_effect_digest,
        std::process::id()
    );
    let mut command = Command::new("/usr/bin/systemd-run");
    command
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
        ]);
    for path in &request.inaccessible_paths {
        if !path.is_absolute()
            || path.components().any(|part| {
                matches!(
                    part,
                    std::path::Component::CurDir | std::path::Component::ParentDir
                )
            })
            || path
                .to_string_lossy()
                .bytes()
                .any(|v| v.is_ascii_whitespace())
        {
            return Err("finite role denial path must be canonical without whitespace".into());
        }
    }
    if !request.inaccessible_paths.is_empty() {
        command.arg(format!(
            "--property=InaccessiblePaths={}",
            request
                .inaccessible_paths
                .iter()
                .map(|p| p.display().to_string())
                .collect::<Vec<_>>()
                .join(" ")
        ));
    }
    command
        .arg("/usr/bin/setpriv")
        .arg(format!("--reuid={}", request.uid))
        .arg(format!("--regid={}", request.gid))
        .args([
            "--clear-groups",
            "--inh-caps=-all",
            "--bounding-set=-all",
            "--ambient-caps=-all",
            "--no-new-privs",
        ])
        .arg(&request.program.path)
        .arg(argument)
        .arg(&request.configuration.path);
    if pinned_argument {
        command.arg(&request.configuration.digest);
    }
    let status = command
        .stdin(Stdio::null())
        .stdout(Stdio::from(output))
        .stderr(Stdio::from(error))
        .status()?;
    output_guard.sync_all()?;
    error_guard.sync_all()?;
    verify_registered_operational_program_v3(&request.program.path, program_pin)?;
    if request.configuration.read(64 * 1024)? != configuration {
        return Err("finite role program/configuration changed during actual effect".into());
    }
    Ok(status)
}
fn require_root_caller() -> HostResult<()> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    for field in ["Uid:", "Gid:"] {
        let values = status
            .lines()
            .find_map(|line| line.strip_prefix(field))
            .ok_or("actual Root role dispatcher identity")?;
        if values.split_whitespace().count() != 4
            || values.split_whitespace().any(|value| value != "0")
        {
            return Err("finite role dispatch requires the original actual Root service".into());
        }
    }
    Ok(())
}
