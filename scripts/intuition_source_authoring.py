#!/usr/bin/env python3
"""Explicit, bounded source authoring on an isolated work branch; removed from the result.
This is never a qualification entrypoint and cannot set acceptance or completion.
"""
from pathlib import Path
import json
import os
import subprocess
R = Path(__file__).resolve().parents[1]
changed = set()
def edit(rel, before, after, count=1):
    path = R / rel
    value = path.read_text(encoding='utf-8')
    if value.count(before) != count:
        raise RuntimeError(f'Authoring precondition failed: {rel}: {before[:90]!r}')
    path.write_text(value.replace(before, after), encoding='utf-8', newline='\n')
    changed.add(rel)
def write(rel, text):
    (R / rel).write_text(text, encoding='utf-8', newline='\n')
    changed.add(rel)

p='codex-rs/hepta-intuition/src/calibrated.rs'
edit(p, '''pub fn decide_calibrated(
    request: CalibratedDecisionRequestV1,
) -> Result<CalibratedIntuitionReceiptV1, CalibratedError> {
    validate_request(&request)?;''', '''pub fn decide_calibrated(
    request: CalibratedDecisionRequestV1,
) -> Result<CalibratedIntuitionReceiptV1, CalibratedError> {
    decide_with_routing(&request, RiskRouting::Request)
}

#[derive(Clone, Copy)]
pub(crate) enum RiskRouting { Request, ProfileSlowPath }

pub(crate) fn decide_with_routing(
    request: &CalibratedDecisionRequestV1,
    routing: RiskRouting,
) -> Result<CalibratedIntuitionReceiptV1, CalibratedError> {
    validate_request(request)?;''')
edit(p,'let disposition = if request.risk_class == RiskClass::High {','let disposition = if request.risk_class == RiskClass::High || matches!(routing, RiskRouting::ProfileSlowPath) {')
edit(p,'        decision_id: request.decision_id,','        decision_id: request.decision_id.clone(),')
edit(p,'    validate_assignment(&request, &eligible)?;','    validate_assignment(request, &eligible)?;')
edit(p,'        select(&request, &eligible)?','        select(request, &eligible)?')
edit(p,'        output_distribution(&request, &disposition)?;','        output_distribution(request, &disposition)?;')
edit(p,'        &request,\n        &disposition,','        request,\n        &disposition,')
edit(p,'    let mut bytes = b"hepta.intuition.calibrated-decision.v1".to_vec();', '''    digest_receipt_with_risk(request, disposition, propensities, abstain_probability, slow_path_probability, request.risk_class)
}

pub(crate) fn digest_receipt_with_risk(
    request: &CalibratedDecisionRequestV1,
    disposition: &CalibratedDispositionV1,
    propensities: &[CalibratedCandidatePropensityV1],
    abstain_probability: ProbabilityQ32,
    slow_path_probability: ProbabilityQ32,
    encoded_risk: RiskClass,
) -> Result<Digest32, CalibratedError> {
    let mut bytes = b"hepta.intuition.calibrated-decision.v1".to_vec();''')
edit(p,'    bytes.push(risk_code(request.risk_class));','    bytes.push(risk_code(encoded_risk));')
edit(p,'pub use binding::decide_calibrated_v2;','pub use binding::decide_calibrated_v2;\npub(crate) use binding::canonical_request_digest_with_risk;')
p='codex-rs/hepta-intuition/src/calibrated_binding.rs'
edit(p,'    if !(1..=MAX_CANDIDATES).contains(&request.candidates.len()) {', '''    canonical_request_digest_with_risk(request, request.risk_class)
}

pub(crate) fn canonical_request_digest_with_risk(
    request: &CalibratedDecisionRequestV1,
    encoded_risk: super::RiskClass,
) -> Result<Digest32, CalibratedError> {
    if !(1..=MAX_CANDIDATES).contains(&request.candidates.len()) {''')
