#!/usr/bin/env python3
import json
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one replacement in {path}, found {count}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    """        CanonicalPortDecisionV1::Selected {
            candidate_id,
            propensity,
        } => AdvisoryDecisionV1::Selected {
            candidate_id: candidate_id.clone(),
            propensity: *propensity,
        },
""",
    """        CanonicalPortDecisionV1::Selected {
            candidate_id,
            propensity,
        } => {
            if propensity.raw() == 0 {
                return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                    "selected propensity",
                ));
            }
            AdvisoryDecisionV1::Selected {
                candidate_id: candidate_id.clone(),
                propensity: *propensity,
            }
        }
""",
)

replace_once(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    """pub fn assemble_context(
    decision: &AdvisoryDecisionReceiptV1,
""",
    """fn require_legal_selection(
    legal: &LegalActionCandidateSetV1,
    intuition: &CanonicalPortReceiptV1,
) -> Result<(), CanonicalIntelligenceError> {
    if let CanonicalPortDecisionV1::Selected { candidate_id, .. } = &intuition.decision
        && !legal
            .candidates
            .iter()
            .any(|candidate| candidate.candidate_id == *candidate_id)
    {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "selected candidate",
        ));
    }
    Ok(())
}

pub fn assemble_context(
    decision: &AdvisoryDecisionReceiptV1,
""",
)

replace_once(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    """    let intuition = stage!(
        CanonicalStageV1::IntuitionDecided,
        |ports: &mut P, input| ports.decide_intuition(input)
    );
    let decision = decide_boundary(&request.run_id, legal.candidate_set_digest, &intuition)?;
""",
    """    let intuition = stage!(
        CanonicalStageV1::IntuitionDecided,
        |ports: &mut P, input| ports.decide_intuition(input)
    );
    require_legal_selection(&legal, &intuition)?;
    let decision = decide_boundary(&request.run_id, legal.candidate_set_digest, &intuition)?;
""",
)

replace_once(
    "codex-rs/hepta-intelligence/src/canonical_tests.rs",
    """struct Ports {
    calls: Vec<CanonicalStageV1>,
    abstain: bool,
    wrong_owner: Option<CanonicalStageV1>,
}
""",
    """struct Ports {
    calls: Vec<CanonicalStageV1>,
    abstain: bool,
    wrong_owner: Option<CanonicalStageV1>,
    selected_candidate: StableId,
    selected_propensity: ProbabilityQ32,
}
""",
)

replace_once(
    "codex-rs/hepta-intelligence/src/canonical_tests.rs",
    """        Self {
            calls: Vec::new(),
            abstain: false,
            wrong_owner: None,
        }
""",
    """        Self {
            calls: Vec::new(),
            abstain: false,
            wrong_owner: None,
            selected_candidate: id("action:one"),
            selected_propensity: ProbabilityQ32::ONE,
        }
""",
)

replace_once(
    "codex-rs/hepta-intelligence/src/canonical_tests.rs",
    """            CanonicalPortDecisionV1::Selected {
                candidate_id: id("action:one"),
                propensity: ProbabilityQ32::ONE,
            }
""",
    """            CanonicalPortDecisionV1::Selected {
                candidate_id: self.selected_candidate.clone(),
                propensity: self.selected_propensity,
            }
""",
)

path = Path("codex-rs/hepta-intelligence/src/canonical_tests.rs")
text = path.read_text()
if "fn selected_candidate_must_belong_to_the_frozen_legal_set()" not in text:
    text = text.rstrip() + r'''


#[test]
fn selected_candidate_must_belong_to_the_frozen_legal_set() {
    let request = request();
    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = Ports::new();
    ports.selected_candidate = id("action:outside-legal-set");

    assert_eq!(
        prepare_intelligence_run(request, &mut ports, &mut oracle)
            .expect_err("out-of-set selection must fail closed"),
        CanonicalIntelligenceError::InvalidCandidateSet("selected candidate")
    );
    assert_eq!(
        ports.calls,
        vec![
            CanonicalStageV1::ObjectiveValidated,
            CanonicalStageV1::UtilityEvaluated,
            CanonicalStageV1::NeuralSignalCollected,
            CanonicalStageV1::PromptPortfolioBuilt,
            CanonicalStageV1::IntuitionDecided,
        ]
    );
}

#[test]
fn selected_candidate_requires_positive_propensity() {
    let request = request();
    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = Ports::new();
    ports.selected_propensity = ProbabilityQ32::ZERO;

    assert_eq!(
        prepare_intelligence_run(request, &mut ports, &mut oracle)
            .expect_err("zero propensity must fail closed"),
        CanonicalIntelligenceError::InvalidCandidateSet("selected propensity")
    );
}
'''
    path.write_text(text + "\n")

