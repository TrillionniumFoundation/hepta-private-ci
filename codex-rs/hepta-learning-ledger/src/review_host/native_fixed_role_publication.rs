//! Original exclusive output reservation and completed-only observation shared
//! by a finite set of enrolled role purposes. This is no extra journal, signer
//! or evidence verifier. Unknown consumed slots never dispatch again.
use super::files::Access;
use super::files::ReviewResult;
use super::files::create_private;
use super::files::read_root;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::path::Path;
use std::process::ExitStatus;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OriginalFixedRolePurposeV1 {
    PreRegistrationArtifactPublication,
    FrozenGenerator,
    ParameterGenerator,
    PairedGeneratorRegistration,
    ParameterObserver,
    PairedCustodyAdmission,
    PairedCustodyExecution,
    PairedCustodyFinish,
    PairedEvaluator,
    ParameterEvaluator,
    PreparationEvaluator,
    ServingScopeEvaluator,
    PreRegistrationEvaluator,
    PreRegistrationSelector,
    CycleSelector,
    CanaryObserver,
}
impl OriginalFixedRolePurposeV1 {
    fn schema(self) -> &'static str {
        match self {
            Self::PreRegistrationArtifactPublication => {
                "hepta.native-parameter-artifact-publication-execution.v1"
            }
            Self::FrozenGenerator => "hepta.native-frozen-generator-execution.v1",
            Self::ParameterGenerator => "hepta.native-parameter-generator-execution.v1",
            Self::PairedGeneratorRegistration => {
                "hepta.native-paired-generator-registration-execution.v1"
            }
            Self::ParameterObserver => "hepta.native-parameter-observer-execution.v1",
            Self::PairedCustodyAdmission => "hepta.native-paired-custody-admission-execution.v1",
            Self::PairedCustodyExecution => "hepta.native-paired-custody-numeric-execution.v1",
            Self::PairedCustodyFinish => "hepta.native-paired-custody-finish-execution.v1",
            Self::PairedEvaluator => "hepta.native-paired-evaluator-execution.v1",
            Self::ParameterEvaluator => "hepta.native-parameter-evaluator-execution.v1",
            Self::PreparationEvaluator => "hepta.native-parameter-preparation-execution.v1",
            Self::ServingScopeEvaluator => "hepta.native-serving-scope-incompatible-execution.v1",
            Self::PreRegistrationEvaluator => "hepta.native-parameter-preregistration-execution.v1",
            Self::PreRegistrationSelector => {
                "hepta.native-parameter-preregistered-selector-execution.v1"
            }
            Self::CycleSelector => "hepta.native-cycle-selector-execution.v1",
            Self::CanaryObserver => "hepta.native-canary-observer-execution.v1",
        }
    }
    fn maximum(self) -> u64 {
        match self {
            Self::PreRegistrationArtifactPublication => 64 * 1024,
            Self::FrozenGenerator => 16 * 1024,
            Self::CycleSelector | Self::CanaryObserver | Self::PreRegistrationSelector => 32 * 1024,
            Self::PairedGeneratorRegistration
            | Self::PairedCustodyAdmission
            | Self::PairedCustodyExecution => 128 * 1024 * 1024,
            Self::PairedEvaluator | Self::PairedCustodyFinish => 3 * 1024 * 1024,
            Self::PreRegistrationEvaluator => 576 * 1024,
            _ => 16 * 1024 * 1024,
        }
    }
}

// FrozenGenerator retains this exact original four-field status codec.
#[derive(Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(super) struct FixedRoleExecutionStatusV1 {
    pub schema: String,
    pub request_digest: String,
    pub program_digest: String,
    pub output_digest: String,
}

fn root(purpose: Option<OriginalFixedRolePurposeV1>) -> ReviewResult<()> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    for field in ["Uid:", "Gid:"] {
        if field == "Gid:"
            && purpose.is_none_or(|value| value == OriginalFixedRolePurposeV1::FrozenGenerator)
        {
            continue;
        }
        let ids = status
            .lines()
            .find_map(|line| line.strip_prefix(field))
            .ok_or("actual Root role owner identity")?
            .split_whitespace()
            .collect::<Vec<_>>();
        if ids.len() != 4 || ids.iter().any(|id| *id != "0") {
            return Err("fixed role publication requires actual Root owner".into());
        }
    }
    Ok(())
}

