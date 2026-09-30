//! Concrete fail-closed canonical intelligence profile for ordinary Agentd startup.
//!
//! This profile consumes the already durable `RunStartRecordV1`, revalidates the
//! signed seven-owner authority file and drives the existing canonical owner
//! chain to an explicit abstention. It proves real startup and owner composition
//! without inventing an action, evaluator result, model call or external effect.
//! A product that wants action selection must install a richer host-owned
//! provider; this conservative profile is not that claim.

use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agent_components::intelligence::CanonicalBudgetV1;
use codex_hepta_agent_components::intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_agent_components::intelligence::CanonicalIntelligenceSnapshotV1;
use codex_hepta_agent_components::intelligence::CanonicalSnapshotRequestV1;
use codex_hepta_agent_components::intelligence::CurrentOwnerStateV1;
use codex_hepta_agent_components::intelligence::LegalActionCandidateSetRequestV1;
use codex_hepta_agent_components::intelligence::LegalActionCandidateV1;
use codex_hepta_agent_components::intelligence::OwnerBindingV1;
use codex_hepta_agent_components::learning_ledger::RunStartRecordV1;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::IntelligenceAuthorityVerifierV1;
use crate::intelligence_product::FileBackedFreshnessOracleV1;

#[path = "canonical_abstain_inputs.rs"]
mod inputs;
use inputs::bound_digest;
use inputs::configuration_digest;
use inputs::owner_inputs;

const REQUIRED_OWNERS: [&str; 7] = [
    "objective.compiler",
    "utility.ndu",
    "neuron.runtime",
    "prompt.optimizer",
    "intuition.policy",
    "context.compiler",
    "learning.eval",
];
const MAX_STAGE_MICROS: u64 = 10_000_000;
const MIN_STAGE_MICROS: u64 = 1_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalIntelligenceProviderProfileV1 {
    DurableSafeAbstainV1,
}

impl FromStr for CanonicalIntelligenceProviderProfileV1 {
    type Err = AgentdError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "durable-safe-abstain-v1" => Ok(Self::DurableSafeAbstainV1),
            _ => Err(invalid(
                "unsupported canonical intelligence provider profile; expected durable-safe-abstain-v1",
            )),
        }
    }
}

#[derive(Clone)]
pub struct AgentdDurableAbstainInvocationProviderV1 {
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
}

impl AgentdDurableAbstainInvocationProviderV1 {
    pub fn new(
        authority_file: PathBuf,
        authority_verifier: IntelligenceAuthorityVerifierV1,
    ) -> Result<Self, AgentdError> {
        if !authority_file.is_absolute() {
            return Err(AgentdError::Invalid(
                "canonical intelligence authority file must be absolute".to_string(),
            ));
        }
        Ok(Self {
            authority_file,
            authority_verifier,
        })
    }
}

impl AgentdIntelligenceInvocationProviderV1 for AgentdDurableAbstainInvocationProviderV1 {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        build_invocation(
            identity,
            record,
            self.authority_file.clone(),
            self.authority_verifier.clone(),
        )
    }
}

/// Atomically install the runner and the one concrete conservative provider.
/// No partial profile is returned if either side fails construction.
pub fn compose_durable_abstain_intelligence_profile_v1(
    config: AgentdConfig,
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
) -> Result<AgentdConfig, AgentdError> {
    let runner =
        AgentdIntelligenceProductRunnerV1::new(authority_file.clone(), authority_verifier.clone())
            .map_err(|error| {
                AgentdError::Invalid(format!("invalid canonical intelligence runner: {error}"))
            })?;
    let provider =
        AgentdDurableAbstainInvocationProviderV1::new(authority_file, authority_verifier)?;
    config
        .with_intelligence_product_runner(Arc::new(runner))?
        .with_intelligence_invocation_provider(Arc::new(provider))
}