edit(p,'    bytes.push(risk_code(request.risk_class));','    bytes.push(risk_code(encoded_risk));')
edit('codex-rs/hepta-intuition/src/qualified.rs','fn validate_profile_for_request(','pub(crate) fn validate_profile_for_request(')
p='codex-rs/hepta-intuition/src/production.rs'
edit(p,'use crate::qualified::decide_calibrated_v3;','use crate::native::decide_native_profile;')
edit(p,'    let legacy = decide_calibrated_v3(request, profile)?;','    let legacy = decide_native_profile(&request, profile)?;')
edit(p,'''/// Current product decision entrypoint.  It preserves compatibility with the
/// historical receipt kernel while exposing an unambiguous profile-rule reason.''', '''/// Native product routing consumes request risk and profile rule separately.
/// Historical digest bytes are projected without executing legacy decisions.''')
edit('codex-rs/hepta-intuition/src/lib.rs','mod production;', '''mod native;
mod production;
mod coordinates;
pub use coordinates::AssignmentCounter;
pub use coordinates::PolicySequence;
pub use coordinates::PolicyWallClockMillis;''')
p='codex-rs/hepta-agentd/src/intuition_policy.rs'
edit(p,'use codex_hepta_intuition::PolicyGeneration;','use codex_hepta_intuition::PolicyGeneration;\nuse codex_hepta_intuition::PolicySequence;\nuse codex_hepta_intuition::PolicyWallClockMillis;')
edit(p,'    prepared_at: u64,\n    qualification_expires_at: u64,\n    prepared_digest:', '    prepared_at: PolicyWallClockMillis,\n    qualification_expires_at: PolicyWallClockMillis,\n    prepared_digest:')
edit(p,'            prepared_at: now,\n            qualification_expires_at,','            prepared_at: PolicyWallClockMillis::from_raw(now),\n            qualification_expires_at: PolicyWallClockMillis::from_raw(qualification_expires_at),')
edit(p,'        validate_prepared_time(prepared.prepared_at, prepared.qualification_expires_at, now)?;','        validate_prepared_time(prepared.prepared_at.get(), prepared.qualification_expires_at.get(), now)?;')
edit(p,'    bytes.extend_from_slice(&sequence.to_be_bytes());','    bytes.extend_from_slice(&PolicySequence::from_raw(sequence).get().to_be_bytes());')
p='codex-rs/hepta-intelligence/src/intuition_qualification_v3.rs'
edit(p,'use codex_hepta_learning_ledger::verify_independent_roles;','use codex_hepta_learning_ledger::verify_verified_role_separation;')
edit(p,'    verify_independent_roles(evaluator.principal(), observer.principal(), now)?;','    verify_verified_role_separation(&evaluator, &observer, now)?;')
p='codex-rs/hepta-intuition/src/production_tests.rs'
write(p,(R/p).read_text()+'''
#[test]
fn native_v4_preserves_legacy_digests_across_all_risk_rules() {
    for risk in [RiskClass::Low, RiskClass::Elevated, RiskClass::High] {
        for rule in [CanonicalRiskRuleV1::HighOnlySlowPath, CanonicalRiskRuleV1::ElevatedAndHighSlowPath, CanonicalRiskRuleV1::AlwaysSlowPath] {
            for mode in 0..6 {
                let (mut request, mut profile) = fixture(risk, rule);
                match mode {
                    1 => request.candidates[0].hard_veto = true,
                    2 => { request.candidates[0].calibrated_confidence = ProbabilityQ32::ZERO; request.minimum_confidence = ProbabilityQ32::ONE; profile.minimum_confidence = ProbabilityQ32::ONE; }
                    3 => { request.candidates[0].ood_score = ProbabilityQ32::ONE; request.ood.maximum_in_domain_score = ProbabilityQ32::ZERO; profile.maximum_in_domain_score = ProbabilityQ32::ZERO; }
                    4 => request.completeness.omitted_count_bound = 1,
                    5 => request.assignment = AssignmentModeV1::CounterBased { random_stream_digest: d("native-stream"), draw: ProbabilityQ32::ZERO, abstain_probability: ProbabilityQ32::ONE },
                    _ => {}
                }
                request.completeness.candidate_set_digest = canonical_candidate_set_digest_v1(&request.candidates).unwrap();
                let original = request.clone();
                assert_eq!(crate::native::decide_native_profile(&request, &profile), crate::qualified::decide_calibrated_v3(request.clone(), &profile), "risk={risk:?} rule={rule:?} mode={mode}");
                assert_eq!(request, original);
            }
        }
    }
}
''')

