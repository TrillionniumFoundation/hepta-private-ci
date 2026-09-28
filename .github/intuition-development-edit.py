"""Isolated source-authoring recipe; never run by qualification or production."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
recipe = Path(__file__).resolve().parents[1]
expected = "301cc06cbc80fe339f8f3055db5315d53acfc177"
assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip() == expected
changed: set[str] = set()


def replace(name: str, old: str, new: str) -> None:
    path = root / name
    content = path.read_text(encoding="utf-8")
    if content.count(old) != 1:
        raise ValueError(f"source precondition failed: {name}: {old[:100]!r}")
    path.write_text(content.replace(old, new, 1), encoding="utf-8", newline="\n")
    changed.add(name)


def append(name: str, content: str) -> None:
    path = root / name
    path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n" + content.lstrip(), encoding="utf-8", newline="\n")
    changed.add(name)


copied = (
    "codex-rs/hepta-intuition/src/production_native.rs",
    "scripts/intuition_state.py",
    "scripts/tests/test_intuition_state.py",
    "docs/modules/intuition.policy/CURRENT_STATE.json",
)
for name in copied:
    target = root / name
    assert not target.exists(), name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(recipe / name, target)
    changed.add(name)

calibrated = "codex-rs/hepta-intuition/src/calibrated.rs"
replace(calibrated, "pub use binding::canonical_calibrated_request_digest_v1;", "pub use binding::canonical_calibrated_request_digest_v1;\npub(crate) use binding::canonical_request_digest_with_risk;")
replace(calibrated, """pub fn decide_calibrated(
    request: CalibratedDecisionRequestV1,
) -> Result<CalibratedIntuitionReceiptV1, CalibratedError> {
    validate_request(&request)?;""", """pub fn decide_calibrated(
    request: CalibratedDecisionRequestV1,
) -> Result<CalibratedIntuitionReceiptV1, CalibratedError> {
    decide_calibrated_with_routing(request, KernelRiskRouting::RequestRisk)
}

/// Internal routing input, not a wire risk classification or authority grant.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum KernelRiskRouting {
    RequestRisk,
    ProfileSlowPath,
}

pub(crate) fn decide_calibrated_with_routing(
    request: CalibratedDecisionRequestV1,
    routing: KernelRiskRouting,
) -> Result<CalibratedIntuitionReceiptV1, CalibratedError> {
    validate_request(&request)?;""")
replace(calibrated, "let disposition = if request.risk_class == RiskClass::High {", "let disposition = if request.risk_class == RiskClass::High\n        || routing == KernelRiskRouting::ProfileSlowPath\n    {")
replace(calibrated, """    let mut bytes = b"hepta.intuition.calibrated-decision.v1".to_vec();""", """    digest_receipt_with_risk(
        request, disposition, propensities, abstain_probability,
        slow_path_probability, request.risk_class,
    )
}