fn build_invocation(
    identity: &AgentdIdentity,
    record: &RunStartRecordV1,
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
    let running_generation = identity
        .spawn_generation
        .checked_add(1)
        .ok_or_else(|| invalid("Agentd generation overflow"))?;
    if record.snapshot.generation != running_generation
        || record.snapshot.fence_digest
            != crate::intelligence_ingress::objective_run_fence_digest_v1(
                identity.agent_id.as_str(),
                identity.spawn_generation,
                running_generation,
            )
        || record.snapshot.run_id.as_str().is_empty()
        || record.snapshot.objective_digest.is_zero()
        || record.snapshot.authority_epoch == 0
        || record.runtime_body_digest.is_zero()
    {
        return Err(invalid(
            "durable RunStart identity is not current for this Agentd",
        ));
    }

    let (owners, frontier) = current_owner_bindings(
        authority_file,
        authority_verifier,
        record.snapshot.authority_epoch,
    )?;
    let configuration_digest = configuration_digest(identity, record, frontier);
    let generation = Generation::new(record.snapshot.generation)
        .map_err(|error| invalid(&format!("RunStart generation: {error}")))?;
    let snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: record.snapshot.objective_digest,
        authority_epoch: record.snapshot.authority_epoch,
        body_generation: generation,
        configuration_digest,
        revocation_frontier_digest: frontier,
        owner_bindings: owners,
    })
    .map_err(|error| invalid(&format!("canonical snapshot: {error}")))?;

    let now_micros = wall_clock_micros()?;
    let budget = budget(record, now_micros)?;
    let candidate_id = id("abstain")?;
    let candidate_support = bound_digest(
        b"hepta.agentd.safe-abstain.candidate.v1\0",
        record,
        snapshot.digest(),
    );
    let legal_candidates = LegalActionCandidateSetRequestV1 {
        candidate_set_id: id("candidate-set.safe-abstain")?,
        state_digest: record.snapshot.objective_digest,
        generator_id: id("intelligence.control")?,
        grammar_digest: bound_digest(
            b"hepta.agentd.safe-abstain.grammar.v1\0",
            record,
            snapshot.digest(),
        ),
        candidates: vec![LegalActionCandidateV1 {
            candidate_id: candidate_id.clone(),
            support_digest: candidate_support,
        }],
        support_floor_ppm: 0,
    };
    let request = CanonicalIntelligenceRunRequestV1 {
        run_id: record.snapshot.run_id.clone(),
        snapshot: snapshot.clone(),
        legal_candidates,
        budget,
    };
    let mut inputs = owner_inputs(
        record,
        &snapshot,
        candidate_id,
        candidate_support,
        now_micros,
    )?;
    inputs.run_identity = Some(crate::AgentdIntelligenceRunIdentityV1::from_run_start(
        identity, record,
    )?);
    Ok(AgentdIntelligenceInvocationV1 { request, inputs })
}

fn current_owner_bindings(
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
    expected_epoch: u64,
) -> Result<(Vec<OwnerBindingV1>, Digest32), AgentdError> {
    let oracle = FileBackedFreshnessOracleV1::new(authority_file, authority_verifier);
    let owner_ids = REQUIRED_OWNERS
        .into_iter()
        .map(id)
        .collect::<Result<Vec<_>, _>>()?;
    let states = oracle
        .current_owners(&owner_ids)
        .map_err(|error| invalid(&format!("current owner snapshot: {error}")))?;
    if states
        .iter()
        .any(|current| current.authority_epoch != expected_epoch)
    {
        return Err(invalid("authority epoch differs from durable RunStart"));
    }
    let frontier = states
        .first()
        .map(|state| state.revocation_frontier_digest)
        .ok_or_else(|| invalid("canonical owner set is empty"))?;
    if frontier.is_zero()
        || states
            .iter()
            .any(|state| state.revocation_frontier_digest != frontier)
    {
        return Err(invalid("canonical owners disagree on revocation frontier"));
    }
    Ok((states.into_iter().map(owner_binding).collect(), frontier))
}

fn owner_binding(state: CurrentOwnerStateV1) -> OwnerBindingV1 {
    OwnerBindingV1 {
        owner_id: state.owner_id,
        generation: state.generation,
        implementation_digest: state.implementation_digest,
        key_digest: state.key_digest,
        key_epoch: state.key_epoch,
    }
}

fn budget(record: &RunStartRecordV1, now_micros: u64) -> Result<CanonicalBudgetV1, AgentdError> {
    let remaining = record
        .admission
        .deadline_unix_micros
        .checked_sub(now_micros)
        .ok_or_else(|| invalid("durable objective deadline has expired"))?;
    let stage = (remaining / 7).min(MAX_STAGE_MICROS);
    if stage < MIN_STAGE_MICROS {
        return Err(invalid(
            "durable objective has insufficient canonical stage budget",
        ));
    }
    let total = stage
        .checked_mul(7)
        .ok_or_else(|| invalid("canonical stage budget overflow"))?;
    Ok(CanonicalBudgetV1 {
        total_micros: total,
        objective_micros: stage,
        utility_micros: stage,
        neural_micros: stage,
        prompt_micros: stage,
        intuition_micros: stage,
        context_micros: stage,
        evaluation_micros: stage,
    })
}

fn wall_clock_micros() -> Result<u64, AgentdError> {
    let micros = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| invalid("system clock precedes Unix epoch"))?
        .as_micros();
    u64::try_from(micros).map_err(|_| invalid("system clock exceeds u64 microseconds"))
}

fn id(value: &str) -> Result<StableId, AgentdError> {
    StableId::new(value).map_err(|error| invalid(&format!("stable id {value}: {error}")))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(message.to_string())
}

#[cfg(test)]
#[path = "canonical_abstain_provider_tests.rs"]
mod tests;