# Immutable process configuration: parse before startup, never on first request.
p='codex-rs/hepta-agentd/src/config.rs'
edit(p,'    intuition_policy_host: Option<','    intuition_profile: crate::IntuitionServingProfileV1,\n    intuition_policy_host: Option<')
edit(p,'        let cognitive_retrieval_mode = cognitive_retrieval_mode_from_process_environment()?;','        let intuition_profile = crate::IntuitionServingProfileV1::from_process_environment()?;\n        let cognitive_retrieval_mode = cognitive_retrieval_mode_from_process_environment()?;')
edit(p,'        .map(|config| config.with_cognitive_retrieval_mode(cognitive_retrieval_mode))','        .map(|config| config.with_cognitive_retrieval_mode(cognitive_retrieval_mode))\n        .and_then(|config| config.with_intuition_profile(intuition_profile))')
edit(p,'            intuition_policy_host: None,','            intuition_profile: crate::IntuitionServingProfileV1::Production,\n            intuition_policy_host: None,')
edit(p,'impl AgentdConfig {','''impl AgentdConfig {
    /// Explicit immutable owner configuration; a product binary cannot select Test.
    pub fn with_intuition_profile(mut self, profile: crate::IntuitionServingProfileV1) -> Result<Self, AgentdError> {
        profile.validate_build()?;
        self.intuition_profile = profile;
        Ok(self)
    }
    pub(crate) const fn intuition_profile(&self) -> crate::IntuitionServingProfileV1 { self.intuition_profile }
''')
p='codex-rs/hepta-agentd/src/runtime.rs'
edit(p,'    let intuition_policy_host = config.intuition_policy_host();','    let intuition_profile = config.intuition_profile();\n    let intuition_policy_host = config.intuition_policy_host();')
edit(p,'''    let state = Arc::new(AgentdState::new(
        identity.clone(),
        registry,
        EVENT_CAPACITY,
    )?);''','''    let mut state = AgentdState::new(identity.clone(), registry, EVENT_CAPACITY)?;
    state.intuition_profile = intuition_profile;
    let state = Arc::new(state);''')
p='codex-rs/hepta-agentd/src/state.rs'
edit(p,'pub(crate) struct AgentdState {','pub(crate) struct AgentdState {\n    pub(crate) intuition_profile: crate::IntuitionServingProfileV1,')
edit(p,'        Ok(Self {\n            authbus:','        Ok(Self {\n            intuition_profile: crate::IntuitionServingProfileV1::Production,\n            authbus:')
# Extract the existing method without deleting behavior; maintain the parent module's privacy.
s=(R/p).read_text();start=s.index('    pub(crate) async fn start_canonical_intelligence(')
end=s.index('    /// Revalidate a durable run-start record', start)
method=s[start:end].rstrip()
method=method.replace('        let (Some(runner), Some(provider)) = (','''        self.intuition_profile.require_host(self.intuition_policy.get().is_some_and(|host| host.is_product_ready()))
            .map_err(|code| AgentdError::Invalid(code.to_string()))?;
        let (Some(runner), Some(provider)) = (''',1)
method=method.replace('let _authenticated_intuition =','let authenticated_intuition =',1)
method=method.replace('                episode_id,\n                run_snapshot_digest,','                episode_id.clone(),\n                run_snapshot_digest,',1)
method=method.replace('        match outcome {','        let admitted_result = (|| {\n        match outcome {',1)
method=method.replace('''                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
                    prepared,
                    run_receipt,
                }))''','''                let intuition = authenticated_intuition.clone().map(|policy| {
                    crate::AgentdIntuitionAdmittedReceiptV1::bind_ready(policy, &prepared, &run_receipt)
                }).transpose()?;
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready { prepared, run_receipt, intuition }))''',1)
method=method.replace('Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Abstained))','''Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Abstained {
                    intuition: authenticated_intuition.clone().map(|policy| crate::AgentdIntuitionAdmittedReceiptV1::bind_terminal(policy, episode_id.as_str(), run_snapshot_digest)).transpose()?,
                }))''',1)
method=method.replace('Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::SlowPath))','''Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::SlowPath {
                    intuition: authenticated_intuition.clone().map(|policy| crate::AgentdIntuitionAdmittedReceiptV1::bind_terminal(policy, episode_id.as_str(), run_snapshot_digest)).transpose()?,
                }))''',1)
