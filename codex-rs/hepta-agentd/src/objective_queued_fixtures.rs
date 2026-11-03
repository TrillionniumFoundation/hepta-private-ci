//! Independent issuer/evaluator fixtures around the actual seven owner runner.
//! This is not a default runtime configuration or a substitute for production
//! owner loading. Every compiled envelope still crosses the real runner.

use super::*;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

use anyhow::{Context, Result, ensure};
use codex_hepta_intelligence::build_legal_candidates;
use codex_hepta_learning_ledger::{ActivatedLearningTrustV1, RunStartRecordV1};
use codex_hepta_objective::{decode_admission_profile_json_v1, decode_source_envelope_json_v1};

use crate::{AgentdError, AgentdIdentity, AgentdIntelligenceInvocationProviderV1,
    AgentdIntelligenceInvocationV1, AuthBusObjectiveBody, signed_objective_queued_text_item};
use crate::intelligence_product::evaluation_tests::evidence_fixture;

pub(crate) struct CanonicalObjectiveTestOwners {
    pub(crate) calls: AtomicUsize,
    pub(crate) fail_before_prepare: AtomicBool,
    profile: ObjectiveAdmissionProfileV1,
    evaluation_now_ms: u64,
    source_json: String,
    objective_digest: Digest32,
    evaluation_distribution_digest: Digest32,
}