replace_once(
    "docs/modules/intelligence.control/TECHNICAL.md",
    """- [codex-rs/hepta-intelligence/src/canonical_tests.rs](../../../codex-rs/hepta-intelligence/src/canonical_tests.rs): first-class NDU/seven-owner order, abstention, post-call generation drift, key rotation, wrong-owner receipt and candidate closure.
""",
    """- [codex-rs/hepta-intelligence/src/canonical_tests.rs](../../../codex-rs/hepta-intelligence/src/canonical_tests.rs): first-class NDU/seven-owner order, abstention, post-call generation drift, key rotation, wrong-owner receipt, duplicate rejection, legal-set membership and positive selected propensity.
""",
)

replace_once(
    "docs/modules/intelligence.control/TECHNICAL.md",
    """In `codex-rs`, run `just test -p codex-hepta-intelligence -p codex-hepta-agentd`. The command is a test invocation, not a stored result. Exact-head and deterministic-merge workflow receipts, skips and target-host measurements must be inspected before elevating the claim boundary.
""",
    """In `codex-rs`, run `just test -p codex-hepta-intelligence -p codex-hepta-agentd`. The command is a test invocation, not a stored result. Exact-head and deterministic-merge workflow receipts, skips and target-host measurements must be inspected before elevating the claim boundary.

The default package run does not enable `qualification-legacy-learning-write`. Decision/Outcome append and reopen cases behind that feature are qualification-only evidence; they do not prove that the normal Agentd binary has composed a production `LedgerWriter`. A configured runner without a concrete host-owned invocation provider likewise does not prove daemon product execution.
""",
)

replace_once(
    "qualification/module-execution-dossiers/detail/intelligence.control.md",
    """- `codex-rs/hepta-intelligence/src/canonical_tests.rs`: seven-owner order with first-class NDU, abstention truncation, post-call generation drift, key rotation, wrong-owner receipt and duplicate candidate rejection.
""",
    """- `codex-rs/hepta-intelligence/src/canonical_tests.rs`: seven-owner order with first-class NDU, abstention truncation, post-call generation drift, key rotation, wrong-owner receipt, duplicate rejection, legal-set membership and positive selected propensity.
""",
)

replace_once(
    "qualification/module-execution-dossiers/detail/intelligence.control.md",
    """These are executable source tests. They become exact-candidate evidence only when the repository workflows execute them on the exact head and deterministic merge candidate. Target-host resource evidence remains a separate receipt.
""",
    """These are executable source tests. They become exact-candidate evidence only when the repository workflows execute them on the exact head and deterministic merge candidate. Target-host resource evidence remains a separate receipt. Tests gated by `qualification-legacy-learning-write` prove only the legacy qualification adapter; they are not evidence that the normal daemon has installed the product learning writer or a concrete invocation provider.
""",
)

trace_path = Path("docs/modules/intelligence.control/TEST_TRACEABILITY.json")
trace = json.loads(trace_path.read_text())
operations = {operation["operation"]: operation for operation in trace["operations"]}
prepare_tests = operations["prepare_intelligence_run"]["tests"]
for test in (
    "codex-rs/hepta-intelligence/src/canonical_tests.rs::selected_candidate_must_belong_to_the_frozen_legal_set",
    "codex-rs/hepta-intelligence/src/canonical_tests.rs::selected_candidate_requires_positive_propensity",
):
    if test not in prepare_tests:
        prepare_tests.append(test)

for name in (
    "AgentdIntelligenceProductRunnerV1::append_decision",
    "AgentdIntelligenceProductRunnerV1::append_outcome",
    "AgentdIntelligenceProductRunnerV1::reconcile_ledger_append",
):
    operations[name]["note"] = (
        "This API is compiled only with qualification-legacy-learning-write; "
        "it is qualification evidence, not default product LedgerWriter composition proof."
    )

ingress = operations["Agentd daemon intelligence ingress"]
ingress["source"] = "codex-rs/hepta-agentd/src/objective_runtime.rs"
ingress["tests"] = []
ingress["note"] = (
    "Authenticated ObjectiveStart routing source exists, but the normal binary does not yet "
    "install a concrete AgentdIntelligenceInvocationProviderV1. Product-route composition and "
    "real-process execution therefore remain unproved."
)
trace["faultCoverage"]["outOfSetSelection"] = "covered_source"
trace["faultCoverage"]["zeroPropensitySelection"] = "covered_source"
trace_path.write_text(json.dumps(trace, indent=2) + "\n")