assert method.endswith('    }')
method=method[:-5]+'''        })();
        admitted_result.map_err(|source| match authenticated_intuition {
            Some(receipt) => crate::AgentdIntuitionServiceErrorV1::AdmissionAfterCommit {
                receipt,
                cause: Box::new(source),
            }.into(),
            None => source,
        })
    }
'''
write('codex-rs/hepta-agentd/src/state_intuition.rs','//! Canonical serving admission; receipt ownership survives every post-commit failure.\nuse super::*;\nimpl AgentdState {\n'+method+'}\n')
write(p,s[:start]+s[end:])
edit(p,'mod control;','mod control;\n#[path = "state_intuition.rs"]\nmod intuition;')
p='codex-rs/hepta-agentd/src/intuition_policy_serving.rs'
s=(R/p).read_text();s=s.replace('use std::sync::OnceLock;\n','')
a=s.index('#[derive(Clone, Copy, Debug, Eq, PartialEq)]\nenum ServingProfile')
b=s.index('#[allow(clippy::too_many_arguments)]',a)
s=s[:a]+'use crate::intuition_profile::IntuitionServingProfileV1 as ServingProfile;\n\n'+s[b:]
a=s.index('    let profile = match serving_profile()');b=s.index('    record_request(profile.as_str());',a)
s=s[:a]+'    let profile = state.intuition_profile;\n'+s[b:]
# Keep a committed token even when post-commit parity or shape validation fails.
a=s.index('        require_outcome_parity(\n            canonical,\n            &committed')
b=s.index('        Ok(Some(committed))',a)
checks=s[a:b]
s=s[:a]+'        let validation: Result<(), AgentdError> = (|| {\n'+checks+'            Ok(())\n        })();\n        validation.map_err(|cause| AgentdError::from(crate::AgentdIntuitionServiceErrorV1::AdmissionAfterCommit { receipt: committed.clone(), cause: Box::new(cause) }))?;\n'+s[b:]
s=s.replace('&[("profile", profile), ("error_class", error_class)],','&[("profile", profile), ("error_class", error_class), ("reason_code", agentd_reason_code(error))],')
s += '''
fn agentd_reason_code(error: &AgentdError) -> &'static str {
    match error { AgentdError::IntuitionPolicy(source) => source.code(), _ => agentd_error_class(error) }
}
'''
write(p,s)
p='codex-rs/hepta-agentd/src/intuition_policy_service.rs'
edit(p,'    GenerationChangedAfterCommit {','''    AdmissionAfterCommit {
        receipt: AgentdIntuitionDecisionReceiptV2,
        cause: Box<AgentdError>,
    },
    GenerationChangedAfterCommit {''')
edit(p,'            Self::NotConfigured =>','            Self::AdmissionAfterCommit { .. } => "agentd.intuition.service.admission_failed_after_commit",\n            Self::NotConfigured =>')
edit(p,'            Self::Agentd(source) => Some(source),','            Self::AdmissionAfterCommit { cause, .. } => Some(cause.as_ref()),\n            Self::Agentd(source) => Some(source),')
p='codex-rs/hepta-agentd/src/intelligence_product.rs'
edit(p,'''        run_receipt: crate::RunReceipt,
    },
    Abstained,
    SlowPath,
}''','''        run_receipt: crate::RunReceipt,
        intuition: Option<crate::AgentdIntuitionAdmittedReceiptV1>,
    },
    Abstained { intuition: Option<crate::AgentdIntuitionAdmittedReceiptV1> },
    SlowPath { intuition: Option<crate::AgentdIntuitionAdmittedReceiptV1> },
}

impl AgentdIntelligenceAdmittedOutcomeV1 {
    #[must_use]
    pub fn intuition(&self) -> Option<&crate::AgentdIntuitionAdmittedReceiptV1> {
        match self { Self::Ready { intuition, .. } | Self::Abstained { intuition } | Self::SlowPath { intuition } => intuition.as_ref() }
    }
}''')
p='codex-rs/hepta-agentd/src/intelligence_product_runner.rs'
edit(p,'''                    prepared,
                    run_receipt,
                })''','''                    prepared,
                    run_receipt,
                    intuition: None,
                })''')
