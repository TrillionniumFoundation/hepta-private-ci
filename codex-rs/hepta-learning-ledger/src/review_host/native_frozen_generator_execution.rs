//! Root dispatch of the original fixed Generator; no private-key read path.

use super::execution_service::GeneratorPurpose;
use super::execution_service::launch_generator;
use super::files::Access;
use super::files::ReviewResult;
use super::files::create_private;
use super::files::read_root;
use super::generator_wire::bounded_generator_controller;
use super::generator_wire::now_ms;
use super::generator_wire::program_digest;
use super::native_generator::NativeFrozenGeneratorRequestV1;
use super::transfer::ReviewEvidenceWireV1;
use crate::LearningEvidenceRoleV1;
use crate::SignedLearningEvidenceV1;
use crate::activate_learning_trust;
use codex_hepta_types::Digest32;
use std::path::Path;

type FrozenExecutionStatus = super::native_fixed_role_publication::FixedRoleExecutionStatusV1;

/// Execute an immutable request already constructed by the original Root
/// window owner after full round, model and native-owner validation. This
/// launcher validates custody, fixed purpose and original public trust; it
/// does not turn an Agent's candidate bytes into an approved window.
/// Existing successful output is verified without dispatch. Partial, failed
/// or expired output remains consumed and cannot be retried with new effects.
pub fn execute_root_approved_frozen_generator(
    program: &Path,
    request_path: &Path,
    output: &Path,
) -> ReviewResult<SignedLearningEvidenceV1> {
    execute_or_observe(program, request_path, output, PublicationMode::Dispatch)?
        .ok_or_else(|| "incomplete retained frozen Generator execution".into())
}

/// Observe only an already completed immutable output for the original Root
/// request. It never dispatches a process, consumes a new output slot or writes
/// a completion marker. Missing or partial publication remains unknown.
pub fn observe_root_approved_frozen_generator(
    program: &Path,
    request_path: &Path,
    output: &Path,
) -> ReviewResult<Option<SignedLearningEvidenceV1>> {
    execute_or_observe(program, request_path, output, PublicationMode::Observe)
}

#[derive(Clone, Copy)]
enum PublicationMode {
    Dispatch,
    Observe,
}

fn execute_or_observe(
    program: &Path,
    request_path: &Path,
    output: &Path,
    mode: PublicationMode,
) -> ReviewResult<Option<SignedLearningEvidenceV1>> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    if status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .is_none_or(|uids| {
            let ids = uids.split_whitespace().collect::<Vec<_>>();
            ids.len() != 4 || ids.iter().any(|id| *id != "0")
        })
    {
        return Err("fixed Generator dispatch requires the actual Root owner".into());
    }
    let request_bytes = read_root(request_path, 64 * 1024, Access::Immutable)?;
    let request: NativeFrozenGeneratorRequestV1 = serde_json::from_slice(&request_bytes)?;
    let request_digest = Digest32::of_bytes(&request_bytes);
    let program_before = program_digest(program)?;
    let now = now_ms()?;
    if request.schema != "hepta.native-frozen-generator-request.v1"
        || request.uid == 0
        || request.generator_program_digest.parse::<Digest32>()? != program_before
        || request.expires_at_ms <= now
        || request.expires_at_ms > now.saturating_add(3_600_000)
        || !(2..=32).contains(&request.inaccessible_paths.len())
    {
        return Err("Root-approved Generator purpose, executable or deadline changed".into());
    }
    let window = read_root(
        &request.window_authorization_path,
        64 * 1024,
        Access::Immutable,
    )?;
    let window_digest: Digest32 = request.window_authorization_digest.parse()?;
    if window_digest.is_zero() || Digest32::of_bytes(&window) != window_digest {
        return Err("Root-approved Generator window changed".into());
    }
    let payload = read_root(&request.frozen_payload_path, 512 * 1024, Access::Immutable)?;
    super::native_generator::validate_frozen_payload(
        &payload,
        request.frozen_payload_digest.parse()?,
    )?;
    let (root, distribution) = request.trust.native()?;
    let controller = bounded_generator_controller(
        program_before,
        request.uid,
        program_digest(Path::new("/usr/bin/setpriv"))?,
        program_digest(Path::new("/usr/bin/systemd-run"))?,
    )?;
    if !distribution
        .distribution
        .trust
        .signers
        .iter()
        .any(|signer| {
            signer.principal.principal_id.as_str() == request.principal_id
                && signer.principal.principal_id.as_str() == "native-unprivileged-generator"
                && signer.roles == [LearningEvidenceRoleV1::Generator]
                && signer.controller_id == controller
        })
    {
        return Err("original Generator controller is absent from public trust".into());
    }
    let trust = activate_learning_trust(&root, distribution, None, now)?;
    let status_path = output.with_extension("status.json");
    let retained = output.exists() || status_path.exists();
    if !retained && matches!(mode, PublicationMode::Dispatch) {
        let exit = launch_generator(
            request.uid,
            program,
            request_digest,
            GeneratorPurpose::FrozenIteration,
            request_path,
            output,
        )?;
        if !exit.success() {
            return Err(format!("original frozen Generator failed: {exit}").into());
        }
    }
    if program_digest(program)? != program_before
        || read_root(request_path, 64 * 1024, Access::Immutable)? != request_bytes
        || read_root(
            &request.window_authorization_path,
            64 * 1024,
            Access::Immutable,
        )? != window
        || read_root(&request.frozen_payload_path, 512 * 1024, Access::Immutable)? != payload
    {
        return Err("original frozen Generator sources changed during execution".into());
    }
    let output_bytes = if retained || matches!(mode, PublicationMode::Observe) {
        let Some(bytes) = read_completed_output(output, request_digest, program_before)? else {
            return match mode {
                PublicationMode::Observe => Ok(None),
                PublicationMode::Dispatch => {
                    Err("incomplete or changed retained frozen Generator execution".into())
                }
            };
        };
        bytes
    } else {
        read_root(output, 16 * 1024, Access::Private)?
    };
    let expected_status = FrozenExecutionStatus {
        schema: "hepta.native-frozen-generator-execution.v1".to_string(),
        request_digest: request_digest.to_string(),
        program_digest: program_before.to_string(),
        output_digest: Digest32::of_bytes(&output_bytes).to_string(),
    };
    let evidence: ReviewEvidenceWireV1 = serde_json::from_slice(&output_bytes)?;
    let evidence = evidence.native()?;
    if evidence.principal_id.as_str() != request.principal_id
        || evidence.expires_at > request.expires_at_ms
    {
        return Err("original frozen Generator evidence scope changed".into());
    }
    let observed = now_ms()?;
    trust.revalidate_at(observed)?;
    trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &evidence,
        &payload,
        observed,
    )?;
    if !retained && matches!(mode, PublicationMode::Dispatch) {
        create_private(&status_path, &serde_json::to_vec(&expected_status)?)?;
    }
    Ok(Some(evidence))
}

fn read_completed_output(
    output: &Path,
    request_digest: Digest32,
    program_digest: Digest32,
) -> ReviewResult<Option<Vec<u8>>> {
    super::native_fixed_role_publication::observe_original_fixed_role_publication_v1(
        super::native_fixed_role_publication::OriginalFixedRolePurposeV1::FrozenGenerator,
        output,
        request_digest,
        program_digest,
    )
}

#[cfg(test)]
#[path = "native_frozen_generator_execution_tests.rs"]
mod tests;
