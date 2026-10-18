//! Original Root-custody boundary for the one physical canary observation purpose.
use super::*;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RootCustody {
    program: Source,
    trust_configuration: Source,
    cycle_approval: Option<Source>,
}

pub(super) fn validate_purpose(config: &Configuration, root: bool) -> HostResult<()> {
    let actors = [
        config.consumer.uid,
        config.evaluation.uid,
        config.selection.uid,
    ];
    if !root {
        let uids = [actors[0], actors[1], actors[2], config.observer.uid];
        if config.schema != "hepta.cpu-neuron.self-iteration-observation.v1"
            || config.root_custody.is_some()
            || config.inaccessible_paths.len() != 5
            || uids.contains(&0)
            || uids
                .iter()
                .enumerate()
                .any(|(index, uid)| uids[..index].contains(uid))
        {
            return Err("original O must be physically distinct from G/E/S".into());
        }
    } else if config.schema != "hepta.cpu-neuron.self-iteration-root-custody-observation.v1"
        || config.root_custody.is_none()
        || config.observer.uid != 0
        || config.observer.gid != 0
        || !config.inaccessible_paths.is_empty()
        || actors[0] == 0
        || actors[1] == 0
        || actors
            .iter()
            .enumerate()
            .any(|(index, uid)| actors[..index].contains(uid))
    {
        return Err("fixed Root O requires the original independent G/E/S purposes".into());
    }
    Ok(())
}

pub(super) fn key_boundary(
    custody: &RootCustody,
    inputs: &Inputs,
    observer: &Role,
) -> HostResult<()> {
    verify_original_observer_process_boundary_v1()?;
    if custody.program.path == inputs.profile.program.path
        || digest(&custody.program.digest)? == digest(&inputs.profile.program.digest)?
    {
        return Err("Root Observer and Selector must execute different original programs".into());
    }
    role::require_actual_program(&custody.program, observer)?;
    inputs.revalidate()
}

pub(super) fn key(
    custody: &RootCustody,
    inputs: &Inputs,
    observer: &Role,
) -> HostResult<SigningKey> {
    key_boundary(custody, inputs, observer)?;
    role::actual_role_for_program(&custody.program, observer)
}

pub(super) fn verify(
    custody: &RootCustody,
    observer: &ledger::TrustedLearningSignerV1,
) -> HostResult<()> {
    let trust = custody.trust_configuration.read(64 * 1024)?;
    let approval = custody
        .cycle_approval
        .as_ref()
        .map(|source| source.read(64 * 1024))
        .transpose()?;
    verify_original_observer_controller(
        digest(&custody.program.digest)?,
        &trust,
        approval.as_deref(),
        observer,
    )
}

pub(super) fn selection(config: &Configuration, maximum: usize) -> HostResult<Vec<u8>> {
    if config.root_custody.is_some() && config.selection.uid == 0 {
        // Only this explicit Root-custody purpose admits the original Root
        // Selector publication. Its full role signature is verified by the
        // common observation owner; the old non-root input reader is unchanged.
        read_root_review_input(&config.selection.path, maximum as u64)
    } else {
        config.selection.read(maximum)
    }
}

#[cfg(test)]
#[path = "initial_cpu_iteration_observation_root_tests.rs"]
mod tests;