/// Sole original create_new consumption, durable before any role effect. A
/// second caller cannot obtain these descriptors or dispatch this same slot.
pub fn reserve_original_fixed_role_output_v1(output: &Path) -> ReviewResult<(File, File)> {
    root(None)?;
    let output_file = create_private(output, &[])?;
    let error_file = create_private(&output.with_extension("stderr.log"), &[])?;
    Ok((output_file, error_file))
}
pub fn observe_original_fixed_role_publication_v1(
    purpose: OriginalFixedRolePurposeV1,
    output: &Path,
    request_digest: Digest32,
    program_digest: Digest32,
) -> ReviewResult<Option<Vec<u8>>> {
    root(Some(purpose))?;
    if request_digest.is_zero() || program_digest.is_zero() {
        return Err("fixed role original identity absent".into());
    }
    let status_path = output.with_extension("status.json");
    for path in [output, &status_path] {
        match std::fs::symlink_metadata(path) {
            Ok(_) => (),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        }
    }
    let bytes = read_root(output, purpose.maximum(), Access::Private)?;
    let status_bytes = read_root(&status_path, 4096, Access::Private)?;
    let Ok(status) = serde_json::from_slice::<FixedRoleExecutionStatusV1>(&status_bytes) else {
        return Ok(None);
    };
    let expected = FixedRoleExecutionStatusV1 {
        schema: purpose.schema().into(),
        request_digest: request_digest.to_string(),
        program_digest: program_digest.to_string(),
        output_digest: Digest32::of_bytes(&bytes).to_string(),
    };
    if bytes.is_empty() || status != expected {
        return Ok(None);
    }
    if read_root(&status_path, 4096, Access::Private)? != status_bytes
        || read_root(output, purpose.maximum(), Access::Private)? != bytes
    {
        return Err("original fixed role publication changed during observation".into());
    }
    Ok(Some(bytes))
}

/// Dispatch only a genuinely unconsumed original output. The trusted fixed
/// purpose caller checks all native signatures/current facts in `verify`.
/// No timeout, cancellation or error manufactures a terminal completion.
pub fn execute_original_fixed_role_publication_v1(
    purpose: OriginalFixedRolePurposeV1,
    output: &Path,
    request_digest: Digest32,
    program_digest: Digest32,
    dispatch: impl FnOnce(File, File) -> ReviewResult<ExitStatus>,
    verify: impl Fn(&[u8]) -> ReviewResult<()>,
) -> ReviewResult<Option<Vec<u8>>> {
    root(Some(purpose))?;
    if request_digest.is_zero() || program_digest.is_zero() {
        return Err("fixed role original identity absent".into());
    }
    let status_path = output.with_extension("status.json");
    if output.try_exists()? || status_path.try_exists()? {
        let completed = observe_original_fixed_role_publication_v1(
            purpose,
            output,
            request_digest,
            program_digest,
        )?;
        if let Some(bytes) = &completed {
            verify(bytes)?;
        }
        return Ok(completed);
    }
    let (stdout, stderr) = reserve_original_fixed_role_output_v1(output)?;
    let exit = dispatch(stdout, stderr)?;
    if !exit.success() {
        return Ok(None);
    }
    let bytes = read_root(output, purpose.maximum(), Access::Private)?;
    if bytes.is_empty() {
        return Ok(None);
    }
    verify(&bytes)?;
    let status = FixedRoleExecutionStatusV1 {
        schema: purpose.schema().into(),
        request_digest: request_digest.to_string(),
        program_digest: program_digest.to_string(),
        output_digest: Digest32::of_bytes(&bytes).to_string(),
    };
    create_private(&status_path, &serde_json::to_vec(&status)?)?;
    observe_original_fixed_role_publication_v1(purpose, output, request_digest, program_digest)
}

#[cfg(test)]
#[path = "native_fixed_role_publication_tests.rs"]
mod tests;
