//! Same-process adapter to the actual evaluated completion-readiness owner.
//! It changes transport custody only; every response uses original Source/Cell.

use super::*;
use codex_hepta_neuron::AnchorWitnessStore;
use super::super::OriginalCircuitLearningReadClientV1;
use super::super::OriginalCircuitLearningReadOwnerV1;
use super::super::fixture as reads;

pub(crate) fn client(
    context: OriginalCircuitEvaluatedLearningReadContextV1,
) -> anyhow::Result<(OriginalCircuitCompletionReadinessClientV1, HostAuthorityPeerChannel)> {
    anyhow::ensure!(context.mode() == original::Mode::NextUse);
    let (original, server) = reads::evaluated_client(context)?;
    let OriginalCircuitLearningReadClientV1 { context, binding, channel, retained } = original;
    Ok((OriginalCircuitCompletionReadinessClientV1 { context, binding, channel, retained }, server))
}

pub(crate) fn reject_legacy_purpose<C: AnchorWitnessStore, S: AnchorWitnessStore>(
    owner: &OriginalCircuitLearningReadOwnerV1<C, S>,
    context: OriginalCircuitEvaluatedLearningReadContextV1,
) -> anyhow::Result<()> {
    let profile = ReadProfile::Evaluated(context);
    let mut request = Request::from_profile(&profile, profile.binding(now()?)?, 1)?;
    request.purpose = PURPOSE.into();
    anyhow::ensure!(matches!(
        owner.readiness_response(&serde_json::to_vec(&request)?, 1),
        Err(Error::Binding("fixed evaluated completion-readiness purpose"))
    ));
    Ok(())
}