impl CanonicalObjectiveTestOwners {
    pub(crate) fn new(authority_path: &Path) -> Result<(Arc<Self>, Arc<AgentdIntelligenceProductRunnerV1>)> {
        let evaluation_now_ms = wall_clock_ms()?;
        // Activated evaluation trust is scoped to one Objective. Freeze the
        // actual signed-adapter source before installing that trust; a later
        // invocation cannot replace it with trust for a different Objective.
        let source_json = Self::frozen_source_json()?;
        let mut value = fixture();
        value.inputs.objective_envelope = decode_source_envelope_json_v1(source_json.as_bytes())?;
        value.inputs.objective_context = ObjectiveAdmissionContextV1 {
            revision: revision(1), now_unix_micros: evaluation_now_ms.checked_mul(1_000).context("clock overflow")?,
            selected_profile_digest: value.inputs.objective_profile.digest()?,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: id("adapter.console"),
                source_digest: value.inputs.objective_envelope.structured_intent.provenance.source_digest,
            },
        };
        let compiled = admit_and_compile_objective_v1(&value.inputs.objective_envelope,
            &value.inputs.objective_profile, &value.inputs.objective_context)?.compile_result
            .map_err(|conflict| anyhow::anyhow!("fixture Objective compilation conflicted: {conflict:?}"))?;
        let objective_digest = compiled.objective.semantic_digest;
        let snapshot = &value.request.snapshot;
        value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
            objective_digest, authority_epoch: snapshot.authority_epoch(), body_generation: snapshot.body_generation(),
            configuration_digest: snapshot.configuration_digest(), revocation_frontier_digest: snapshot.revocation_frontier_digest(),
            owner_bindings: value.owners.clone(),
        })?;
        value.request.legal_candidates.state_digest = objective_digest;
        value.inputs.context_request.objective_digest = objective_digest;
        value.inputs.evaluation_request.objective_digest = objective_digest;
        let (value, trust) = sign_at(value, evaluation_now_ms)?;
        ensure!(trust.verifier().objective_digest() == objective_digest, "fixture installed another Objective's evaluation trust");
        let evaluation_distribution_digest = trust.distribution_digest();
        write_authority_file(authority_path, &value.owners, value.request.snapshot.revocation_frontier_digest());
        let runner = Arc::new(AgentdIntelligenceProductRunnerV1::new(authority_path.to_path_buf(), authority_verifier())?
            .with_evaluation_trust(trust)?);
        Ok((Arc::new(Self { calls: AtomicUsize::new(0), fail_before_prepare: AtomicBool::new(false), profile: value.inputs.objective_profile,
            evaluation_now_ms, source_json, objective_digest, evaluation_distribution_digest }), runner))
    }

    pub(crate) fn profile_json(&self) -> Result<Vec<u8>> {
        // Owner-local Objective types deliberately do not expose serde. This
        // private fixture writes the existing ProfileWire shape and asks the
        // original bounded decoder to verify the same profile digest.
        let class = |value: &ConstraintClass| match value {
            ConstraintClass::Constitutional => "constitutional",
            ConstraintClass::Principal => "principal",
            ConstraintClass::Environment => "environment",
            ConstraintClass::Task => "task",
        };
        let resource = |value: &ObjectiveResourceAxisProfileV1| serde_json::json!({
            "constraintId":value.constraint_id.to_string(), "axis":value.axis.to_string(),
            "class":class(&value.class), "q32PerSourceUnit":value.q32_per_source_unit.raw(),
            "evidenceSource":value.evidence_source.to_string(),
        });
        let p = &self.profile;
        let constraints = p.constraints.iter().map(|v| serde_json::json!({
            "sourceConstraintId":v.source_constraint_id, "expectedUnit":v.expected_unit,
            "class":class(&v.class), "axis":v.axis.to_string(),
        })).collect::<Vec<_>>();
        let predicates = p.predicates.iter().map(|v| serde_json::json!({
            "sourcePredicateId":v.source_predicate_id, "expectedUnit":v.expected_unit, "axis":v.axis.to_string(),
        })).collect::<Vec<_>>();
        let actions = p.actions.iter().map(|v| serde_json::json!({
            "sourceActionClass":v.source_action_class, "actionId":v.action_id.to_string(),
        })).collect::<Vec<_>>();
        let dimensions = p.soft_dimensions.iter().map(|v| serde_json::json!({
            "sourceDimensionId":v.source_dimension_id, "expectedUnit":v.expected_unit,
            "expectedDirection":match v.expected_direction {
                ObjectiveSoftDirectionV1::Maximize => "maximize", ObjectiveSoftDirectionV1::Minimize => "minimize",
            }, "dimension":v.dimension.to_string(), "baselineWeightQ32":v.baseline_weight.raw(),
        })).collect::<Vec<_>>();
        let requirements = p.evidence_requirements.iter().map(|v| serde_json::json!({
            "sourceRequirementId":v.source_requirement_id, "axis":v.axis.to_string(),
        })).collect::<Vec<_>>();
        let resources = serde_json::json!({
            "timeMicros":resource(&p.resources.time_micros), "tokenCount":resource(&p.resources.token_count),
            "computeMicros":resource(&p.resources.compute_micros), "memoryBytes":resource(&p.resources.memory_bytes),
            "networkBytes":resource(&p.resources.network_bytes), "externalEffectCount":resource(&p.resources.external_effect_count),
        });
        let risk = &p.risk;
        let abstention_rules = risk.abstention_rules.iter().map(|v| serde_json::json!({
            "sourceRule":v.source_rule, "valueQ32":v.value.raw(),
        })).collect::<Vec<_>>();
        let risk_value = serde_json::json!({
            "evidenceSource":risk.evidence_source.to_string(), "class":class(&risk.class),
            "riskConstraintId":risk.risk_constraint_id.to_string(), "riskAxis":risk.risk_axis.to_string(),
            "lowValueQ32":risk.low_value.raw(), "mediumValueQ32":risk.medium_value.raw(),
            "highValueQ32":risk.high_value.raw(), "criticalValueQ32":risk.critical_value.raw(),
            "rollbackConstraintId":risk.rollback_constraint_id.to_string(), "rollbackAxis":risk.rollback_axis.to_string(),
            "rollbackNoneValueQ32":risk.rollback_none_value.raw(), "rollbackReversibleValueQ32":risk.rollback_reversible_value.raw(),
            "rollbackCompensatableValueQ32":risk.rollback_compensatable_value.raw(), "rollbackIrreversibleValueQ32":risk.rollback_irreversible_value.raw(),
            "compensationConstraintId":risk.compensation_constraint_id.to_string(), "compensationAxis":risk.compensation_axis.to_string(),
            "compensationFalseValueQ32":risk.compensation_false_value.raw(), "compensationTrueValueQ32":risk.compensation_true_value.raw(),
            "abstentionConstraintId":risk.abstention_constraint_id.to_string(), "abstentionAxis":risk.abstention_axis.to_string(),
            "abstentionRules":abstention_rules,
        });
        let bytes = serde_json::to_vec(&serde_json::json!({
            "profileId":p.profile_id.to_string(), "profileRevision":p.profile_revision.get(),
            "expectedInputSchemaDigest":p.expected_input_schema_digest.to_string(),
            "expectedNormalizationProfileDigest":p.expected_normalization_profile_digest.to_string(),
            "principalScopeDigest":p.principal_scope_digest.to_string(), "principalScope":p.principal_scope.to_string(),
            "allowedLocales":p.allowed_locales, "maximumSourceAgeMicros":p.maximum_source_age_micros,
            "maximumFutureSkewMicros":p.maximum_future_skew_micros, "deadlineRequired":p.deadline_required,
            "allowedTrustedSourceIdentities":p.allowed_trusted_source_identities.iter().map(ToString::to_string).collect::<Vec<_>>(),
            "constraints":constraints, "predicates":predicates, "actions":actions,
            "softDimensions":dimensions, "evidenceRequirements":requirements,
            "resources":resources, "risk":risk_value,
        }))?;
        ensure!(decode_admission_profile_json_v1(&bytes)?.digest()? == p.digest()?,
            "fixture wire changed the original Objective admission profile");
        Ok(bytes)
    }

    pub(crate) fn source_json(&self) -> Result<String> { Ok(self.source_json.clone()) }

    fn frozen_source_json() -> Result<String> {
        let now = chrono::Utc::now();
        let mut source = objective_envelope();
        // This fixture enters through the signed AuthBus adapter, whose
        // original admission context is AuthorizedAdapter, not Principal.
        source.source_trust_class = ObjectiveSourceTrustV1::AuthorizedAdapter;
        source.observed_at = now.to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
        source.deadline = Some((now + chrono::Duration::minutes(5))
            .to_rfc3339_opts(chrono::SecondsFormat::Millis, true));
        source.intent_digest = canonical_objective_intent_digest_v1(&source)?;
        let predicate = |v: &ObjectiveSourcePredicateV1| serde_json::json!({
            "predicateId":v.predicate_id, "unit":v.unit,
            "comparator":match v.comparator {
                ObjectivePredicateComparatorV1::Equal => "eq",
                ObjectivePredicateComparatorV1::NotEqual => "ne",
                ObjectivePredicateComparatorV1::LessThan => "lt",
                ObjectivePredicateComparatorV1::LessThanOrEqual => "lte",
                ObjectivePredicateComparatorV1::GreaterThan => "gt",
                ObjectivePredicateComparatorV1::GreaterThanOrEqual => "gte",
            },
            "boundQ32":v.bound_q32, "evidenceSourceId":v.evidence_source_id, "terminal":v.terminal,
        });
        let intent = &source.structured_intent;
        let constraints = intent.constraints.iter().map(|v| serde_json::json!({
            "constraintId":v.constraint_id, "unit":v.unit,
            "comparator":match v.comparator {
                ObjectiveConstraintComparatorV1::Equal => "eq",
                ObjectiveConstraintComparatorV1::NotEqual => "ne",
                ObjectiveConstraintComparatorV1::LessThan => "lt",
                ObjectiveConstraintComparatorV1::LessThanOrEqual => "lte",
                ObjectiveConstraintComparatorV1::GreaterThan => "gt",
                ObjectiveConstraintComparatorV1::GreaterThanOrEqual => "gte",
                ObjectiveConstraintComparatorV1::In => "in",
                ObjectiveConstraintComparatorV1::NotInSet => "not_in",
            },
            "boundQ32":v.bound_q32, "evidenceSourceId":v.evidence_source_id, "terminal":v.terminal,
        })).collect::<Vec<_>>();
        let dimensions = intent.soft_dimensions.iter().map(|v| serde_json::json!({
            "dimensionId":v.dimension_id, "unit":v.unit,
            "direction":match v.direction {
                ObjectiveSoftDirectionV1::Maximize => "maximize",
                ObjectiveSoftDirectionV1::Minimize => "minimize",
            },
            "minimumWeightQ32":v.minimum_weight_q32, "maximumWeightQ32":v.maximum_weight_q32,
        })).collect::<Vec<_>>();
        let requirements = intent.evidence_requirements.iter().map(|v| serde_json::json!({
            "requirementId":v.requirement_id, "evidenceSourceId":v.evidence_source_id,
            "minimumConfidencePpm":v.minimum_confidence_ppm, "terminal":v.terminal,
        })).collect::<Vec<_>>();
        let risk = serde_json::json!({
            "riskClass":match intent.risk.risk_class {
                ObjectiveRiskClassV1::Low => "low", ObjectiveRiskClassV1::Medium => "medium",
                ObjectiveRiskClassV1::High => "high", ObjectiveRiskClassV1::Critical => "critical",
            },
            "abstentionRule":intent.risk.abstention_rule,
            "rollbackClass":match intent.risk.rollback_class {
                ObjectiveRollbackClassV1::None => "none", ObjectiveRollbackClassV1::Reversible => "reversible",
                ObjectiveRollbackClassV1::Compensatable => "compensatable", ObjectiveRollbackClassV1::Irreversible => "irreversible",
            },
            "compensationRequired":intent.risk.compensation_required,
        });
        // This is the existing private source DTO wire shape. The original
        // decoder remains responsible for structure, enum and digest parsing.
        let structured = serde_json::json!({
            "successPredicates":intent.success_predicates.iter().map(&predicate).collect::<Vec<_>>(),
            "terminalConditions":intent.terminal_conditions.iter().map(predicate).collect::<Vec<_>>(),
            "legalActionClasses":intent.legal_action_classes, "forbiddenActionClasses":intent.forbidden_action_classes,
            "confirmationActionClasses":intent.confirmation_action_classes,
            "constraints":constraints, "softDimensions":dimensions, "evidenceRequirements":requirements,
            "resources":{
                "timeMicros":intent.resources.time_micros, "tokenCount":intent.resources.token_count,
                "computeMicros":intent.resources.compute_micros, "memoryBytes":intent.resources.memory_bytes,
                "networkBytes":intent.resources.network_bytes, "externalEffectCount":intent.resources.external_effect_count,
            },
            "risk":risk,
            "provenance":{
                "sourceDigest":intent.provenance.source_digest.to_string(),
                "normalizationProfileDigest":intent.provenance.normalization_profile_digest.to_string(),
            },
        });
        let mut wire = serde_json::json!({
            "requestId":source.request_id, "principalScopeDigest":source.principal_scope_digest.to_string(),
            "intentDigest":source.intent_digest.to_string(), "structuredIntent":structured,
            "sourceTrustClass":"authorized_adapter", "locale":source.locale, "observedAt":source.observed_at,
            "inputSchemaDigest":source.input_schema_digest.to_string(),
        });
        if let Some(deadline) = &source.deadline {
            wire["deadline"] = serde_json::Value::String(deadline.clone());
        }
        let json = serde_json::to_string(&wire)?;
        ensure!(decode_source_envelope_json_v1(json.as_bytes())? == source,
            "fixture wire changed the original Objective source envelope");
        Ok(json)
    }

    fn invocation(&self, record: &RunStartRecordV1) -> Result<AgentdIntelligenceInvocationV1> {
        let body: AuthBusObjectiveBody = serde_json::from_slice(record.authenticated_payload.as_deref()
            .context("original authenticated Objective bytes")?)?;
        let mut value = fixture();
        let objective_digest = record.snapshot.objective_digest;
        ensure!(objective_digest == self.objective_digest,
            "fixture invocation differs from its independently installed Objective-scoped evaluation trust");
        let generation = generation(record.snapshot.generation);
        value.request.run_id = record.snapshot.run_id.clone();
        value.request.legal_candidates.state_digest = objective_digest;
        value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
            objective_digest, authority_epoch: record.snapshot.authority_epoch,
            body_generation: generation,
            configuration_digest: value.request.snapshot.configuration_digest(),
            revocation_frontier_digest: value.request.snapshot.revocation_frontier_digest(),
            owner_bindings: value.owners.clone(),
        })?;
        let inputs = &mut value.inputs;
        inputs.objective_envelope = decode_source_envelope_json_v1(body.source_envelope_json.as_bytes())?;
        inputs.objective_profile = self.profile.clone();
        inputs.objective_context = ObjectiveAdmissionContextV1 {
            revision: revision(body.objective_revision), now_unix_micros: wall_clock_ms()?.checked_mul(1_000).context("clock overflow")?,
            selected_profile_digest: record.admission.profile_digest,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: record.authentication.issuer_id.clone(),
                source_digest: inputs.objective_envelope.structured_intent.provenance.source_digest,
            },
        };
        let compiled = admit_and_compile_objective_v1(&inputs.objective_envelope, &inputs.objective_profile,
            &inputs.objective_context)?.compile_result
            .map_err(|conflict| anyhow::anyhow!("original Objective compilation conflicted: {conflict:?}"))?;
        ensure!(compiled.objective.semantic_digest == objective_digest, "fixture changed original Objective semantics");
        inputs.utility_contributions.objective_digest = objective_digest;
        inputs.utility_contributions.generation = generation;
        for contribution in &mut inputs.utility_contributions.contributions {
            contribution.objective_digest = objective_digest;
            contribution.generation = generation;
        }
        let utility = evaluate_candidates_with_policy(inputs.utility_contributions.clone(),
            inputs.utility_profile.clone(), inputs.utility_scalarization.clone(), inputs.utility_policy.clone())?;
        inputs.neural_config.generation = generation;
        inputs.neural_tick.objective_digest = objective_digest;
        inputs.neural_tick.body_digest = record.runtime_body_digest;
        inputs.neural_tick.ndu_digest = utility.evaluation_digest_v2;
        let (_, neural) = sparse_tick(&inputs.neural_config, &inputs.neural_tick, /*previous*/ None)?;
        inputs.prompt_request.objective_digest = objective_digest;
        inputs.prompt_request.registry_snapshot_digest = record.snapshot.prompt_registry_digest;
        for candidate in &mut inputs.prompt_request.candidates {
            candidate.registry_digest = record.snapshot.prompt_registry_digest;
        }
        inputs.intuition_request.decision_id = record.snapshot.run_id.clone();
        inputs.intuition_request.objective_digest = objective_digest;
        inputs.intuition_request.state_digest = neural.checkpoint_after;
        inputs.intuition_request.policy_generation = record.snapshot.generation;
        inputs.intuition_request.calibration.generation = record.snapshot.generation;
        inputs.intuition_request.ood.generation = record.snapshot.generation;
        inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
        inputs.context_request.objective_digest = objective_digest;
        inputs.context_request.items = vec![signed_objective_queued_text_item(record, /*token_count*/ 8)?];
        inputs.context_request.token_budget = 16;
        inputs.evaluation_request.objective_digest = objective_digest;
        let (value, trust) = sign_at(value, self.evaluation_now_ms)?;
        ensure!(trust.distribution_digest() == self.evaluation_distribution_digest,
            "fixture request evidence differs from the host's already activated evaluation trust");
        Ok(AgentdIntelligenceInvocationV1 { request: value.request, inputs: value.inputs })
    }
}