/// Read-only historical digest view; never used to choose an action.
pub(crate) fn digest_receipt_with_risk(
    request: &CalibratedDecisionRequestV1,
    disposition: &CalibratedDispositionV1,
    propensities: &[CalibratedCandidatePropensityV1],
    abstain_probability: ProbabilityQ32,
    slow_path_probability: ProbabilityQ32,
    encoded_risk: RiskClass,
) -> Result<Digest32, CalibratedError> {
    let mut bytes = b"hepta.intuition.calibrated-decision.v1".to_vec();""")
replace(calibrated, "bytes.push(risk_code(request.risk_class));", "bytes.push(risk_code(encoded_risk));")

binding = "codex-rs/hepta-intuition/src/calibrated_binding.rs"
replace(binding, """pub fn canonical_calibrated_request_digest_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, CalibratedError> {
    if !(1..=MAX_CANDIDATES)""", """pub fn canonical_calibrated_request_digest_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, CalibratedError> {
    canonical_request_digest_with_risk(request, request.risk_class)
}

/// Historical serialized risk is an encoding view, never a mutable request.
pub(crate) fn canonical_request_digest_with_risk(
    request: &CalibratedDecisionRequestV1,
    encoded_risk: RiskClass,
) -> Result<Digest32, CalibratedError> {
    if !(1..=MAX_CANDIDATES)""")
replace(binding, "bytes.push(risk_code(request.risk_class));", "bytes.push(risk_code(encoded_risk));")
replace("codex-rs/hepta-intuition/src/qualified.rs", "fn validate_profile_for_request(", "pub(crate) fn validate_profile_for_request(")
production = "codex-rs/hepta-intuition/src/production.rs"
replace(production, "use crate::qualified::decide_calibrated_v3;", '#[path = "production_native.rs"]\nmod native;\nuse native::native_profile_decision;')
replace(production, "let legacy = decide_calibrated_v3(request, profile)?;", "let legacy = native_profile_decision(request, profile)?;")
replace(production, "/// historical receipt kernel while exposing an unambiguous profile-rule reason.", "/// historical receipt encoding while routing natively with an explicit profile rule.")

append("codex-rs/hepta-intuition/src/production_tests.rs", r'''
#[test]
fn native_v4_preserves_historical_receipts_across_risk_mask_and_assignment_matrix() {
    for risk in [RiskClass::Low, RiskClass::Elevated, RiskClass::High] {
        for rule in [
            CanonicalRiskRuleV1::HighOnlySlowPath,
            CanonicalRiskRuleV1::ElevatedAndHighSlowPath,
            CanonicalRiskRuleV1::AlwaysSlowPath,
        ] {
            for mask in 0..4 {
                for randomized in [false, true] {
                    let (mut request, mut profile) = fixture(risk, rule);
                    if mask == 1 {
                        request.candidates[0].hard_veto = true;
                    } else if mask == 2 {
                        request.minimum_confidence = ProbabilityQ32::ONE;
                        profile.minimum_confidence = ProbabilityQ32::ONE;
                        request.candidates[0].calibrated_confidence = ProbabilityQ32::ZERO;
                    } else if mask == 3 {
                        request.ood.maximum_in_domain_score = ProbabilityQ32::ZERO;
                        profile.maximum_in_domain_score = ProbabilityQ32::ZERO;
                        request.candidates[0].ood_score = ProbabilityQ32::ONE;
                    }
                    if randomized {
                        let eligible = mask == 0;
                        request.candidates[0].assignment_probability = if eligible {
                            ProbabilityQ32::ONE
                        } else {
                            ProbabilityQ32::ZERO
                        };
                        request.assignment = AssignmentModeV1::CounterBased {
                            random_stream_digest: d("native-matrix-stream"),
                            draw: ProbabilityQ32::ZERO,
                            abstain_probability: if eligible {
                                ProbabilityQ32::ZERO
                            } else {
                                ProbabilityQ32::ONE
                            },
                        };
                    }
                    request.completeness.candidate_set_digest =
                        canonical_candidate_set_digest_v1(&request.candidates).expect("set");
                    let before = canonical_calibrated_request_digest_v1(&request).expect("request");
                    let old = crate::qualified::decide_calibrated_v3(request.clone(), &profile)
                        .expect("historical oracle");
                    let native = native::native_profile_decision(request.clone(), &profile)
                        .expect("native routing");
                    assert_eq!(native, old, "risk={risk:?} rule={rule:?} mask={mask} randomized={randomized}");
                    let product = decide_calibrated_v4(request.clone(), &profile).expect("V4");
                    assert_eq!(product.legacy_receipt_digest, old.receipt_digest);
                    assert_eq!(product.original_risk_class, risk);
                    assert_eq!(product.propensities, old.propensities);
                    assert_eq!(product.abstain_probability, old.abstain_probability);
                    assert_eq!(product.slow_path_probability, old.slow_path_probability);
                    assert_eq!(canonical_calibrated_request_digest_v1(&request).expect("unchanged"), before);
                }
            }
        }
    }
}
''')

qualification = "codex-rs/hepta-intelligence/src/intuition_qualification_v3.rs"
replace(qualification, "use codex_hepta_learning_ledger::verify_independent_roles;", "use codex_hepta_learning_ledger::verify_verified_role_separation;")
replace(qualification, "verify_independent_roles(evaluator.principal(), observer.principal(), now)?;", "// Distinct principal keys do not establish independent controllers.\n    verify_verified_role_separation(&evaluator, &observer, now)?;")

product_tests = "codex-rs/hepta-agentd/tests/intuition_policy_product_v3.rs"
replace(product_tests, """fn trust_material() -> (
    ActivatedLearningTrustV1,
    Arc<LearningEvidenceVerifierV1>,
    [SigningKey; 3],
    [AuthenticatedPrincipalV1; 3],
) {
    let keys""", """fn trust_material() -> (
    ActivatedLearningTrustV1,
    Arc<LearningEvidenceVerifierV1>,
    [SigningKey; 3],
    [AuthenticatedPrincipalV1; 3],
) {
    trust_material_with_observer_controller("controller:observer")
}

fn trust_material_with_observer_controller(observer_controller: &str) -> (
    ActivatedLearningTrustV1,
    Arc<LearningEvidenceVerifierV1>,
    [SigningKey; 3],
    [AuthenticatedPrincipalV1; 3],
) {
    let keys""")
replace(product_tests, '                "controller:observer",\n                &keys[2],', '                observer_controller,\n                &keys[2],')
append(product_tests, r'''
#[test]
fn v3_product_rejects_evaluator_observer_controller_collision_despite_distinct_keys() {
    let (_, verifier, keys, principals) =
        trust_material_with_observer_controller("controller:evaluator");
    let (request, profile) = request_and_profile();
    let (scoring, assignment) = commitments(&request, &profile);
    let completeness = sign_evidence(
        &verifier, &principals[0], &keys[0], LearningEvidenceRoleV1::Generator,
        "completeness:controller-collision",
        &canonical_completeness_evidence_payload_v1(&request).expect("completeness"),
    );
    let qualification = sign_evidence(
        &verifier, &principals[1], &keys[1], LearningEvidenceRoleV1::Evaluator,
        "qualification:controller-collision",
        &canonical_profile_qualification_payload_v1(&profile).expect("profile"),
    );
    let runtime = sign_evidence(
        &verifier, &principals[2], &keys[2], LearningEvidenceRoleV1::Observer,
        "runtime:controller-collision",
        &canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
            .expect("runtime"),
    );
    let error = codex_hepta_intelligence::decide_authenticated_intuition_v3(
        request, profile, scoring, assignment,
        IntuitionQualificationEvidenceV2 {
            completeness: &completeness,
            profile_qualification: &qualification,
            runtime: &runtime,
        },
        &verifier, NOW,
    ).expect_err("same controller must not self-qualify independent runtime evidence");
    assert!(matches!(error,
        codex_hepta_intelligence::IntuitionQualificationErrorV3::Evidence(
            codex_hepta_learning_ledger::SignedEvidenceError::ControllerCollision
        )
    ));
}
''')

# Correct stale factual descriptions without discarding the detailed design.
operations = "docs/modules/intuition.policy/OPERATIONS.md"
replace(operations, "The canonical Agentd gate reads `HEPTA_INTUITION_PROFILE` once per process.", "AgentdState resolves `HEPTA_INTUITION_PROFILE` at startup and binds the immutable typed profile into configuration identity.")
replace(operations, "The profile cannot be changed through environment mutation after first use; restart into a new configured process generation instead.", "Requests do not re-read the environment or a global cache; restart into a new configured process generation to change the profile.")
dossier = "qualification/module-execution-dossiers/detail/intuition.policy.md"
replace(dossier, "The canonical gate reads `HEPTA_INTUITION_PROFILE` once per process.", "AgentdState resolves `HEPTA_INTUITION_PROFILE` at startup and binds its typed value into configuration identity.")
replace(dossier, "V4 currently wraps the qualified legacy kernel; preserving the product receipt semantics must not be confused with removing every internal legacy risk transformation.", "V4 invokes the shared deterministic kernel with explicit risk routing and the unchanged original request. A read-only historical encoding view preserves existing V1/V2/V3 digest fields without using a rewritten risk value to choose an action. Legacy entry points remain for compatibility callers.")
replace(dossier, "End-to-end recovery must preserve this typed information through the outer serving error boundary as well.", "The canonical run/context boundary now retains the complete policy receipt and typed downstream cause in process. Durable restart reconciliation and outward transport of that receipt remain separate unclosed requirements.")
replace(dossier, "| Canonical ObjectiveStart hook materialized and compile-reachable | requires actual source/build evidence, not a pending script |", "| Canonical ObjectiveStart hook and bound receipt | directly committed source; compile and real-process evidence still required |")
replace(dossier, "The actual hook, exact-head and synthetic-merge execution, real process E2E and independent acceptance are separate facts.", "The actual hook and in-process receipt binding are directly committed source. Exact-head and synthetic-merge execution, real process E2E and independent acceptance remain separate facts.")

mapping_name = "docs/modules/intuition.policy/IMPLEMENTATION_MAP.json"
mapping_path = root / mapping_name
mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
assert all(value is False for value in mapping["full_completion_predicate"].values())
mapping["servingProfile"]["configurationPinnedOnFirstUse"] = False
mapping["servingProfile"]["configurationParsedAtStartup"] = True
mapping["servingProfile"]["configurationIncludedInRuntimeIdentity"] = True
mapping["productCallerState"] = "canonical_hook_and_in_process_receipt_bound_execution_unverified"
mapping_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8", newline="\n")
changed.add(mapping_name)

# This supplementary ARM job does not replace any required x86 source/merge
# qualification, change their runner identity, or reinterpret their artifacts.
replace(".github/workflows/intuition-source-regressions.yml", "runs-on: macos-15", "runs-on: ubuntu-24.04-arm")
replace(".github/workflows/intuition-source-regressions.yml", "name: POSIX source regression preflight", "name: Linux ARM source regression preflight")

subprocess.run([sys.executable, "scripts/intuition_state.py", "--write"], cwd=root, check=True)
changed.update({"docs/modules/intuition.policy/TECHNICAL.md", operations,
                "docs/modules/intuition.policy/CI_EVIDENCE.md", dossier,
                mapping_name, "docs/modules/intuition.policy/CONTRACTS.md"})
subprocess.run(["git", "add", "--intent-to-add", "--", *copied,
                "docs/modules/intuition.policy/CONTRACTS.md"], cwd=root, check=True)
actual = {x.decode() for x in subprocess.check_output(["git", "diff", "--name-only", "-z"], cwd=root).split(b"\0") if x}
assert actual <= changed, actual - changed
(root.parent / "author-allowed.json").write_text(json.dumps(sorted(changed)), encoding="utf-8")
print("Authored scoped native routing, verified-controller separation and document projections.")
