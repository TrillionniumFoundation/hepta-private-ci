//! One ordinary upgrade step composed from the existing durable owners.
//!
//! TaskFlow owns dispatch/reconciliation and FinalUse; the artifact owner owns
//! publication/CURRENT; the independent selector owns candidate admission; and
//! Supervisord owns the signed release transaction. This coordinator has no
//! journal, issuer key, mutable ranker slot, or authority-bearing receipt.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::ProductionMutationState;
use codex_hepta_supervisor::ProductionMutationStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordAgentStatus;
use serde::Serialize;

use crate::AgentdClient;
use crate::AutomationEffectChainObservation;
use crate::AutomationEffectObservation;
use crate::AutomationEffectReconcileSnapshot;
use crate::AutomationEffectReconcileState;
use crate::CognitiveModelReadback;
use crate::cognitive_upgrade_materials::inspect_model;
use crate::cognitive_materials_io::read_material;
use crate::cognitive_upgrade_plan::PublishedCognitiveUpgradePlanV1;

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum CognitiveUpgradeProgressV1 {
    AwaitingChain {
        observation: AutomationEffectReconcileSnapshot,
    },
    Installing {
        production: Option<ProductionMutationState>,
        chain: Option<AutomationEffectChainObservation>,
        owner: SupervisordAgentStatus,
    },
    Installed {
        model: CognitiveModelReadback,
        chain: AutomationEffectChainObservation,
        production: ProductionMutationState,
    },
    Blocked {
        reason: String,
        production: Option<ProductionMutationState>,
        chain: Option<AutomationEffectChainObservation>,
    },
}

/// Perform a bounded step against the real local sockets. Exact retries derive
/// their progress from the original TaskFlow and signed Supervisor journals.
/// Reorgs, unavailable data or revoked CURRENT never authorize another upgrade
/// or an automatic rollback. A rollback still requires its own existing grants.
pub async fn advance_published_cognitive_upgrade_v1(
    fleet: &FleetRegistry,
    plan: &PublishedCognitiveUpgradePlanV1,
) -> Result<CognitiveUpgradeProgressV1> {
    let commitment = &plan.commitment;
    let source = &commitment.source;
    let output = commitment.output_sha256()?;
    let grant = &plan.production_grant;
    ensure!(
        grant.agent_id == source.agent_id.as_str()
            && grant.source_release == source.source_release.as_str()
            && grant.target_release == source.target_release.as_str()
            && grant.transition == H7H89ProductionTransition::Upgrade
            && plan.effect.intent.subject_id == source.agent_id.as_str(),
        "upgrade owner/release/effect binding mismatch"
    );
    plan.effect.intent.digest()?;
    ensure!(
        inspect_model(fleet, source)? == commitment.installed,
        "original selected model no longer matches the committed upgrade"
    );
    let supervisor = SupervisordClient::new(fleet.layout().supervisor_socket().to_path_buf())?;
    let production = supervisor.production_mutation_status(source.agent_id.clone()).await?;
    let same_operation = production.as_ref().is_some_and(|state| {
        state.receipt.grant_sha256 == grant.grant_sha256
            && state.receipt.agent_id == source.agent_id.as_str()
            && state.receipt.source_release == source.source_release.as_str()
            && state.receipt.target_release == source.target_release.as_str()
            && state.receipt.transition == H7H89ProductionTransition::Upgrade
    });
    if let Some(state) = &production {
        let blocked = match state.receipt.status {
            ProductionMutationStatus::Queued => !same_operation,
            ProductionMutationStatus::RecoveryRequired => true,
            ProductionMutationStatus::Aborted | ProductionMutationStatus::RolledBack => same_operation,
            ProductionMutationStatus::Committed => false,
        };
        if blocked || !state.unknown_effects.is_empty() {
            return Ok(CognitiveUpgradeProgressV1::Blocked {
                reason: "the existing signed release owner requires recovery or another operation".to_owned(),
                production,
                chain: None,
            });
        }
    }
    let status = supervisor.snapshot(source.agent_id.clone()).await?;
    if status.lifecycle != AgentLifecycle::Running || !status.active || !status.healthy {
        ensure!(same_operation, "source Agentd is not ready for an upgrade");
        return Ok(CognitiveUpgradeProgressV1::Installing { production, chain: None, owner: status });
    }
    let generation = status.spawn_generation.context("active Agentd has no launch generation")?;
    let client = AgentdClient::new(
        fleet.layout().agent(&source.agent_id).agentd_control_socket().to_path_buf(),
        source.agent_id.clone(),
        generation,
    )?;

    let observation = if !same_operation {
        ensure!(
            status.current_release.as_ref() == Some(&source.source_release)
                && !status.release_change_pending
                && generation < source.spawn_generation,
            "source release or launch fence changed"
        );
        let current = client.cognitive_model_status().await?.installed
            .context("upgrade requires a readback of the independently evaluated predecessor")?;
        ensure!(
            Some(&current.model) == commitment.installed.evaluated_predecessor.as_ref(),
            "running predecessor differs from independent selection"
        );
        let packet = read_material(&plan.effect.packet_path, crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES as u64)?;
        ensure!(Sha256Digest::for_bytes(&packet) == plan.effect.intent.payload_digest,
            "task accept packet differs from the original FinalUse effect");
        // The original owner prepares only before its durable dispatch barrier;
        // exact uncertain attempts enter recovery without a second submission.
        client.automation_resume_effect(
            plan.effect.intent.clone(),
            &packet,
            plan.effect.final_use_grant.clone(),
            plan.effect.command_id.clone(),
        ).await?
    } else {
        client.automation_observe_effect(plan.effect.intent.clone(), plan.effect.command_id.clone()).await?
    };
    let accepted = accepted_task_chain(&observation, plan, &output)?;
    let Some(chain) = accepted else {
        return Ok(if same_operation {
            CognitiveUpgradeProgressV1::Blocked {
                reason: "the exact accepted task is unavailable, reorganized, or below the original confirmation policy".to_owned(),
                production,
                chain: observation.chain,
            }
        } else {
            CognitiveUpgradeProgressV1::AwaitingChain { observation }
        });
    };

    if same_operation {
        let production = production.context("signed operation disappeared")?;
        if production.receipt.status != ProductionMutationStatus::Committed
            || status.release_change_pending
        {
            return Ok(CognitiveUpgradeProgressV1::Installing { production: Some(production), chain: Some(chain), owner: status });
        }
        ensure!(status.current_release.as_ref() == Some(&source.target_release)
            && generation == source.spawn_generation, "installed release/launch differs from committed target");
        let model = client.cognitive_model_status().await?.installed.context("target has no learned ranker")?;
        ensure!(model == commitment.installed, "actual installed ranker differs from the selected target");
        // Reobserve Chain after the actual model readback. Neither observation
        // grants future freshness or bypasses the next real FinalUse boundary.
        let after = client.automation_observe_effect(
            plan.effect.intent.clone(), plan.effect.command_id.clone(),
        ).await?;
        let Some(chain) = accepted_task_chain(&after, plan, &output)? else {
            return Ok(CognitiveUpgradeProgressV1::Blocked {
                reason: "task confirmation changed during installed-model readback".to_owned(),
                production: Some(production), chain: after.chain,
            });
        };
        return Ok(CognitiveUpgradeProgressV1::Installed { model, chain, production });
    }

    // Fresh owner/selector revalidation immediately before the original signed
    // lifecycle mutation. Chain settlement is only a prerequisite, never its authority.
    ensure!(inspect_model(fleet, source)? == commitment.installed,
        "candidate withdrew or changed before signed installation");
    let accepted = supervisor.signed_upgrade(
        status.control_fence, grant.clone(), plan.h7_envelope.clone(),
    ).await?;
    ensure!(accepted.production_receipt.as_ref().is_some_and(|receipt| receipt.grant_sha256 == grant.grant_sha256),
        "supervisor did not return the exact signed admission");
    Ok(CognitiveUpgradeProgressV1::Installing {
        production: supervisor.production_mutation_status(source.agent_id.clone()).await?,
        chain: Some(chain),
        owner: supervisor.snapshot(source.agent_id.clone()).await?,
    })
}