impl AgentdIntelligenceInvocationProviderV1 for CanonicalObjectiveTestOwners {
    fn build(&self, _identity: &AgentdIdentity, record: &RunStartRecordV1)
        -> std::result::Result<AgentdIntelligenceInvocationV1, AgentdError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if self.fail_before_prepare.load(Ordering::SeqCst) {
            return Err(AgentdError::Invalid("fixture stopped before original canonical preparation".to_owned()));
        }
        self.invocation(record).map_err(|error| AgentdError::Invalid(format!("canonical Objective fixture: {error:#}")))
    }
}

fn sign_at(mut value: Fixture, now_ms: u64) -> Result<(Fixture, ActivatedLearningTrustV1)> {
    let key = SigningKey::from_bytes(&[47; 32]);
    for owner in &mut value.owners {
        if owner.owner_id.as_str() == "learning.eval" {
            owner.key_digest = Digest32::of_bytes(&key.verifying_key().to_bytes());
        }
    }
    let snapshot = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: snapshot.objective_digest(), authority_epoch: snapshot.authority_epoch(),
        body_generation: snapshot.body_generation(), configuration_digest: snapshot.configuration_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(), owner_bindings: value.owners.clone(),
    })?;
    value.inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
    let context = compile(value.inputs.context_request.clone())?;
    let legal = build_legal_candidates(value.request.legal_candidates.clone())?;
    let binding = AgentdEvaluationBindingV1 {
        run_id: value.request.run_id.clone(), objective_digest: value.request.snapshot.objective_digest(),
        snapshot_digest: value.request.snapshot.digest(), context_receipt_digest: context.context_digest,
        candidate_set_digest: legal.candidate_set_digest, selected_candidate_id: id("action.read"),
    };
    let (trust, signed) = evidence_fixture(&binding, now_ms);
    value.inputs.signed_evaluation = Some(signed);
    Ok((value, trust))
}