edit(p,'AgentdIntelligenceAdmittedOutcomeV1::Abstained)','AgentdIntelligenceAdmittedOutcomeV1::Abstained { intuition: None })')
edit(p,'AgentdIntelligenceAdmittedOutcomeV1::SlowPath)','AgentdIntelligenceAdmittedOutcomeV1::SlowPath { intuition: None })')
for p in ['codex-rs/hepta-agentd/src/intelligence_product_tests.rs','codex-rs/hepta-agentd/src/intelligence_product_signed_tests.rs']:
    s=(R/p).read_text();a=s.index('let AgentdIntelligenceAdmittedOutcomeV1::Ready {');b=s.index('    } = ',a)
    write(p,s[:b]+'        ..\n'+s[b:])
p='codex-rs/hepta-agentd/src/objective_runtime.rs'
edit(p,'if agentd.canonical_intelligence_enabled() {','if agentd.intuition_profile == crate::IntuitionServingProfileV1::Production || agentd.canonical_intelligence_enabled() {')
edit(p,'        let disposition = match record.disposition {','        let mut intuition = None;\n        let disposition = match record.disposition {')
edit(p,'                match agentd.start_canonical_intelligence(&record).await? {','''                let admitted = agentd.start_canonical_intelligence(&record).await?;
                intuition = admitted.as_ref().and_then(crate::AgentdIntelligenceAdmittedOutcomeV1::intuition).map(crate::AgentdIntuitionAdmittedReceiptV1::wire_receipt);
                match admitted {''')
edit(p,'Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Abstained)','Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Abstained { .. })')
edit(p,'Some(crate::AgentdIntelligenceAdmittedOutcomeV1::SlowPath)','Some(crate::AgentdIntelligenceAdmittedOutcomeV1::SlowPath { .. })')
edit(p,'        Ok(ObjectiveStartResult::Admitted(ObjectiveRunAdmission {','        Ok(ObjectiveStartResult::Admitted(ObjectiveRunAdmission {\n            intuition,')
p='codex-rs/hepta-agent-protocol/src/authbus.rs'
edit(p,'pub struct ObjectiveRunAdmission {','''pub struct ObjectiveRunAdmission {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub intuition: Option<ObjectiveIntuitionAdmissionV1>,''')
write(p,(R/p).read_text()+'''
/// Observational authenticated-policy binding; never a dispatch authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveIntuitionAdmissionV1 {
    pub schema_version: u32,
    pub admission_digest: String,
    pub service_receipt_digest: String,
    pub authentication_digest: String,
    pub production_record_id: Option<String>,
    pub ledger_event_digest: Option<String>,
    pub ledger_chain_digest: Option<String>,
    pub ledger_sequence: Option<u64>,
}
''')
edit('codex-rs/hepta-agent-protocol/src/lib.rs','pub use authbus::ObjectiveRunAdmission;','pub use authbus::ObjectiveRunAdmission;\npub use authbus::ObjectiveIntuitionAdmissionV1;')
edit('codex-rs/hepta-agent-protocol/src/objective_tests.rs','        receipt: ObjectiveRunAdmission {','        receipt: ObjectiveRunAdmission {\n            intuition: None,')
p='codex-rs/hepta-agentd/src/lib.rs'
edit(p,'mod intuition_policy;','''mod intuition_policy;
mod intuition_profile;
mod intuition_admission_receipt;
pub use intuition_profile::IntuitionServingProfileV1;
pub use intuition_admission_receipt::AgentdIntuitionAdmittedReceiptV1;''')

# The operations above are the full authoring scope. Remove all temporary carriers
# in the source commit before it can be inspected or used by qualification.
for rel in ['.github/workflows/intuition-lockfile-authoring-once.yml', '.github/workflows/intuition-toolchain-export.yml']:
    (R/rel).unlink(missing_ok=True)
changed.update(['codex-rs/hepta-intuition/src/native.rs','codex-rs/hepta-intuition/src/coordinates.rs','codex-rs/hepta-agentd/src/intuition_profile.rs','codex-rs/hepta-agentd/src/intuition_admission_receipt.rs'])
Path(os.environ['AUTHORING_FILES']).write_text(json.dumps(sorted(changed)),encoding='utf-8')
print(json.dumps({'sourceFiles':sorted(changed),'acceptance':False},indent=2))