fn accepted_task_chain(
    observation: &AutomationEffectReconcileSnapshot,
    plan: &PublishedCognitiveUpgradePlanV1,
    output: &Sha256Digest,
) -> Result<Option<AutomationEffectChainObservation>> {
    let intent = &plan.effect.intent;
    if observation.state != AutomationEffectReconcileState::Terminal
        || !observation.effect.as_ref().is_some_and(|effect| {
            effect.run_id == intent.run_id && effect.step_id == intent.step_id
                && effect.attempt == intent.attempt && effect.observation == AutomationEffectObservation::Succeeded
                && effect.receipt_digest.is_some()
        })
    {
        return Ok(None);
    }
    let Some(chain) = &observation.chain else { return Ok(None); };
    ensure!(chain.provider_effect_key.as_deref() == Some(plan.effect.provider_effect_key.as_str())
        && chain.payload_sha256.as_deref() == Some(intent.payload_digest.as_str()),
        "chain observation is not bound to this exact durable task effect");
    let task_matches = chain.accepted_task.as_ref().is_some_and(|task| {
        task.schema_version == 1 && task.accepted_in_exact_packet && task.current_status == "settled"
            && task.task_id == plan.task.task_id.as_str() && task.owner == plan.task.owner.as_str()
            && task.provider == plan.task.provider.as_str() && task.output_sha256 == output.as_str()
    });
    Ok((chain.stored_exact && chain.active_chain_member && chain.confirmation_policy_satisfied
        && chain.local_target_only && !chain.global_absence_authority && !chain.confirmation_authority
        && !chain.finality_authority && !chain.execution_authority && task_matches).then(|| chain.clone()))
}
